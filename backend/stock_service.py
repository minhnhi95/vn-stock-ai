import pandas as pd
import yfinance as yf

from market_service import TTLCache, market_status
from symbol_utils import is_vn_symbol
import numpy as np
from datetime import datetime, timedelta

# Import vnstock Quote
try:
    from vnstock import Quote
    HAS_VNSTOCK = True
except ImportError:
    HAS_VNSTOCK = False

def clean_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    return symbol

def is_vn_stock(symbol: str) -> bool:
    """
    Mã cổ phiếu niêm yết VN hợp lệ.

    Uỷ quyền cho symbol_utils — mã VN được phép chứa số (HT1, NT2, PC1...),
    kiểm tra bằng isalpha() sẽ loại nhầm ~8,5% thị trường.
    """
    return is_vn_symbol(symbol)

# Số ngày lịch tương ứng mỗi period yêu cầu.
_PERIOD_DAYS = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}

# Chỉ báo cần dữ liệu "mồi" trước khoảng hiển thị, nếu không EMA200/RSI ở các nến
# đầu chỉ là giá trị rác (EMA200 = giá đóng cửa nến đầu tiên, RSI = 100).
# 200 phiên ≈ 290 ngày lịch; +60 ngày đệm cho nghỉ lễ.
_WARMUP_CALENDAR_DAYS = 350

# yfinance nhận chuỗi period, không nhận start/end tuỳ ý -> map sang period đủ dài
# rồi cắt lại sau khi tính chỉ báo.
_YF_WARMUP_PERIOD = {
    "1mo": "1y",
    "3mo": "1y",
    "6mo": "2y",
    "1y": "2y",
    "2y": "5y",
    "5y": "10y",
}


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index using Wilder's smoothing"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Wilder's exponential moving average
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / (avg_loss + 1e-10) # Avoid division by zero
    rsi = 100 - (100 / (1.0 + rs))
    return rsi

