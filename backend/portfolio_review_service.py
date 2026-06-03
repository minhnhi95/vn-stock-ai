"""
AI Portfolio Review — phân tích sức khỏe toàn bộ danh mục thay vì 1 mã đơn lẻ.

Quy trình:
1. Đọc portfolio hiện tại từ storage_service.get_portfolio()
2. Với mỗi holding: fetch giá thời gian thực + chỉ báo kỹ thuật + sector lookup
3. Tính các metric rủi ro:
   - Concentration: 1 mã > 30% NAV
   - Sector exposure: 1 ngành > 40%
   - Correlation pairs: tương quan giá (proxy bằng pearson trên close 6 tháng)
   - Risk-adjusted return so với VNIndex
4. Đẩy snapshot vào Gemini → structured JSON khuyến nghị rebalance

Cache 10 phút (review nặng — tránh spam khi user click liên tục).
Tất cả comment + reason tiếng Việt theo convention dự án.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from market_service import TTLCache, fetch_realtime_price
from stock_service import fetch_stock_data
import storage_service

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

try:
    from vnstock import Company, Listing
    HAS_VNSTOCK = True
except ImportError:
    HAS_VNSTOCK = False

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
REVIEW_TTL_SECONDS = 600.0  # 10 phút — review tốn nhiều call, cache khá lâu
SECTOR_TTL_SECONDS = 86400.0  # 1 ngày — sector hiếm khi đổi
HISTORY_TTL_SECONDS = 1800.0  # 30 phút cho chuỗi close làm correlation

# Ngưỡng cảnh báo (có thể điều chỉnh)
CONCENTRATION_THRESHOLD_PCT = 30.0  # 1 mã > 30% NAV
SECTOR_THRESHOLD_PCT = 40.0  # 1 ngành > 40% NAV
CORRELATION_THRESHOLD = 0.75  # 2 mã correlation > 0.75 = thực tế 1 bet
HIGH_CORRELATION_TRIGGER_PAIRS = 3  # >= 3 cặp correlation cao = correlation risk

# Fallback sector map cho VN30 + một số mã phổ biến (dùng khi vnstock fail).
# Nguồn: HSX industry classification (ICB level 2 đã chuẩn hóa tiếng Việt).
_SECTOR_FALLBACK: Dict[str, str] = {
    # Ngân hàng
    "VCB": "Ngân hàng", "BID": "Ngân hàng", "CTG": "Ngân hàng", "TCB": "Ngân hàng",
    "MBB": "Ngân hàng", "ACB": "Ngân hàng", "VPB": "Ngân hàng", "HDB": "Ngân hàng",
    "STB": "Ngân hàng", "SHB": "Ngân hàng", "TPB": "Ngân hàng", "VIB": "Ngân hàng",
    "SSB": "Ngân hàng", "OCB": "Ngân hàng", "EIB": "Ngân hàng", "LPB": "Ngân hàng",
    "MSB": "Ngân hàng", "NAB": "Ngân hàng",
    # Bất động sản
    "VIC": "Bất động sản", "VHM": "Bất động sản", "VRE": "Bất động sản",
    "NVL": "Bất động sản", "PDR": "Bất động sản", "KDH": "Bất động sản",
    "DXG": "Bất động sản", "NLG": "Bất động sản", "BCM": "Bất động sản",
    "KBC": "Bất động sản", "DIG": "Bất động sản", "CEO": "Bất động sản",
    # Thép & Vật liệu
    "HPG": "Thép & Vật liệu", "HSG": "Thép & Vật liệu", "NKG": "Thép & Vật liệu",
    "POM": "Thép & Vật liệu", "TLH": "Thép & Vật liệu",
    # Chứng khoán
    "SSI": "Chứng khoán", "VND": "Chứng khoán", "HCM": "Chứng khoán",
    "VCI": "Chứng khoán", "MBS": "Chứng khoán", "SHS": "Chứng khoán",
    "FTS": "Chứng khoán", "BSI": "Chứng khoán", "VIX": "Chứng khoán",
    # Công nghệ
    "FPT": "Công nghệ", "CMG": "Công nghệ", "ELC": "Công nghệ",
    # Bán lẻ & Tiêu dùng
    "MWG": "Bán lẻ", "PNJ": "Bán lẻ", "DGW": "Bán lẻ", "FRT": "Bán lẻ",
    "VNM": "Tiêu dùng", "MSN": "Tiêu dùng", "SAB": "Tiêu dùng", "MCH": "Tiêu dùng",
    "QNS": "Tiêu dùng", "KDC": "Tiêu dùng", "VHC": "Tiêu dùng",
    # Năng lượng & Dầu khí
    "GAS": "Dầu khí", "PLX": "Dầu khí", "BSR": "Dầu khí", "PVD": "Dầu khí",
    "PVS": "Dầu khí", "POW": "Năng lượng", "NT2": "Năng lượng", "GEG": "Năng lượng",
    "REE": "Năng lượng",
    # Vận tải & Logistics
    "VJC": "Vận tải", "HVN": "Vận tải", "GMD": "Vận tải", "VOS": "Vận tải",
    # Cao su & Nông nghiệp
    "GVR": "Cao su", "DPR": "Cao su", "PHR": "Cao su",
    # Bảo hiểm
    "BVH": "Bảo hiểm", "BMI": "Bảo hiểm", "MIG": "Bảo hiểm",
    # Xây dựng & Hạ tầng
    "CTD": "Xây dựng", "HBC": "Xây dựng", "VCG": "Xây dựng", "C4G": "Xây dựng",
}


_cache = TTLCache()


# ---------- Sector lookup ----------

def _lookup_sector_vnstock(symbol: str) -> Optional[str]:
    """Thử lấy ngành (industry/sector) qua vnstock Company hoặc Listing.

    vnstock 4.0.4: Company(symbol, source='VCI').overview() có cột 'industry'
    hoặc 'icb_name'. Listing().symbols_by_industries() trả mapping nhưng nặng.
    """
    if not HAS_VNSTOCK:
        return None
    # Path 1: Company overview — nhanh nhất
    for src in ("VCI", "TCBS"):
        try:
            c = Company(symbol=symbol, source=src)
            if hasattr(c, "overview"):
                df = c.overview()
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    for key in ("industry", "industry_name", "icb_name",
                                "icb_industry_name", "icb_lv2", "sector"):
                        if key in df.columns:
                            v = row.get(key)
                            if v and str(v).strip() and str(v).lower() != "nan":
                                return str(v).strip()
        except Exception:
            continue
    return None


def get_sector(symbol: str) -> str:
    """Trả về ngành của mã. Cache 1 ngày. Fallback map nếu vnstock fail."""
    symbol = symbol.strip().upper()
    cache_key = f"sector:{symbol}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    sector = _lookup_sector_vnstock(symbol) or _SECTOR_FALLBACK.get(symbol) or "Không xác định"
    _cache.set(cache_key, sector, SECTOR_TTL_SECONDS)
    return sector


# ---------- Holding snapshot (price + indicators) ----------

def _fetch_holding_snapshot(symbol: str, shares: int, avg_price: float) -> Dict[str, Any]:
    """Lấy giá hiện tại + chỉ báo kỹ thuật + sector cho 1 holding.

    Defensive: nếu fetch fail trả snapshot với price=avg_price (giá vốn) + lý do,
    để tổng NAV vẫn tính được mà không sai lệch lớn.
    """
    snapshot: Dict[str, Any] = {
        "symbol": symbol,
        "shares": shares,
        "avg_price": avg_price,
        "sector": get_sector(symbol),
    }

    # Giá hiện tại — fetch_realtime_price đã tự cache 5s
    rt = fetch_realtime_price(symbol)
    price = rt.get("price")
    if price is None or price <= 0:
        snapshot["price"] = avg_price  # fallback giá vốn để NAV không lệch
        snapshot["price_available"] = False
        snapshot["price_reason"] = rt.get("error") or "Không lấy được giá"
    else:
        snapshot["price"] = float(price)
        snapshot["price_available"] = True

    snapshot["market_value"] = snapshot["price"] * shares
    snapshot["cost_basis"] = avg_price * shares
    snapshot["pnl"] = snapshot["market_value"] - snapshot["cost_basis"]
    snapshot["pnl_pct"] = (snapshot["pnl"] / snapshot["cost_basis"] * 100.0) if snapshot["cost_basis"] > 0 else 0.0

    # Chỉ báo kỹ thuật — chỉ lấy giá trị mới nhất
    try:
        df, _ = fetch_stock_data(symbol, period="6mo", interval="1d")
        if df is not None and not df.empty:
            last = df.iloc[-1]
            snapshot["rsi"] = float(last["RSI"]) if pd.notna(last["RSI"]) else None
            snapshot["macd_hist"] = float(last["MACD_Hist"]) if pd.notna(last["MACD_Hist"]) else None
            snapshot["ema20"] = float(last["EMA20"]) if pd.notna(last["EMA20"]) else None
            snapshot["ema50"] = float(last["EMA50"]) if pd.notna(last["EMA50"]) else None
            snapshot["indicators_available"] = True
            # Cache chuỗi close để dùng cho correlation matrix sau
            _cache.set(f"close_series:{symbol}", df["Close"].copy(), HISTORY_TTL_SECONDS)
        else:
            snapshot["indicators_available"] = False
    except Exception as e:
        snapshot["indicators_available"] = False
        snapshot["indicators_reason"] = str(e)[:200]

    return snapshot


# ---------- Correlation analysis ----------

def _build_correlation_matrix(symbols: List[str]) -> Optional[pd.DataFrame]:
    """Tính ma trận tương quan pearson trên log-return 6 tháng.

    Trả None nếu < 2 mã có dữ liệu hoặc series không align được.
    """
    if len(symbols) < 2:
        return None
    series_map: Dict[str, pd.Series] = {}
    for sym in symbols:
        s = _cache.get(f"close_series:{sym}")
        if s is None:
            try:
                df, _ = fetch_stock_data(sym, period="6mo", interval="1d")
                if df is not None and not df.empty:
                    s = df["Close"]
                    _cache.set(f"close_series:{sym}", s.copy(), HISTORY_TTL_SECONDS)
            except Exception:
                continue
        if s is not None and len(s) >= 20:
            # Dùng log-return để giảm trend bias, correlation chuẩn xác hơn
            ret = np.log(s / s.shift(1)).dropna()
            series_map[sym] = ret

    if len(series_map) < 2:
        return None

    try:
        # Outer join để tránh mất dữ liệu, sau đó ffill rồi dropna
        df_ret = pd.DataFrame(series_map).dropna(how="any")
        if df_ret.shape[0] < 20:
            return None
        return df_ret.corr(method="pearson")
    except Exception:
        return None


def _extract_high_correlation_pairs(corr_matrix: pd.DataFrame, threshold: float) -> List[Dict[str, Any]]:
    """Trả về list các cặp có |correlation| >= threshold, sort desc."""
    pairs: List[Dict[str, Any]] = []
    symbols = list(corr_matrix.columns)
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            try:
                corr = float(corr_matrix.iloc[i, j])
            except Exception:
                continue
            if pd.isna(corr):
                continue
            if abs(corr) >= threshold:
                pairs.append({"a": a, "b": b, "correlation": round(corr, 3)})
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
    return pairs


# ---------- Risk-adjusted return vs VNIndex ----------

def _fetch_vnindex_return_6mo() -> Optional[float]:
    """Lấy % thay đổi VNIndex 6 tháng qua yfinance (^VNINDEX).

    yfinance đôi khi delay/fail với index VN — defensive trả None.
    """
    if not HAS_YF:
        return None
    cache_key = "vnindex_return_6mo"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        ticker = yf.Ticker("^VNINDEX")
        df = ticker.history(period="6mo", interval="1d")
        if df is None or df.empty or len(df) < 2:
            return None
        ret_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1.0) * 100.0
        result = float(ret_pct)
        _cache.set(cache_key, result, HISTORY_TTL_SECONDS)
        return result
    except Exception:
        return None


def _portfolio_return_6mo(holdings_snapshots: List[Dict[str, Any]]) -> Optional[float]:
    """Tính % return danh mục 6 tháng dùng weighted avg theo cost basis.

    Đơn giản hóa: dùng close 6mo của từng mã, weight = cost_basis / total_cost.
    Bỏ qua mã không có chuỗi close.
    """
    if not holdings_snapshots:
        return None
    total_cost = sum(h["cost_basis"] for h in holdings_snapshots)
    if total_cost <= 0:
        return None
    weighted_ret = 0.0
    weight_used = 0.0
    for h in holdings_snapshots:
        sym = h["symbol"]
        s = _cache.get(f"close_series:{sym}")
        if s is None or len(s) < 2:
            continue
        try:
            ret_pct = (float(s.iloc[-1]) / float(s.iloc[0]) - 1.0) * 100.0
        except Exception:
            continue
        w = h["cost_basis"] / total_cost
        weighted_ret += ret_pct * w
        weight_used += w
    if weight_used <= 0:
        return None
    # Nếu chỉ cover được 1 phần, rescale lên 100% (giả định phần còn lại = avg)
    return weighted_ret / weight_used if weight_used > 0 else None


# ---------- Gemini prompt ----------

def _build_review_prompt(metrics: Dict[str, Any]) -> str:
    """Dựng prompt cho Gemini từ metrics đã tính sẵn."""
    h_lines = []
    for h in metrics["holdings"]:
        rsi = f"{h['rsi']:.1f}" if h.get("rsi") is not None else "N/A"
        macd_h = f"{h['macd_hist']:.3f}" if h.get("macd_hist") is not None else "N/A"
        h_lines.append(
            f"  - {h['symbol']} ({h['sector']}): {h['shares']} CP @ giá vốn {h['avg_price']:,.0f}đ, "
            f"giá hiện tại {h['price']:,.0f}đ, NAV {h['market_value']:,.0f}đ ({h['weight_pct']:.1f}%), "
            f"P&L {h['pnl']:+,.0f}đ ({h['pnl_pct']:+.1f}%), RSI={rsi}, MACD_hist={macd_h}"
        )
    holdings_block = "\n".join(h_lines) if h_lines else "  (Không có cổ phiếu)"

    sector_lines = [f"  - {s['sector']}: {s['weight_pct']:.1f}% NAV ({', '.join(s['symbols'])})"
                    for s in metrics["sector_breakdown"]]
    sector_block = "\n".join(sector_lines) if sector_lines else "  (Không có dữ liệu ngành)"

    corr_pairs = metrics.get("high_correlation_pairs", [])
    if corr_pairs:
        corr_lines = [f"  - {p['a']} ↔ {p['b']}: corr={p['correlation']:+.2f}" for p in corr_pairs[:10]]
        corr_block = "\n".join(corr_lines)
    else:
        corr_block = "  (Không có cặp tương quan cao)"

    vnindex_ret = metrics.get("vnindex_return_6mo")
    port_ret = metrics.get("portfolio_return_6mo")
    vnindex_str = f"{vnindex_ret:+.2f}%" if vnindex_ret is not None else "N/A"
    port_str = f"{port_ret:+.2f}%" if port_ret is not None else "N/A"
    alpha = port_ret - vnindex_ret if (port_ret is not None and vnindex_ret is not None) else None
    alpha_str = f"{alpha:+.2f}%" if alpha is not None else "N/A"

    cash = metrics["cash"]
    nav = metrics["total_nav"]
    cash_pct = (cash / nav * 100.0) if nav > 0 else 0.0

    return f"""
