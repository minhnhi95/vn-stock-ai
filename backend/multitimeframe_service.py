"""
Multi-timeframe analysis helper cho cổ phiếu Việt Nam.

Cung cấp 3 timeframe song song:
- Daily 6 tháng — bám theo `stock_service.fetch_stock_data` để giữ nguyên schema
  cột Open/High/Low/Close/Volume + chỉ báo (EMA20/50, RSI, MACD).
- Weekly 2 năm — resample dữ liệu daily sang weekly OHLCV rồi tính lại chỉ báo.
- Hourly 1 tháng — gọi vnstock Quote.history với interval='1H'.

Mỗi timeframe trả về snapshot rút gọn (giá trị mới nhất + xu hướng) để inject
vào prompt AI mà không tốn token cho toàn bộ chuỗi thời gian.

Cache TTL trong process (dùng `market_service.TTLCache`):
- Daily / Weekly: 5 phút (chart không đổi nhiều trong phiên)
- Hourly: 60 giây (gần realtime hơn, nhưng tránh spam vnstock)

Defensive: try/except quanh mọi vnstock call, trả về {available: False, reason}
khi fail để FE / AI prompt vẫn render được.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from market_service import TTLCache
from stock_service import (
    calculate_rsi,
    clean_symbol,
    fetch_stock_data,
    is_vn_stock,
)

try:
    from vnstock import Quote
    HAS_VNSTOCK = True
except ImportError:
    HAS_VNSTOCK = False


# ---------- Cache ----------

_cache = TTLCache()

DAILY_TTL_SECONDS = 300.0    # 5 phút
WEEKLY_TTL_SECONDS = 300.0   # 5 phút
HOURLY_TTL_SECONDS = 60.0    # 1 phút


# ---------- Helpers ----------

def _safe_float(value: Any) -> Optional[float]:
    """Ép kiểu float, trả None khi NaN/inf/None để JSON serialize không vỡ."""
    try:
        if value is None:
            return None
        f = float(value)
        if not np.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính EMA20/50, RSI14, MACD trên dataframe đã có cột OHLCV (CamelCase).
    Áp dụng cho mọi timeframe — chỉ báo cùng công thức, chỉ khác chu kỳ nến.
    """
    df = df.copy()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()

    df['RSI'] = calculate_rsi(df['Close'], 14)

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.ffill().bfill()
    return df


def _snapshot(df: pd.DataFrame, timeframe: str) -> Dict[str, Any]:
    """
    Tóm tắt khung thời gian thành 1 dict gọn: giá đóng cửa, EMA, RSI, MACD,
    xu hướng (EMA20 vs EMA50), và biến động % giai đoạn gần đây.
    """
    if df is None or df.empty:
        return {"available": False, "reason": "Không có dữ liệu"}

    last = df.iloc[-1]
    close = _safe_float(last.get('Close'))
    ema20 = _safe_float(last.get('EMA20'))
    ema50 = _safe_float(last.get('EMA50'))
    rsi = _safe_float(last.get('RSI'))
    macd = _safe_float(last.get('MACD'))
    macd_signal = _safe_float(last.get('MACD_Signal'))
    macd_hist = _safe_float(last.get('MACD_Hist'))

    # Xu hướng dựa trên EMA20 vs EMA50: bullish khi EMA20 > EMA50.
    trend = None
    if ema20 is not None and ema50 is not None:
        if ema20 > ema50:
            trend = "uptrend"
        elif ema20 < ema50:
            trend = "downtrend"
        else:
            trend = "sideways"

    # Biến động % từ phiên đầu đến phiên cuối của khung dữ liệu.
    pct_change = None
    if len(df) >= 2:
        first_close = _safe_float(df.iloc[0].get('Close'))
        if first_close and close:
            pct_change = (close - first_close) / first_close * 100.0

    return {
        "available": True,
        "timeframe": timeframe,
        "bars": int(len(df)),
        "last_time": str(df.index[-1]),
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "trend": trend,
        "pct_change_period": pct_change,
    }


# ---------- Daily ----------

def _fetch_daily(symbol: str) -> Dict[str, Any]:
    """Reuse fetch_stock_data (6mo, 1d) — đã có sẵn chỉ báo + fallback yfinance."""
    try:
        df, formatted = fetch_stock_data(symbol, period="6mo", interval="1d")
        if df is None or df.empty:
            return {"available": False, "reason": "fetch_stock_data trả về rỗng"}
        snap = _snapshot(df, "daily")
        snap["symbol"] = formatted
        return snap
    except Exception as e:
        return {"available": False, "reason": f"Lỗi fetch daily: {e}"}


