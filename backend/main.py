import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import pandas as pd

# Import services
from stock_service import fetch_stock_data, format_chart_data, clean_symbol, fetch_intraday_summary, is_vn_stock
from ai_service import get_ai_analysis, chat_about_stock
from market_service import (
    market_status,
    fetch_realtime_price,
    fetch_fundamentals,
    format_fundamentals_for_prompt,
)
from news_service import get_recent_news, format_news_for_prompt, search_news_semantic
from backtest_service import run_backtest, run_batch_backtest, VN30_SYMBOLS
from storage_service import (
    get_portfolio,
    get_transactions,
    record_buy,
    record_sell,
    reset_portfolio,
)

load_dotenv()

app = FastAPI(title="Vietnamese Stock AI Analyzer API")

# Setup CORS for Frontend React integration.
# CORS_ORIGINS env var can override (comma-separated).
_default_origins = [
    "http://localhost:5180",
    "http://127.0.0.1:5180",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5273",
    "http://127.0.0.1:5273",
]
_env_origins = os.getenv("CORS_ORIGINS")
allow_origins = [o.strip() for o in _env_origins.split(",") if o.strip()] if _env_origins else _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Vietnamese popular stock tickers
POPULAR_STOCKS = [
    {"symbol": "FPT", "name": "Công ty Cổ phần FPT", "exchange": "HOSE"},
    {"symbol": "HPG", "name": "Tập đoàn Hòa Phát", "exchange": "HOSE"},
    {"symbol": "TCB", "name": "Ngân hàng Techcombank", "exchange": "HOSE"},
    {"symbol": "VNM", "name": "Sữa Việt Nam (Vinamilk)", "exchange": "HOSE"},
    {"symbol": "SSI", "name": "Công ty Cổ phần Chứng khoán SSI", "exchange": "HOSE"},
    {"symbol": "MWG", "name": "Thế Giới Di Động", "exchange": "HOSE"},
    {"symbol": "VIC", "name": "Tập đoàn Vingroup", "exchange": "HOSE"},
    {"symbol": "VND", "name": "Chứng khoán VNDIRECT", "exchange": "HOSE"},
    {"symbol": "ACB", "name": "Ngân hàng Á Châu (ACB)", "exchange": "HNX"},
    {"symbol": "DGC", "name": "Hóa chất Đức Giang", "exchange": "HOSE"},
]

class ChatRequest(BaseModel):
    symbol: str
    message: str
    apiKey: Optional[str] = None

class AnalysisRequest(BaseModel):
    symbol: str
    apiKey: Optional[str] = None

@app.get("/api/stocks/search")
def search_stocks(query: Optional[str] = ""):
    query = query.strip().upper()
    if not query:
        return POPULAR_STOCKS
        
    results = []
    for s in POPULAR_STOCKS:
        if query in s["symbol"] or query in s["name"].upper():
            results.append(s)
            
    # Restrict custom suggestion to exactly 3 uppercase letters (Vietnam format)
    if not results and len(query) == 3 and query.isalpha():
        results.append({
            "symbol": query,
            "name": f"Cổ phiếu {query}",
            "exchange": "HOSE / HNX"
        })
        
    return results

@app.get("/api/market/status")
def get_market_status():
    return market_status()


@app.get("/api/stocks/realtime")
def get_realtime_price(symbol: str):
    symbol = symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ mã chứng khoán Việt Nam (3 ký tự).")
    data = fetch_realtime_price(symbol)
    data["market"] = market_status()
    return data


@app.get("/api/stocks/fundamentals")
def get_fundamentals(symbol: str):
    symbol = symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ mã chứng khoán Việt Nam (3 ký tự).")
    return fetch_fundamentals(symbol)


@app.get("/api/news")
def get_news(symbol: str, limit: int = 5):
    symbol = symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ mã chứng khoán Việt Nam (3 ký tự).")
    limit = max(1, min(20, limit))
    items = get_recent_news(symbol, limit=limit)
    return {"symbol": symbol, "count": len(items), "items": items}


class BacktestRequest(BaseModel):
    symbol: str
    strategy: str = "ema_cross"
    period: str = "1y"
    initial_capital: float = 100_000_000


class BatchBacktestRequest(BaseModel):
    symbols: Optional[List[str]] = None  # None = mặc định VN30
    strategy: str = "ema_cross"
    period: str = "1y"
    initial_capital: float = 100_000_000


class TradeRequest(BaseModel):
    symbol: str
    shares: int
    price: float
    executor: str = "USER"


class NewsSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    apiKey: Optional[str] = None
    symbols: Optional[List[str]] = None


@app.get("/api/portfolio")
def api_get_portfolio():
    return {
        "portfolio": get_portfolio(),
        "transactions": get_transactions(limit=200),
    }


@app.post("/api/portfolio/buy")
def api_buy(req: TradeRequest):
    if req.shares <= 0 or req.price <= 0:
        raise HTTPException(status_code=400, detail="Số lượng và giá phải > 0.")
    if not is_vn_stock(req.symbol.strip().upper()):
        raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
    result = record_buy(req.symbol.strip().upper(), req.shares, req.price, req.executor)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Lệnh thất bại"))
    return {"portfolio": result["portfolio"], "transactions": get_transactions(limit=200)}