Bạn là Chuyên gia Quản lý Danh mục Đầu tư cấp cao tại thị trường chứng khoán Việt Nam.
Hãy đánh giá TOÀN BỘ danh mục dưới đây và đưa khuyến nghị tái cơ cấu.

[1] TỔNG QUAN DANH MỤC
- Tổng NAV: {nav:,.0f}đ (vốn ban đầu: {metrics['initial_capital']:,.0f}đ)
- Tiền mặt: {cash:,.0f}đ ({cash_pct:.1f}% NAV)
- Số mã nắm giữ: {len(metrics['holdings'])}
- Return danh mục 6 tháng: {port_str}
- Return VNIndex 6 tháng: {vnindex_str}
- Alpha (vs VNIndex): {alpha_str}

[2] CHI TIẾT TỪNG MÃ
{holdings_block}

[3] PHÂN BỔ THEO NGÀNH
{sector_block}

[4] CẶP CỔ PHIẾU TƯƠNG QUAN CAO (|corr| >= {CORRELATION_THRESHOLD})
{corr_block}

[5] CẢNH BÁO TỰ ĐỘNG ĐÃ TÍNH SẴN
- Concentration warning: {metrics.get('concentration_flag', 'OK')}
- Sector warning: {metrics.get('sector_flag', 'OK')}
- Correlation warning: {metrics.get('correlation_flag', 'OK')}