def _trim_to_period(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Cắt bỏ phần warm-up, chỉ giữ khoảng người dùng yêu cầu (tz-safe)."""
    if df is None or df.empty:
        return df
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=days))
    tz = getattr(df.index, "tz", None)
    if tz is not None:
        cutoff = cutoff.tz_localize(tz)
    trimmed = df[df.index >= cutoff]
    # Mã mới niêm yết có thể ngắn hơn cả khoảng yêu cầu — giữ nguyên thay vì trả rỗng.
    return trimmed if not trimmed.empty else df


# Nến ngày chỉ đổi mỗi phiên (và nến cuối trong lúc mở cửa), nhưng biểu đồ, bộ
# lọc an toàn, bản tin và cảnh báo đều xin CÙNG bộ dữ liệu cho CÙNG một mã. Không
# cache thì mỗi lần mở app là 4-5 request trùng nhau, ăn hết hạn mức 20 req/phút
# của vnstock và các panel sau bị trả rỗng.
_bars_cache = TTLCache()
_BARS_TTL_OPEN_SECONDS = 300.0     # trong phiên: nến cuối còn đổi
_BARS_TTL_CLOSED_SECONDS = 1800.0  # ngoài phiên: dữ liệu đứng yên


def fetch_stock_data(symbol: str, period: str = "6mo", interval: str = "1d"):
    """
    Fetch stock data. Uses vnstock (KBS source) for Vietnamese stocks,
    and falls back to Yahoo Finance for US stocks.

    Luôn tải thêm ~350 ngày lịch trước khoảng yêu cầu để EMA200/RSI/MACD được
    "mồi" đầy đủ, rồi cắt lại đúng khoảng yêu cầu trước khi trả về.

    Kết quả được cache; caller nhận BẢN SAO nên có thể sửa thoải mái.
    """
    symbol = clean_symbol(symbol)
    days = _PERIOD_DAYS.get(period, 180)

    cache_key = f"bars:{symbol}:{period}:{interval}"
    cached = _bars_cache.get(cache_key)
    if cached is not None:
        df_cached, formatted_cached = cached
        return df_cached.copy(), formatted_cached

    if is_vn_stock(symbol) and HAS_VNSTOCK:
        # Fetch from vnstock
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days + _WARMUP_CALENDAR_DAYS)
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            # Use KBS source in vnstock
            q = Quote(symbol=symbol, source='KBS')
            df = q.history(start=start_str, end=end_str, interval=interval)

            if df is not None and not df.empty:
                # Format Columns to match yfinance format
                # vnstock returns columns: time, open, high, low, close, volume
                # Let's map 'time' to index and rename
                df['Date'] = pd.to_datetime(df['time'])
                df.set_index('Date', inplace=True)

                # In vnstock, prices are in thousands (e.g. 73.7 instead of 73700)
                # Multiply prices by 1000 to convert to full VND units
                df['Open'] = df['open'] * 1000.0
                df['High'] = df['high'] * 1000.0
                df['Low'] = df['low'] * 1000.0
                df['Close'] = df['close'] * 1000.0
                df['Volume'] = df['volume']

                # Clean extra columns
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                formatted_symbol = symbol
            else:
                raise Exception("Empty dataframe returned from vnstock")

        except Exception as e:
            print(f"Failed to fetch VN stock {symbol} via vnstock ({str(e)}). Falling back to yfinance...")
            # Fall back to yfinance (FPT.VN)
            formatted_symbol = f"{symbol}.VN"
            ticker = yf.Ticker(formatted_symbol)
            df = ticker.history(period=_YF_WARMUP_PERIOD.get(period, "2y"), interval=interval)
    else:
        # US/International stock - use yfinance directly
        formatted_symbol = symbol
        ticker = yf.Ticker(formatted_symbol)
        df = ticker.history(period=_YF_WARMUP_PERIOD.get(period, "2y"), interval=interval)

    if df is None or df.empty:
        return None, f"Cannot fetch data for symbol: {symbol}"

    df = df.sort_index()

    # Calculate indicators
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()

    # RSI
    df['RSI'] = calculate_rsi(df['Close'], 14)

    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # Nến chưa đủ dữ liệu mồi thì để NaN thay vì bịa số — format_chart_data trả null,
    # main.py bỏ chỉ báo đó ra khỏi prompt AI.
    df = df.replace([np.inf, -np.inf], np.nan)
    for column, min_bars in (('EMA20', 20), ('EMA50', 50), ('EMA200', 200), ('RSI', 15)):
        if len(df) >= min_bars:
            df.iloc[: min_bars - 1, df.columns.get_loc(column)] = np.nan
        else:
            df[column] = np.nan
    df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].ffill()

    df = _trim_to_period(df, days)

    # Add ticker column
    df['Symbol'] = formatted_symbol

    try:
        ttl = _BARS_TTL_OPEN_SECONDS if market_status().get("is_open") else _BARS_TTL_CLOSED_SECONDS
    except Exception:
        ttl = _BARS_TTL_OPEN_SECONDS
    _bars_cache.set(cache_key, (df.copy(), formatted_symbol), ttl)

    return df, formatted_symbol


def fetch_intraday_summary(symbol: str) -> str:
    """
    Fetch intraday active trades summary from vnstock to feed as context to AI.
    """
    symbol = clean_symbol(symbol)
    if not is_vn_stock(symbol) or not HAS_VNSTOCK:
        return "Dữ liệu khớp lệnh trong ngày: Không khả dụng cho mã quốc tế."
        
    try:
        q = Quote(symbol=symbol, source='KBS')
        df_intraday = q.intraday(page_size=40)
        
        if df_intraday is None or df_intraday.empty:
            return "Dữ liệu khớp lệnh thời gian thực hôm nay: Chưa có giao dịch phát sinh."
            
        # Thống kê lượng mua/bán chủ động
        # match_type is lowercase: 'buy' or 'sell'
        buy_vol = df_intraday[df_intraday['match_type'].str.lower() == 'buy']['volume'].sum()
        sell_vol = df_intraday[df_intraday['match_type'].str.lower() == 'sell']['volume'].sum()
        total_vol = buy_vol + sell_vol
        buy_ratio = (buy_vol / total_vol) * 100 if total_vol > 0 else 50
        
        summary_lines = [
            f"Dữ liệu khớp lệnh thời gian thực (0-delay):",
            f"- Tổng khối lượng khớp gần đây: {total_vol:,} CP",
            f"- Tỷ lệ Mua chủ động (Đẩy giá): {buy_ratio:.1f}%",
            f"- Tỷ lệ Bán chủ động (Thoát hàng): {100.0 - buy_ratio:.1f}%",
            f"- Lịch sử 5 lệnh khớp gần nhất:"
        ]
        
        for idx, row in df_intraday.head(5).iterrows():
            trade_time = str(row['time']).split()[-1] # Get time part
            action = "MUA" if str(row['match_type']).lower() == 'buy' else "BÁN"
            price_vnd = float(row['price']) * 1000.0
            summary_lines.append(f"  + [{trade_time}] {action} {int(row['volume']):,} CP giá {price_vnd:,.0f} đ")
            
        return "\n".join(summary_lines)
    except Exception as e:
        # Chuỗi này đi thẳng vào prompt AI — không đổ repr exception của Python
        # vào đó (vô nghĩa với model, chỉ làm nhiễu). Log để dev còn debug được.
        print(f"[intraday] {symbol}: {str(e)[:200]}")
        return (
            "Dữ liệu khớp lệnh thời gian thực: Không lấy được cho phiên này "
            "(ngoài giờ giao dịch hoặc nguồn dữ liệu tạm gián đoạn)."
        )

def nan_safe_float(value):
    """float() nhưng NaN/None -> None, để JSON hợp lệ (NaN không phải JSON chuẩn)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def format_chart_data(df: pd.DataFrame):
    chart_data = []
    for idx, row in df.iterrows():
        # Convert index to timestamp in seconds
        timestamp = int(idx.timestamp())
        chart_data.append({
            "time": timestamp,
            "open": nan_safe_float(row["Open"]),
            "high": nan_safe_float(row["High"]),
            "low": nan_safe_float(row["Low"]),
            "close": nan_safe_float(row["Close"]),
            "volume": int(row["Volume"]) if nan_safe_float(row["Volume"]) is not None else 0,
            "ema20": nan_safe_float(row["EMA20"]),
            "ema50": nan_safe_float(row["EMA50"]),
            "ema200": nan_safe_float(row["EMA200"]),
            "rsi": nan_safe_float(row["RSI"]),
            "macd": nan_safe_float(row["MACD"]),
            "signal": nan_safe_float(row["MACD_Signal"]),
            "hist": nan_safe_float(row["MACD_Hist"]),
        })
    return chart_data
