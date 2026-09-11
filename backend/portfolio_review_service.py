"""
AI Portfolio Review — phân tích sức khỏe toàn bộ danh mục thay vì 1 mã đơn lẻ.

Quy trình:
1. Đọc danh mục thật từ real_portfolio_service.get_real_portfolio()
2. Với mỗi holding: fetch giá thời gian thực + chỉ báo kỹ thuật + sector lookup
3. Tính các metric rủi ro:
   - Concentration: 1 mã > 30% NAV
   - Sector exposure: 1 ngành > 40%
   - Correlation pairs: tương quan giá (proxy bằng pearson trên close 6 tháng)
   - Risk-adjusted return so với VNIndex
4. Tùy chọn: Gemini diễn giải các quan sát bằng lời — không chấm điểm, không
   xếp mức rủi ro, không đưa hành động mua/bán (xem verdict_guard).

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
from verdict_guard import FILTER_NOTE, clean_fields

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
    for src in ("VCI", "KBS"):
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


def _lookup_sector_icb(symbol: str) -> Optional[str]:
    """
    Tên ngành ICB cấp 2 tiếng Việt từ sector_service (cache 24h).

    Cùng nguồn với heatmap ngành và bảng trung vị ngành, để một mã không mang hai
    tên ngành khác nhau ở hai panel khác nhau.
    """
    try:
        from sector_service import get_industries
    except Exception:
        return None
    try:
        for industry in get_industries():
            if symbol in (industry.get("symbols") or []):
                return industry.get("name")
    except Exception:
        return None
    return None


def get_sector(symbol: str) -> str:
    """Trả về ngành của mã. Cache 1 ngày. Fallback map nếu vnstock fail."""
    symbol = symbol.strip().upper()
    cache_key = f"sector:{symbol}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # Ưu tiên tên ngành ICB tiếng Việt, cùng nguồn với heatmap và bảng trung vị ngành.
    # Company.overview() trả tên tiếng Anh ("Food & Beverage") nên chỉ dùng cuối cùng.
    sector = (
        _lookup_sector_icb(symbol)
        or _SECTOR_FALLBACK.get(symbol)
        or _lookup_sector_vnstock(symbol)
        or "Không xác định"
    )
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

def _build_review_prompt(metrics: Dict[str, Any], observations: List[str]) -> str:
    """
    Dựng prompt nhờ Gemini DIỄN GIẢI các quan sát đã tính sẵn bằng Python.

    Không xin điểm, không xin mức rủi ro, không xin hành động: với người mới,
    "danh mục 45/100 — bán bớt VCB" là một lệnh, và AI không có căn cứ để ra lệnh
    trên tiền thật của người khác.
    """
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

    cash = metrics["cash"]
    nav = metrics["total_nav"]
    cash_pct = (cash / nav * 100.0) if nav > 0 else 0.0
    obs_block = "\n".join(f"  - {o}" for o in observations) if observations else "  (Không có)"

    return f"""
Bạn đang giải thích danh mục cổ phiếu của một người MỚI đầu tư, bằng tiếng Việt đời thường.

[1] TỔNG QUAN DANH MỤC
- Tổng NAV: {nav:,.0f}đ (vốn ban đầu: {metrics['initial_capital']:,.0f}đ)
- Tiền mặt: {cash:,.0f}đ ({cash_pct:.1f}% NAV)
- Số mã nắm giữ: {len(metrics['holdings'])}
- Biến động 6 tháng của các mã trong danh mục (bình quân theo vốn): {port_str}
- VN-Index 6 tháng: {vnindex_str}

[2] CHI TIẾT TỪNG MÃ
{holdings_block}

[3] PHÂN BỔ THEO NGÀNH
{sector_block}

[4] CẶP CỔ PHIẾU TƯƠNG QUAN CAO (|corr| >= {CORRELATION_THRESHOLD})
{corr_block}

[5] CẢNH BÁO NGƯỠNG ĐÃ TÍNH SẴN
- Tập trung một mã: {metrics.get('concentration_flag') or 'Không'}
- Tập trung một ngành: {metrics.get('sector_flag') or 'Không'}
- Tương quan: {metrics.get('correlation_flag') or 'Không'}

[6] QUAN SÁT ĐÃ TÍNH SẴN
{obs_block}

QUY TẮC BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG đưa hành động: không bảo mua thêm, bán bớt, chốt lời, cắt lỗ hay tái
   cơ cấu. Không chấm điểm, không xếp mức rủi ro cao hay thấp.
