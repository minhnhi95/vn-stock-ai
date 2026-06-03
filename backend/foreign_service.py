"""
Module quản lý dữ liệu khối ngoại (foreign trade) — TÍN HIỆU QUAN TRỌNG NHẤT
của thị trường chứng khoán Việt Nam.

Nhà đầu tư nước ngoài (NĐTNN) có vốn lớn, thông tin tốt và thường đi trước
dòng tiền nội. Khối ngoại mua ròng mạnh là tín hiệu bullish; bán ròng kéo
dài là tín hiệu bearish.

Exports:
- fetch_foreign_trade_for_symbol(symbol) -> Dict
    Net buy/sell hôm nay + 5 phiên gần nhất cho 1 mã.
- fetch_top_foreign_today(top=10) -> Dict
    Top mua ròng + top bán ròng của thị trường hôm nay.
- format_foreign_for_prompt(data) -> str
    Tiếng Việt, để inject vào AI prompt.

Chiến lược fetch:
1. vnstock 4.0.4 Quote.history() có cột foreign_buy_volume / foreign_sell_volume
   ở một số source — thử trước.
2. Fallback: scrape CafeF (RSS + endpoint thống kê khối ngoại) khi vnstock fail.
3. Cuối cùng: trả {available: false, reason: "..."} để caller xử lý gracefully.

LƯU Ý từ probe Phase 1:
- Trading(symbol, source='VCI').foreign_trade() FAIL với NotImplementedError.
- Quote.history() có thể có một số cột foreign tuỳ source/version → thử
  defensive parse dataframe columns.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from market_service import TTLCache, VN_TZ, now_vn

try:
    from vnstock import Quote
    HAS_QUOTE = True
except ImportError:
    HAS_QUOTE = False


# ---------- Cấu hình ----------

# Khối ngoại update chậm hơn giá khớp lệnh (thường mỗi vài phút), TTL 30s
# vừa đủ tươi mà vẫn giảm tải mạnh khi nhiều client poll.
FOREIGN_TTL_SECONDS = 30.0
TOP_FOREIGN_TTL_SECONDS = 60.0  # Top market cập nhật mỗi phút

USER_AGENT = "Mozilla/5.0 (compatible; VN-Stock-AI/1.0)"

# RSS / endpoint fallback. CafeF chuyên đề khối ngoại.
RSS_CAFEF_FOREIGN = "https://cafef.vn/du-lieu/khoi-ngoai-mua-ban-rong.rss"
RSS_VIETSTOCK_FOREIGN = "https://vietstock.vn/rss/khoi-ngoai-giao-dich.rss"

_cache = TTLCache()


# ---------- Tiện ích ----------

def _safe_int(value: Any) -> Optional[int]:
    """Parse số nguyên, trả None nếu không hợp lệ (NaN, None, str rỗng)."""
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:  # NaN
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _find_col(df_columns, *candidates: str) -> Optional[str]:
    """
    Tìm cột đầu tiên khớp 1 trong candidates (case-insensitive, substring).
    Tương tự pattern _row_value của market_service nhưng cho columns.
    """
    cols_lower = {str(c).lower(): str(c) for c in df_columns}
    # Exact match trước
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    # Fallback substring
    for cand in candidates:
        cand_l = cand.lower()
        for c_lower, c_orig in cols_lower.items():
            if cand_l in c_lower:
                return c_orig
    return None


def _today_vn_str() -> str:
    return now_vn().strftime("%Y-%m-%d")


def _date_n_days_ago(n: int) -> str:
    return (now_vn() - timedelta(days=n)).strftime("%Y-%m-%d")


# ---------- Lấy dữ liệu cho 1 mã ----------

def _fetch_foreign_via_vnstock(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Thử Quote.history() với hi vọng dataframe có cột foreign_buy / foreign_sell.
    vnstock 4.0.4 ở source VCI/TCBS đôi khi expose các cột này.
    Trả None nếu schema không có data khối ngoại.
    """
    if not HAS_QUOTE:
        return None

    # Lấy 10 phiên để cover các kỳ nghỉ + cuối tuần, sau đó cắt 5 phiên có data.
    start = _date_n_days_ago(15)
    end = _today_vn_str()
    last_error: Optional[str] = None

    for source in ("VCI", "TCBS"):
        try:
            q = Quote(symbol=symbol, source=source)
            df = q.history(start=start, end=end, interval="1D")
            if df is None or df.empty:
                continue

            buy_col = _find_col(df.columns, "foreign_buy_volume", "foreign_buy", "fb_volume", "buy_foreign")
            sell_col = _find_col(df.columns, "foreign_sell_volume", "foreign_sell", "fs_volume", "sell_foreign")
            time_col = _find_col(df.columns, "time", "date", "trading_date")

            if buy_col is None or sell_col is None:
                # Source này không expose foreign columns
                continue

            # Sắp xếp theo thời gian giảm dần (mới nhất trước)
            if time_col is not None:
                try:
                    df = df.sort_values(time_col, ascending=False)
                except Exception:
                    pass

            sessions: List[Dict[str, Any]] = []
            for _, row in df.head(5).iterrows():
                buy_vol = _safe_int(row.get(buy_col))
                sell_vol = _safe_int(row.get(sell_col))
                if buy_vol is None and sell_vol is None:
                    continue
                buy_vol = buy_vol or 0
                sell_vol = sell_vol or 0
                sessions.append({
                    "date": str(row.get(time_col, "")) if time_col else "",
                    "buy_volume": buy_vol,
                    "sell_volume": sell_vol,
                    "net_volume": buy_vol - sell_vol,
                })

            if not sessions:
                continue

            today = sessions[0]
            return {
                "symbol": symbol,
                "available": True,
                "source": f"vnstock/{source}",
                "today": today,
                "recent_sessions": sessions,
                "net_5d": sum(s.get("net_volume", 0) for s in sessions),
            }
        except Exception as e:
            last_error = str(e)
            continue

    if last_error:
        print(f"[foreign] vnstock fail for {symbol}: {last_error}")
    return None