@app.post("/api/portfolio/sell")
def api_sell(req: TradeRequest):
    if req.shares <= 0 or req.price <= 0:
        raise HTTPException(status_code=400, detail="Số lượng và giá phải > 0.")
    if not is_vn_stock(req.symbol.strip().upper()):
        raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
    result = record_sell(req.symbol.strip().upper(), req.shares, req.price, req.executor)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Lệnh thất bại"))
    return {"portfolio": result["portfolio"], "transactions": get_transactions(limit=200)}


@app.post("/api/portfolio/reset")
def api_reset():
    return {"portfolio": reset_portfolio(), "transactions": []}


@app.get("/api/vn30")
def api_vn30():
    return {"symbols": VN30_SYMBOLS}


@app.post("/api/backtest/batch")
def api_backtest_batch(req: BatchBacktestRequest):
    symbols = req.symbols or VN30_SYMBOLS
    return run_batch_backtest(
        symbols=symbols,
        strategy=req.strategy,
        period=req.period,
        initial_capital=req.initial_capital,
    )


@app.post("/api/news/search")
def api_news_search(req: NewsSearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Câu truy vấn rỗng.")
    return search_news_semantic(
        query=req.query,
        top_k=max(1, min(20, req.top_k)),
        api_key=req.apiKey,
        symbol_filter=req.symbols,
    )


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    symbol = req.symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ mã chứng khoán Việt Nam (3 ký tự).")
    try:
        return run_backtest(
            symbol=symbol,
            strategy=req.strategy,
            period=req.period,
            initial_capital=req.initial_capital,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi backtest: {str(e)}")


@app.get("/api/stocks/historical")
def get_historical_data(symbol: str, period: str = "6mo", interval: str = "1d"):
    symbol = symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ các mã cổ phiếu thị trường Việt Nam (3 ký tự viết hoa).")
        
    try:
        df, formatted_symbol = fetch_stock_data(symbol, period, interval)
        if df is None:
            raise HTTPException(status_code=404, detail=formatted_symbol)
            
        chart_data = format_chart_data(df)
        return {
            "symbol": symbol,
            "formatted_symbol": formatted_symbol,
            "data": chart_data
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")

@app.post("/api/ai/analyze")
def analyze_stock(req: AnalysisRequest):
    symbol = req.symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ phân tích cổ phiếu Việt Nam.")
        
    try:
        df, formatted_symbol = fetch_stock_data(symbol, period="6mo", interval="1d")
        if df is None:
            raise HTTPException(status_code=404, detail=formatted_symbol)
            
        if len(df) < 2:
            raise HTTPException(status_code=400, detail="Không đủ dữ liệu lịch sử để phân tích.")
            
        latest_row = df.iloc[-1]
        
        indicators = {
            "rsi": float(latest_row["RSI"]),
            "macd": float(latest_row["MACD"]),
            "signal": float(latest_row["MACD_Signal"]),
            "hist": float(latest_row["MACD_Hist"]),
            "ema20": float(latest_row["EMA20"]),
            "ema50": float(latest_row["EMA50"]),
            "ema200": float(latest_row["EMA200"])
        }
        
        last_5 = df.tail(5)
        history_summary_lines = []
        for idx, row in last_5.iterrows():
            history_summary_lines.append(
                f"- Ngày {idx.strftime('%Y-%m-%d')}: Mở={row['Open']:.2f}, Cao={row['High']:.2f}, Thấp={row['Low']:.2f}, Đóng={row['Close']:.2f}, Khối lượng={int(row['Volume'])}"
            )
        history_summary = "\n".join(history_summary_lines)
        
        intraday_summary = fetch_intraday_summary(symbol)
        fundamentals = fetch_fundamentals(symbol)
        fundamentals_summary = format_fundamentals_for_prompt(fundamentals)
        news_items = get_recent_news(symbol, limit=5)
        news_summary = format_news_for_prompt(news_items)

        current_price = float(latest_row["Close"])
        analysis_result = get_ai_analysis(
            symbol=symbol,
            current_price=current_price,
            indicators=indicators,
            history_summary=history_summary,
            intraday_summary=intraday_summary,
            api_key=req.apiKey,
            fundamentals_summary=fundamentals_summary,
            news_summary=news_summary,
        )

        return {
            "symbol": symbol,
            "formatted_symbol": formatted_symbol,
            "current_price": current_price,
            "indicators": indicators,
            "intraday_summary": intraday_summary,
            "fundamentals": fundamentals,
            "news": news_items,
            "analysis": analysis_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi phân tích AI: {str(e)}")

@app.post("/api/ai/chat")
def chat(req: ChatRequest):
    symbol = req.symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ chat về cổ phiếu Việt Nam.")
        
    try:
        df, formatted_symbol = fetch_stock_data(symbol, period="3mo", interval="1d")
        if df is None:
            raise HTTPException(status_code=404, detail=formatted_symbol)
            
        latest = df.iloc[-1]
        intraday_summary = fetch_intraday_summary(symbol)
        
        summary = (
            f"Cổ phiếu {symbol} ({formatted_symbol}) đang giao dịch ở giá {latest['Close']:.2f}. "
            f"Các chỉ số kỹ thuật hiện tại: RSI(14)={latest['RSI']:.2f}, MACD={latest['MACD']:.4f}, "
            f"EMA20={latest['EMA20']:.2f}, EMA50={latest['EMA50']:.2f}.\n"
            f"{intraday_summary}"
        )
        
        answer = chat_about_stock(
            symbol=symbol,
            message=req.message,
            chart_data_summary=summary,
            api_key=req.apiKey
        )
        
        return {"answer": answer}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi chat AI: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
