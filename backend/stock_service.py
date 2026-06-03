import pandas as pd
import yfinance as yf
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
    """Check if the symbol is a 3-character Vietnamese stock ticker"""
    return len(symbol) == 3 and symbol.isalpha()

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

def fetch_stock_data(symbol: str, period: str = "6mo", interval: str = "1d"):
    """
    Fetch stock data. Uses vnstock (KBS source) for Vietnamese stocks,
    and falls back to Yahoo Finance for US stocks.
    """
    symbol = clean_symbol(symbol)
    
    if is_vn_stock(symbol) and HAS_VNSTOCK:
        # Fetch from vnstock
        try:
            # Parse period to start and end dates
            end_date = datetime.now()
            if period == "1mo":
                days = 30
            elif period == "3mo":
                days = 90
            elif period == "6mo":
                days = 180
            elif period == "1y":
                days = 365
            else:
                days = 180
                
            start_date = end_date - timedelta(days=days)
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
            df = ticker.history(period=period, interval=interval)
    else:
        # US/International stock - use yfinance directly
        formatted_symbol = symbol
        ticker = yf.Ticker(formatted_symbol)
        df = ticker.history(period=period, interval=interval)

    if df is None or df.empty:
        return None, f"Cannot fetch data for symbol: {symbol}"

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
    
    # Fill NaN values with sensible defaults
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.ffill().bfill()
    
    # Add ticker column
    df['Symbol'] = formatted_symbol
    
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
        return f"Dữ liệu khớp lệnh thời gian thực: Gặp lỗi khi tải: {str(e)}"

def format_chart_data(df: pd.DataFrame):
    chart_data = []
    for idx, row in df.iterrows():
        # Convert index to timestamp in seconds
        timestamp = int(idx.timestamp())
        chart_data.append({
            "time": timestamp,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
            "ema20": float(row["EMA20"]),
            "ema50": float(row["EMA50"]),
            "ema200": float(row["EMA200"]),
            "rsi": float(row["RSI"]),
            "macd": float(row["MACD"]),
            "signal": float(row["MACD_Signal"]),
            "hist": float(row["MACD_Hist"])
        })
    return chart_data