def _fetch_foreign_via_cafef_rss(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fallback: parse RSS CafeF khối ngoại, tìm mã trong title/description.
    RSS không cho số liệu chính xác — chỉ cho dấu hiệu định tính (tin xuất hiện = có giao dịch đáng chú ý).
    """
    try:
        req = Request(RSS_CAFEF_FOREIGN, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=6) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[foreign] CafeF RSS fetch failed: {e}")
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[foreign] CafeF RSS parse failed: {e}")
        return None

    pattern = re.compile(rf"\b{re.escape(symbol)}\b", re.IGNORECASE)
    mentions: List[Dict[str, Any]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()
        haystack = f"{title} {desc_clean}"
        if not pattern.search(haystack):
            continue
        mentions.append({
            "title": title,
            "summary": desc_clean[:400],
            "url": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
        })
        if len(mentions) >= 5:
            break

    if not mentions:
        return None

    # Heuristic định tính: nhận diện hướng net (mua/bán ròng) từ từ khoá trong title.
    direction = "UNKNOWN"
    head_text = " ".join(m["title"].lower() for m in mentions[:3])
    if "mua ròng" in head_text:
        direction = "NET_BUY"
    elif "bán ròng" in head_text:
        direction = "NET_SELL"

    return {
        "symbol": symbol,
        "available": True,
        "source": "CafeF/RSS",
        "qualitative_only": True,
        "direction_hint": direction,
        "mentions": mentions,
    }


def fetch_foreign_trade_for_symbol(symbol: str) -> Dict[str, Any]:
    """
    Lấy dữ liệu khối ngoại cho 1 mã: net buy/sell hôm nay + 5 phiên gần nhất.
    Cache 30s. Defensive: thử vnstock trước, fallback RSS CafeF, cuối cùng trả
    {available: false, reason: ...}.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"available": False, "reason": "Thiếu mã chứng khoán"}

    cache_key = f"foreign:symbol:{symbol}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    # 1) vnstock
    data = _fetch_foreign_via_vnstock(symbol)

    # 2) Fallback RSS định tính
    if data is None:
        data = _fetch_foreign_via_cafef_rss(symbol)

    if data is None:
        # Cache cả failure ngắn (10s) để không spam upstream khi feature off.
        result = {
            "symbol": symbol,
            "available": False,
            "reason": (
                "vnstock 4.0.4 không expose dữ liệu khối ngoại cho mã này và "
                "RSS CafeF/Vietstock cũng không có tin nhắc tới mã."
            ),
            "cached": False,
        }
        _cache.set(cache_key, result, 10.0)
        return result

    data.setdefault("cached", False)
    _cache.set(cache_key, data, FOREIGN_TTL_SECONDS)
    return data