# ---------- Weekly ----------

def _resample_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Resample dataframe daily (index DatetimeIndex, cột OHLCV) sang weekly.
    Dùng nhãn 'W' (mặc định = chủ nhật kết tuần) — phù hợp cho chart kỹ thuật.
    """
    agg = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum',
    }
    weekly = df_daily.resample('W').agg(agg).dropna(subset=['Close'])
    return weekly


def _fetch_weekly(symbol: str) -> Dict[str, Any]:
    """
    Lấy ~2 năm dữ liệu daily rồi resample sang weekly để có đủ EMA50 weekly
    (50 tuần ~ 1 năm). vnstock không hỗ trợ interval='1W' trực tiếp ổn định
    nên resample từ daily là cách an toàn nhất.
    """
    symbol = clean_symbol(symbol)
    try:
        # fetch_stock_data hardcode period mapping (max '1y') → gọi vnstock
        # trực tiếp với 2 năm cho VN, fallback yfinance cho mã quốc tế.
        if is_vn_stock(symbol) and HAS_VNSTOCK:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=730)
            try:
                q = Quote(symbol=symbol, source='KBS')
                df_raw = q.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    interval='1D',
                )
            except Exception as e_kbs:
                # Fallback source VCI nếu KBS lỗi (đồng bộ pattern market_service)
                try:
                    q = Quote(symbol=symbol, source='VCI')
                    df_raw = q.history(
                        start=start_date.strftime("%Y-%m-%d"),
                        end=end_date.strftime("%Y-%m-%d"),
                        interval='1D',
                    )
                except Exception:
                    return {"available": False, "reason": f"vnstock lỗi cả KBS/VCI: {e_kbs}"}

            if df_raw is None or df_raw.empty:
                return {"available": False, "reason": "vnstock trả về rỗng cho 2 năm"}

            # Normalize schema giống stock_service
            df_raw['Date'] = pd.to_datetime(df_raw['time'])
            df_raw.set_index('Date', inplace=True)
            df_daily = pd.DataFrame({
                'Open': df_raw['open'] * 1000.0,
                'High': df_raw['high'] * 1000.0,
                'Low': df_raw['low'] * 1000.0,
                'Close': df_raw['close'] * 1000.0,
                'Volume': df_raw['volume'],
            }, index=df_raw.index)
        else:
            # Mã quốc tế — dùng fetch_stock_data với '1y' (đã là max trong mapping)
            df_daily, _ = fetch_stock_data(symbol, period="1y", interval="1d")
            if df_daily is None or df_daily.empty:
                return {"available": False, "reason": "Không có dữ liệu daily cho weekly resample"}
            # Trim chỉ giữ OHLCV để resample (loại bỏ cột chỉ báo daily không dùng)
            df_daily = df_daily[['Open', 'High', 'Low', 'Close', 'Volume']]

        df_weekly = _resample_weekly(df_daily)
        if df_weekly.empty:
            return {"available": False, "reason": "Weekly resample rỗng"}

        df_weekly = _add_indicators(df_weekly)
        snap = _snapshot(df_weekly, "weekly")
        snap["symbol"] = symbol
        return snap
    except Exception as e:
        return {"available": False, "reason": f"Lỗi weekly: {e}"}


# ---------- Hourly ----------

def _fetch_hourly(symbol: str) -> Dict[str, Any]:
    """
    Lấy ~1 tháng dữ liệu hourly qua vnstock Quote.history với interval='1H'.

    Chỉ áp dụng cho mã VN — yfinance hourly cho mã quốc tế đã được FE xử lý
    qua endpoint chart riêng, không cần trùng lặp ở đây.
    """
    symbol = clean_symbol(symbol)
    if not is_vn_stock(symbol):
        return {"available": False, "reason": "Hourly chỉ hỗ trợ cho mã VN"}
    if not HAS_VNSTOCK:
        return {"available": False, "reason": "vnstock không khả dụng"}

    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # Thử nhiều source vì interval='1H' có thể không đồng nhất giữa provider.
    last_error = None
    for source in ("VCI", "KBS", "TCBS"):
        try:
            q = Quote(symbol=symbol, source=source)
            df_raw = q.history(start=start_str, end=end_str, interval='1H')
            if df_raw is None or df_raw.empty:
                last_error = f"source={source} trả rỗng"
                continue

            df_raw['Date'] = pd.to_datetime(df_raw['time'])
            df_raw.set_index('Date', inplace=True)
            df_hourly = pd.DataFrame({
                'Open': df_raw['open'] * 1000.0,
                'High': df_raw['high'] * 1000.0,
                'Low': df_raw['low'] * 1000.0,
                'Close': df_raw['close'] * 1000.0,
                'Volume': df_raw['volume'],
            }, index=df_raw.index)

            df_hourly = _add_indicators(df_hourly)
            snap = _snapshot(df_hourly, "hourly")
            snap["symbol"] = symbol
            snap["source"] = source
            return snap
        except Exception as e:
            last_error = f"source={source}: {e}"
            continue

    return {"available": False, "reason": last_error or "Không lấy được dữ liệu hourly"}


# ---------- Public API ----------

def fetch_multi_timeframe(symbol: str) -> Dict[str, Any]:
    """
    Lấy snapshot 3 timeframe (daily / weekly / hourly) cho 1 mã.

    Return shape:
        {
            "symbol": "FPT",
            "daily":   {available, close, ema20, ema50, rsi, macd, ..., trend},
            "weekly":  {...},
            "hourly":  {...},
        }

    Mỗi sub-dict có flag `available` — nếu False kèm `reason`.
    Cache riêng theo timeframe để daily/weekly miss cache không kéo hourly đi cùng.
    """
    symbol = clean_symbol(symbol)

    daily = _cache.get_or_set(
        f"mtf:daily:{symbol}", DAILY_TTL_SECONDS, lambda: _fetch_daily(symbol)
    )
    weekly = _cache.get_or_set(
        f"mtf:weekly:{symbol}", WEEKLY_TTL_SECONDS, lambda: _fetch_weekly(symbol)
    )
    hourly = _cache.get_or_set(
        f"mtf:hourly:{symbol}", HOURLY_TTL_SECONDS, lambda: _fetch_hourly(symbol)
    )

    return {
        "symbol": symbol,
        "daily": daily or {"available": False, "reason": "cache miss + producer None"},
        "weekly": weekly or {"available": False, "reason": "cache miss + producer None"},
        "hourly": hourly or {"available": False, "reason": "cache miss + producer None"},
    }


def format_mtf_for_prompt(data: Dict[str, Any]) -> str:
    """
    Tóm tắt 3 timeframe thành đoạn text gọn cho prompt AI.

    Mục tiêu: cung cấp đủ thông tin để AI nhận diện sự đồng pha / phân kỳ
    giữa các khung (vd: daily đang uptrend nhưng hourly đã sang downtrend).
    """
    symbol = data.get("symbol", "?")
    lines = [f"Phân tích đa khung thời gian (mã {symbol}):"]

    def _fmt_section(label: str, snap: Dict[str, Any]) -> str:
        if not snap or not snap.get("available"):
            reason = (snap or {}).get("reason", "Không khả dụng")
            return f"- {label}: KHÔNG KHẢ DỤNG ({reason})"

        def f(v, suffix="", fmt=".2f"):
            if v is None:
                return "N/A"
            return f"{v:{fmt}}{suffix}"

        trend_vn = {
            "uptrend": "TĂNG",
            "downtrend": "GIẢM",
            "sideways": "ĐI NGANG",
        }.get(snap.get("trend"), "N/A")

        return (
            f"- {label} ({snap.get('bars', 0)} nến, mốc {snap.get('last_time', 'N/A')}):\n"
            f"  + Giá đóng cửa: {f(snap.get('close'), ' đ', ',.0f')}\n"
            f"  + EMA20: {f(snap.get('ema20'), ' đ', ',.0f')} | "
            f"EMA50: {f(snap.get('ema50'), ' đ', ',.0f')} → Xu hướng: {trend_vn}\n"
            f"  + RSI(14): {f(snap.get('rsi'))} | "
            f"MACD: {f(snap.get('macd'))} / Signal: {f(snap.get('macd_signal'))} "
            f"(Hist: {f(snap.get('macd_hist'))})\n"
            f"  + Biến động khung: {f(snap.get('pct_change_period'), '%')}"
        )

    lines.append(_fmt_section("KHUNG TUẦN (Weekly, ~2 năm)", data.get("weekly", {})))
    lines.append(_fmt_section("KHUNG NGÀY (Daily, ~6 tháng)", data.get("daily", {})))
    lines.append(_fmt_section("KHUNG GIỜ (Hourly, ~1 tháng)", data.get("hourly", {})))

    lines.append(
        "\nDiễn giải: nếu cả 3 khung cùng xu hướng → tín hiệu mạnh. "
        "Nếu khung dài (Weekly) tăng nhưng khung ngắn (Hourly) giảm → "
        "có thể là pullback trong xu hướng tăng dài hạn."
    )
    return "\n".join(lines)