HƯỚNG DẪN CHẤM ĐIỂM:
- overall_score 0-100: phản ánh chất lượng danh mục (đa dạng + alpha + chỉ báo kỹ thuật).
  + > 80: danh mục cân đối, alpha tốt, không có rủi ro tập trung lớn.
  + 60-80: ổn nhưng có 1-2 điểm cần điều chỉnh.
  + 40-60: rủi ro rõ rệt (concentration HOẶC sector HOẶC alpha âm).
  + < 40: nhiều vấn đề chồng chéo, cần tái cơ cấu mạnh.
- risk_level: LOW (đa dạng tốt, không cảnh báo nào), MEDIUM (1 cảnh báo), HIGH (>= 2 cảnh báo HOẶC concentration > 50%).
- recommendation: tổng hợp 2-3 câu — chiến lược chính.
- rebalance_suggestions: 3-5 hành động cụ thể (ví dụ: "Giảm tỷ trọng VCB từ 35% xuống 20% — chốt lời 1 phần",
  "Bổ sung 1 mã ngành Tiêu dùng để giảm phụ thuộc Ngân hàng", "Cắt lỗ ABC do RSI > 80 và MACD đảo chiều").
  Mỗi suggestion 1 câu, hành động rõ ràng, KHÔNG chung chung kiểu "theo dõi sát".