# ---------- Top market hôm nay ----------

def _parse_top_from_cafef_rss(direction: str) -> List[Dict[str, Any]]:
    """
    Parse RSS CafeF khối ngoại, trả về list mã được nhắc kèm context.
    direction: 'BUY' hoặc 'SELL' — dùng để filter tin theo từ khoá.
    """
    try:
        req = Request(RSS_CAFEF_FOREIGN, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=6) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[foreign] CafeF RSS top fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[foreign] CafeF RSS top parse failed: {e}")
        return []

    # Pattern mã CK Việt Nam: 3 ký tự hoa (HOSE/HNX) — đôi khi 4 ký tự cho UPCOM phái sinh.
    symbol_pattern = re.compile(r"\b([A-Z]{3,4})\b")
    keyword = "mua ròng" if direction == "BUY" else "bán ròng"

    items: List[Dict[str, Any]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()
        full_text = f"{title} {desc_clean}"

        if keyword not in full_text.lower():
            continue

        # Trích các mã CK xuất hiện (loại stopwords thường gặp).
        stopwords = {"VN", "RSS", "PDF", "HCM", "USA", "FED", "ETF", "CTCK", "CTG", "AGM", "EPS"}
        symbols_in_text = []
        for m in symbol_pattern.findall(full_text):
            if m in stopwords:
                continue
            if m not in symbols_in_text:
                symbols_in_text.append(m)

        for sym in symbols_in_text[:5]:
            items.append({
                "symbol": sym,
                "context_title": title,
                "url": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
            })

    return items


def fetch_top_foreign_today(top: int = 10) -> Dict[str, Any]:
    """
    Top mua ròng + top bán ròng của thị trường hôm nay.
    vnstock 4.0.4 không có endpoint thị trường tổng hợp khối ngoại → dùng RSS
    CafeF làm nguồn định tính. Caller cần biết đây là HEURISTIC, không phải
    bảng xếp hạng chính xác.
    """
    top = max(1, min(int(top), 30))
    cache_key = f"foreign:top:{top}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    buys = _parse_top_from_cafef_rss("BUY")
    sells = _parse_top_from_cafef_rss("SELL")

    if not buys and not sells:
        result = {
            "available": False,
            "reason": (
                "Không lấy được RSS khối ngoại từ CafeF. vnstock free tier "
                "không có endpoint top khối ngoại thị trường."
            ),
            "top_net_buy": [],
            "top_net_sell": [],
            "cached": False,
        }
        _cache.set(cache_key, result, 30.0)
        return result

    # Dedupe theo symbol, giữ entry đầu tiên (mới nhất trong RSS).
    def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out = []
        for it in items:
            s = it.get("symbol")
            if s and s not in seen:
                seen.add(s)
                out.append(it)
        return out

    result = {
        "available": True,
        "source": "CafeF/RSS",
        "qualitative_only": True,
        "fetched_at": now_vn().isoformat(),
        "top_net_buy": _dedupe(buys)[:top],
        "top_net_sell": _dedupe(sells)[:top],
        "cached": False,
    }
    _cache.set(cache_key, result, TOP_FOREIGN_TTL_SECONDS)
    return result


# ---------- Format cho AI prompt ----------

def _fmt_volume(v: Optional[int]) -> str:
    """Định dạng khối lượng dạng dễ đọc (k, triệu)."""
    if v is None:
        return "N/A"
    abs_v = abs(v)
    sign = "-" if v < 0 else ""
    if abs_v >= 1_000_000:
        return f"{sign}{abs_v / 1_000_000:.2f} triệu CP"
    if abs_v >= 1_000:
        return f"{sign}{abs_v / 1_000:.1f}k CP"
    return f"{sign}{abs_v} CP"


def format_foreign_for_prompt(data: Dict[str, Any]) -> str:
    """
    Format dữ liệu khối ngoại sang tiếng Việt để inject vào AI prompt.
    Hỗ trợ 2 shape: per-symbol (fetch_foreign_trade_for_symbol) và
    top-market (fetch_top_foreign_today).
    """
    if not data or not data.get("available"):
        reason = (data or {}).get("reason", "")
        return f"Dữ liệu khối ngoại: Không khả dụng ({reason})."

    # Shape top-market: có top_net_buy / top_net_sell
    if "top_net_buy" in data or "top_net_sell" in data:
        lines = ["Khối ngoại toàn thị trường (heuristic từ tin tức, không phải số liệu chính xác):"]
        buys = data.get("top_net_buy", [])
        sells = data.get("top_net_sell", [])
        if buys:
            syms = ", ".join(b.get("symbol", "?") for b in buys[:10])
            lines.append(f"- Mã được nhắc trong tin MUA RÒNG: {syms}")
        if sells:
            syms = ", ".join(s.get("symbol", "?") for s in sells[:10])
            lines.append(f"- Mã được nhắc trong tin BÁN RÒNG: {syms}")
        if not buys and not sells:
            lines.append("- Không có tin khối ngoại nổi bật.")
        return "\n".join(lines)

    # Shape per-symbol định tính (chỉ có direction_hint từ RSS)
    if data.get("qualitative_only"):
        symbol = data.get("symbol", "?")
        direction = data.get("direction_hint", "UNKNOWN")
        direction_vn = {
            "NET_BUY": "MUA RÒNG (theo tin tức)",
            "NET_SELL": "BÁN RÒNG (theo tin tức)",
            "UNKNOWN": "có giao dịch đáng chú ý (chưa xác định hướng)",
        }.get(direction, "không rõ")
        mentions = data.get("mentions", [])
        lines = [
            f"Khối ngoại với {symbol} (chỉ định tính, không có số liệu):",
            f"- Hướng giao dịch: {direction_vn}",
        ]
        for i, m in enumerate(mentions[:3], 1):
            lines.append(f"  {i}. {m.get('title', '')}")
        return "\n".join(lines)

    # Shape per-symbol đầy đủ (có sessions + net volume)
    symbol = data.get("symbol", "?")
    today = data.get("today", {}) or {}
    sessions = data.get("recent_sessions", []) or []
    net_5d = data.get("net_5d", 0) or 0

    today_net = today.get("net_volume", 0) or 0
    today_buy = today.get("buy_volume", 0) or 0
    today_sell = today.get("sell_volume", 0) or 0

    if today_net > 0:
        today_label = f"MUA RÒNG {_fmt_volume(today_net)}"
    elif today_net < 0:
        today_label = f"BÁN RÒNG {_fmt_volume(abs(today_net))}"
    else:
        today_label = "Cân bằng"

    if net_5d > 0:
        trend_label = f"MUA RÒNG 5 phiên: {_fmt_volume(net_5d)}"
    elif net_5d < 0:
        trend_label = f"BÁN RÒNG 5 phiên: {_fmt_volume(abs(net_5d))}"
    else:
        trend_label = "Khối ngoại trung lập 5 phiên gần nhất"

    lines = [
        f"Khối ngoại với {symbol} (nguồn: {data.get('source', 'N/A')}):",
        f"- Hôm nay ({today.get('date', 'N/A')}): {today_label}",
        f"  (Mua: {_fmt_volume(today_buy)}, Bán: {_fmt_volume(today_sell)})",
        f"- Xu hướng: {trend_label}",
    ]

    if len(sessions) > 1:
        lines.append("- Chi tiết 5 phiên gần nhất:")
        for s in sessions:
            n = s.get("net_volume", 0) or 0
            tag = "MUA" if n > 0 else ("BÁN" if n < 0 else "==")
            lines.append(f"  + {s.get('date', '')}: {tag} ròng {_fmt_volume(abs(n))}")

    return "\n".join(lines)