2. Chỉ giải thích các quan sát trên nghĩa là gì với tiền của người này. Không bịa số.
3. Viết như đang giải thích cho người thân chưa từng đầu tư.

Xuất ra DUY NHẤT một JSON theo cấu trúc dưới, KHÔNG kèm markdown:
{{
  "dien_giai": "<3-5 câu diễn giải các quan sát>",
  "rui_ro_chinh": ["<2-3 rủi ro cụ thể, dựa trên quan sát>"]
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


# Mức giảm giả định dùng trong câu hỏi "nếu mã lớn nhất giảm X%". 20% là mức một
# cổ phiếu Việt Nam giảm trong vài tuần không hiếm, đủ để câu hỏi có sức nặng.
_STRESS_DROP_PCT = 20.0


def _observations(metrics: Dict[str, Any]) -> List[str]:
    """Quan sát thuần số học về danh mục. Mô tả, không phải hành động."""
    obs: List[str] = []
    holdings = metrics["holdings"]
    obs.append(
        f"Danh mục có {len(holdings)} mã, tổng giá trị thị trường {metrics['total_nav']:,.0f}đ."
    )
    top = max(holdings, key=lambda x: x["weight_pct"], default=None)
    if top:
        obs.append(
            f"Mã chiếm tỷ trọng lớn nhất là {top['symbol']} với {top['weight_pct']:.1f}% danh mục."
        )
    sectors = metrics.get("sector_breakdown") or []
    if sectors:
        parts = ", ".join(f"{s['sector']} {s['weight_pct']:.0f}%" for s in sectors[:4])
        obs.append(f"Phân bổ theo ngành: {parts}.")
    pairs = metrics.get("high_correlation_pairs") or []
    if pairs:
        top_pairs = ", ".join(f"{p['a']}–{p['b']}" for p in pairs[:3])
        obs.append(
            f"{len(pairs)} cặp mã có giá thường đi cùng chiều (tương quan từ "
            f"{CORRELATION_THRESHOLD} trở lên): {top_pairs}. Khi một mã giảm, mã kia thường giảm theo."
        )
    port, vn = metrics.get("portfolio_return_6mo"), metrics.get("vnindex_return_6mo")
    if port is not None and vn is not None:
        obs.append(
            f"6 tháng qua, các mã trong danh mục biến động {port:+.1f}% "
            f"(bình quân theo vốn), VN-Index {vn:+.1f}%."
        )
    return obs


def _questions(metrics: Dict[str, Any]) -> List[str]:
    """
    Câu hỏi để người dùng tự trả lời, kèm con số tính sẵn cho cụ thể.

    "Danh mục của bạn quá tập trung" là một phán xét. "Nếu VCB giảm 20% thì cả danh
    mục giảm 10% — bạn chấp nhận được không?" là một phép tính, và người đọc tự quyết.
    """
    qs: List[str] = []
    top = max(metrics["holdings"], key=lambda x: x["weight_pct"], default=None)
    if top and top["weight_pct"] > 0:
        impact = top["weight_pct"] * _STRESS_DROP_PCT / 100.0
        qs.append(
            f"Nếu {top['symbol']} giảm {_STRESS_DROP_PCT:.0f}%, cả danh mục giảm khoảng "
            f"{impact:.1f}%. Bạn có chấp nhận được mức đó không?"
        )
    sectors = metrics.get("sector_breakdown") or []
    if sectors and sectors[0]["weight_pct"] > SECTOR_THRESHOLD_PCT:
        qs.append(
            f"{sectors[0]['weight_pct']:.0f}% danh mục nằm trong ngành {sectors[0]['sector']}. "
            f"Bạn biết gì về những rủi ro riêng của ngành này?"
        )
    if metrics.get("high_correlation_pairs"):
        qs.append(
            "Các mã tương quan cao thường lên xuống cùng lúc. Danh mục của bạn thực sự đang "
            "đặt cược vào bao nhiêu chủ đề khác nhau?"
        )
    qs.append("Bạn đã biết mình sẽ làm gì nếu cả thị trường giảm mạnh trong vài tuần chưa?")
    return qs[:4]


def _base_review(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phần review không cần AI: quan sát + cảnh báo ngưỡng + câu hỏi.

    Luôn có, kể cả khi thiếu API key — đây mới là phần chính. AI (nếu có) chỉ diễn
    giải thêm các quan sát này bằng lời.
    """
    return {
        "quan_sat": _observations(metrics),
        "concentration_warning": metrics.get("concentration_flag"),
        "sector_warning": metrics.get("sector_flag"),
        "correlation_warning": metrics.get("correlation_flag"),
        "cau_hoi": _questions(metrics),
    }


def _real_portfolio_as_holdings() -> Dict[str, Any]:
    """
    Đưa danh mục THẬT về đúng shape mà _compute_metrics đang dùng.

    Danh mục thật không có khái niệm "tiền mặt" (app không biết số dư tài khoản
    của người dùng), nên cash = 0 và mọi phân tích chỉ dựa trên phần cổ phiếu.
    """
    from real_portfolio_service import get_real_portfolio

    data = get_real_portfolio(include_prices=True)
    if data.get("empty"):
        return {"holdings": [], "cash": 0.0, "initial_capital": 0.0}

    holdings = []
    for position in data.get("positions", []):
        if not position.get("price_available"):
            continue
        holdings.append(
            {
                "symbol": position["symbol"],
                "shares": position["shares"],
                "avgPrice": position["avg_cost"],
                "currentPrice": position["price"],
            }
        )
    total_cost = sum(h["shares"] * h["avgPrice"] for h in holdings)
    return {"holdings": holdings, "cash": 0.0, "initial_capital": total_cost}


def review_portfolio(api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Phân tích sức khỏe danh mục THẬT và trả về cảnh báo rủi ro.

    Args:
        api_key: Gemini API key. Nếu None/empty, chỉ trả phần tính bằng Python.

    Returns:
        Dict: {empty: true} nếu chưa có vị thế, hoặc structured review.
    """
    source = "real"
    portfolio = _real_portfolio_as_holdings()
    empty_reason = (
        "Danh mục chưa có vị thế nào (hoặc chưa lấy được giá) — "
        "nhập sao kê giao dịch trước khi đánh giá."
    )

    holdings = portfolio.get("holdings", [])

    if not holdings:
        return {
            "empty": True,
            "portfolio_source": source,
            "reason": empty_reason,
            "cash": portfolio.get("cash"),
            "initial_capital": portfolio.get("initial_capital"),
        }

    # Cache key bao gồm danh sách mã + tỷ trọng (xấp xỉ qua shares) — nếu portfolio
    # đổi (mua/bán) thì cache key đổi → tự invalidate.
    holdings_sig = "|".join(f"{h['symbol']}:{h.get('shares', 0)}" for h in sorted(holdings, key=lambda x: x["symbol"]))
    cache_key = f"review:{source}:{holdings_sig}:{portfolio.get('cash', 0):.0f}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    metrics = _compute_metrics(portfolio)
    metrics["portfolio_source"] = source

    active_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()

    base = _base_review(metrics)

    # Thiếu key hoặc thư viện: vẫn trả đủ phần tính bằng Python — đó mới là phần chính.
    if not active_key or not HAS_GENAI:
        result = {**base, "metrics": metrics, "portfolio_source": source, "source": "python", "cached": False}
        _cache.set(cache_key, result, REVIEW_TTL_SECONDS)
        return result

    prompt = _build_review_prompt(metrics, base["quan_sat"])
    parsed = None
    errors: List[str] = []
    # Thử structured mode trước, rồi thử lại không có mime hint (đôi khi structured
    # mode từ chối schema).
    for use_mime in (True, False):
        try:
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(GEMINI_MODEL)
            if use_mime:
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"},
                )
                parsed = json.loads(response.text.strip())
            else:
                response = model.generate_content(prompt)
                parsed = json.loads(_strip_json_fence(response.text))
            break
        except Exception as e:
            errors.append(str(e))

    result = {**base, "metrics": metrics, "portfolio_source": source, "cached": False}
    if parsed is None:
        result["source"] = "python_after_gemini_error"
        result["error"] = " | ".join(errors)[:300]
        # KHÔNG cache lỗi quá lâu — TTL 60s để retry sớm
        _cache.set(cache_key, result, 60.0)
        return result

    # Chỉ nhận đúng hai trường diễn giải; điểm, mức rủi ro hay "đề xuất" mà mô hình
    # tự thêm đều bị bỏ, và câu mang tính chỉ dẫn bị lọc.
    ai_part, removed = clean_fields(
        parsed if isinstance(parsed, dict) else {}, ("dien_giai",), ("rui_ro_chinh",)
    )
    result.update(ai_part)
    if removed:
        result["da_loc"] = removed
        result["ghi_chu_loc"] = FILTER_NOTE
    result["source"] = "gemini"
    _cache.set(cache_key, result, REVIEW_TTL_SECONDS)
    return result