Xuất ra DUY NHẤT một JSON theo cấu trúc dưới, KHÔNG kèm markdown:
{{
  "overall_score": <0-100 integer>,
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "concentration_warning": "<mô tả 1 câu>" hoặc null,
  "sector_warning": "<mô tả 1 câu>" hoặc null,
  "correlation_warning": "<mô tả 1 câu>" hoặc null,
  "recommendation": "<2-3 câu tổng hợp chiến lược>",
  "rebalance_suggestions": ["<hành động 1>", "<hành động 2>", "<hành động 3>"]
}}

LƯU Ý: Phản hồi PHẢI là chuỗi JSON hợp lệ parse được bằng json.loads().
"""


# ---------- Main entry ----------

def _compute_metrics(portfolio: Dict[str, Any]) -> Dict[str, Any]:
    """Tính tất cả metric thuần Python (không gọi LLM) từ portfolio raw."""
    holdings_raw = portfolio.get("holdings", [])
    cash = float(portfolio.get("cash") or 0.0)
    initial_capital = float(portfolio.get("initial_capital") or 0.0)

    # Fetch snapshot cho từng holding
    snapshots: List[Dict[str, Any]] = []
    for h in holdings_raw:
        snap = _fetch_holding_snapshot(
            symbol=h["symbol"],
            shares=int(h.get("shares") or 0),
            avg_price=float(h.get("avgPrice") or 0.0),
        )
        snapshots.append(snap)

    total_holdings_value = sum(s["market_value"] for s in snapshots)
    total_nav = total_holdings_value + cash

    # Gán % NAV cho từng holding (so với total_nav để cash cũng được tính)
    for s in snapshots:
        s["weight_pct"] = (s["market_value"] / total_nav * 100.0) if total_nav > 0 else 0.0

    # Sector breakdown
    sector_map: Dict[str, Dict[str, Any]] = {}
    for s in snapshots:
        sec = s["sector"]
        if sec not in sector_map:
            sector_map[sec] = {"sector": sec, "market_value": 0.0, "symbols": []}
        sector_map[sec]["market_value"] += s["market_value"]
        sector_map[sec]["symbols"].append(s["symbol"])
    sector_breakdown = []
    for sec_info in sector_map.values():
        sec_info["weight_pct"] = (sec_info["market_value"] / total_nav * 100.0) if total_nav > 0 else 0.0
        sector_breakdown.append(sec_info)
    sector_breakdown.sort(key=lambda x: x["weight_pct"], reverse=True)

    # Concentration check
    concentration_flag = None
    top_holding = max(snapshots, key=lambda x: x["weight_pct"], default=None)
    if top_holding and top_holding["weight_pct"] > CONCENTRATION_THRESHOLD_PCT:
        concentration_flag = (
            f"{top_holding['symbol']} chiếm {top_holding['weight_pct']:.1f}% NAV "
            f"(ngưỡng cảnh báo {CONCENTRATION_THRESHOLD_PCT:.0f}%)"
        )

    # Sector exposure check
    sector_flag = None
    if sector_breakdown:
        top_sec = sector_breakdown[0]
        if top_sec["weight_pct"] > SECTOR_THRESHOLD_PCT:
            sector_flag = (
                f"Ngành '{top_sec['sector']}' chiếm {top_sec['weight_pct']:.1f}% NAV "
                f"(ngưỡng cảnh báo {SECTOR_THRESHOLD_PCT:.0f}%)"
            )

    # Correlation matrix
    symbols = [s["symbol"] for s in snapshots]
    corr_matrix = _build_correlation_matrix(symbols)
    high_corr_pairs: List[Dict[str, Any]] = []
    correlation_flag = None
    if corr_matrix is not None:
        high_corr_pairs = _extract_high_correlation_pairs(corr_matrix, CORRELATION_THRESHOLD)
        if len(high_corr_pairs) >= HIGH_CORRELATION_TRIGGER_PAIRS:
            top3 = ", ".join(f"{p['a']}↔{p['b']}" for p in high_corr_pairs[:3])
            correlation_flag = (
                f"Có {len(high_corr_pairs)} cặp cổ phiếu tương quan cao "
                f"(>= {CORRELATION_THRESHOLD}). Top: {top3}. "
                "Danh mục thực tế đặt cược vào ít chủ đề hơn số mã hiển thị."
            )

    # Risk-adjusted return
    vnindex_return = _fetch_vnindex_return_6mo()
    portfolio_return = _portfolio_return_6mo(snapshots)

    return {
        "holdings": snapshots,
        "cash": cash,
        "initial_capital": initial_capital,
        "total_nav": total_nav,
        "total_holdings_value": total_holdings_value,
        "sector_breakdown": sector_breakdown,
        "high_correlation_pairs": high_corr_pairs,
        "concentration_flag": concentration_flag,
        "sector_flag": sector_flag,
        "correlation_flag": correlation_flag,
        "vnindex_return_6mo": vnindex_return,
        "portfolio_return_6mo": portfolio_return,
    }


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    if t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def _heuristic_review(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Khuyến nghị fallback khi không có Gemini API key — dùng rule-based."""
    flags = [metrics.get("concentration_flag"), metrics.get("sector_flag"), metrics.get("correlation_flag")]
    num_flags = sum(1 for f in flags if f)
    top_holding = max(metrics["holdings"], key=lambda x: x["weight_pct"], default=None)
    top_weight = top_holding["weight_pct"] if top_holding else 0.0

    if num_flags >= 2 or top_weight > 50.0:
        risk_level = "HIGH"
        score = 35
    elif num_flags == 1:
        risk_level = "MEDIUM"
        score = 60
    else:
        risk_level = "LOW"
        score = 78

    # Alpha vào điểm
    port_ret = metrics.get("portfolio_return_6mo")
    vn_ret = metrics.get("vnindex_return_6mo")
    if port_ret is not None and vn_ret is not None:
        alpha = port_ret - vn_ret
        score += max(min(int(alpha), 15), -15)
    score = max(0, min(100, score))

    suggestions = []
    if metrics.get("concentration_flag"):
        suggestions.append(f"Giảm tỷ trọng {top_holding['symbol']} — chốt lời 1 phần để đưa về dưới 25% NAV.")
    if metrics.get("sector_flag"):
        top_sec = metrics["sector_breakdown"][0]
        suggestions.append(f"Đa dạng hóa khỏi ngành '{top_sec['sector']}' — bổ sung 1 mã ngành khác.")
    if metrics.get("correlation_flag"):
        suggestions.append("Cân nhắc cắt giảm 1 trong các cặp tương quan cao để giảm rủi ro hệ thống.")
    # Đề xuất kỹ thuật cho từng holding
    for h in metrics["holdings"]:
        if h.get("rsi") is not None and h["rsi"] > 75 and h["pnl_pct"] > 15:
            suggestions.append(f"Cân nhắc chốt lời 1 phần {h['symbol']} — RSI={h['rsi']:.0f} quá mua, đã lãi {h['pnl_pct']:+.0f}%.")
        elif h.get("rsi") is not None and h["rsi"] < 30 and h["pnl_pct"] < -10:
            suggestions.append(f"Xem xét cắt lỗ {h['symbol']} — RSI={h['rsi']:.0f} chưa thoát đáy, đã lỗ {h['pnl_pct']:+.0f}%.")
    if not suggestions:
        suggestions = ["Danh mục đang cân đối — duy trì vị thế và theo dõi tín hiệu kỹ thuật từng mã."]

    return {
        "overall_score": score,
        "risk_level": risk_level,
        "concentration_warning": metrics.get("concentration_flag"),
        "sector_warning": metrics.get("sector_flag"),
        "correlation_warning": metrics.get("correlation_flag"),
        "recommendation": (
            f"Danh mục có mức rủi ro {risk_level}. "
            + ("Cần tái cơ cấu để giảm tập trung." if num_flags >= 1 else "Phân bổ ổn, tiếp tục giữ vị thế.")
        ),
        "rebalance_suggestions": suggestions[:5],
        "source": "heuristic_fallback",
    }


def review_portfolio(api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Phân tích sức khỏe toàn danh mục và trả về khuyến nghị tái cơ cấu.

    Args:
        api_key: Gemini API key. Nếu None/empty, fallback heuristic rule-based.

    Returns:
        Dict: {empty: true} nếu không có holding, hoặc structured review.
    """
    portfolio = storage_service.get_portfolio()
    holdings = portfolio.get("holdings", [])

    if not holdings:
        return {
            "empty": True,
            "reason": "Danh mục chưa có cổ phiếu nào — chưa thể đánh giá.",
            "cash": portfolio.get("cash"),
            "initial_capital": portfolio.get("initial_capital"),
        }

    # Cache key bao gồm danh sách mã + tỷ trọng (xấp xỉ qua shares) — nếu portfolio
    # đổi (mua/bán) thì cache key đổi → tự invalidate.
    holdings_sig = "|".join(f"{h['symbol']}:{h.get('shares', 0)}" for h in sorted(holdings, key=lambda x: x["symbol"]))
    cache_key = f"review:{holdings_sig}:{portfolio.get('cash', 0):.0f}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    metrics = _compute_metrics(portfolio)

    active_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()

    # Nếu thiếu key hoặc lib → heuristic fallback
    if not active_key or not HAS_GENAI:
        result = _heuristic_review(metrics)
        result["metrics"] = metrics
        result["cached"] = False
        _cache.set(cache_key, result, REVIEW_TTL_SECONDS)
        return result

    prompt = _build_review_prompt(metrics)

    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        text = response.text.strip()
        parsed = json.loads(text)
        result = {
            **parsed,
            "metrics": metrics,
            "source": "gemini",
            "cached": False,
        }
        _cache.set(cache_key, result, REVIEW_TTL_SECONDS)
        return result
    except Exception as e_structured:
        # Retry không có mime hint (đôi khi structured mode reject schema phức tạp)
        try:
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = model.generate_content(prompt)
            parsed = json.loads(_strip_json_fence(response.text))
            result = {
                **parsed,
                "metrics": metrics,
                "source": "gemini_fallback",
                "cached": False,
            }
            _cache.set(cache_key, result, REVIEW_TTL_SECONDS)
            return result
        except Exception as e_plain:
            # Fallback cuối cùng: heuristic + ghi lỗi
            err_msg = f"{e_structured} | {e_plain}"
            result = _heuristic_review(metrics)
            result["metrics"] = metrics
            result["source"] = "heuristic_after_gemini_error"
            result["error"] = str(err_msg)[:300]
            result["cached"] = False
            # KHÔNG cache lỗi quá lâu — TTL 60s để retry sớm
            _cache.set(cache_key, result, 60.0)
            return result
