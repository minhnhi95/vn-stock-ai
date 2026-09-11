import os
from dotenv import load_dotenv

# CRITICAL: patch vnstock TRƯỚC khi bất kỳ service nào import vnstock.
# vnstock free tier 20 req/min → khi limit hit, thư viện sys.exit() giết worker.
import vnstock_safe  # noqa: F401 - side effect import

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import pandas as pd

# Import services
from stock_service import fetch_stock_data, format_chart_data, clean_symbol, fetch_intraday_summary, is_vn_stock, nan_safe_float
from ai_service import get_ai_analysis, chat_about_stock
from market_service import (
    market_status,
    fetch_realtime_price,
    fetch_fundamentals,
    format_fundamentals_for_prompt,
)
from metric_explainer import explain_for_symbol
from news_service import get_recent_news, format_news_for_prompt, search_news_semantic
from market_universe import VN30_SYMBOLS
from storage_service import (
    get_daily_brief,
    list_brief_dates,
    get_verdict_scan,
    list_verdict_scan_dates,
    clear_real_transactions,
    delete_real_transaction,
    insert_real_transactions,
    list_real_transactions,
)

# === Phase 2 services (guarded imports — skip endpoints if any module fails) ===
try:
    from foreign_service import (
        fetch_foreign_trade_for_symbol,
        fetch_top_foreign_today,
        format_foreign_for_prompt,
    )
    _FOREIGN_OK = True
except Exception as _e:
    print(f"[phase2] foreign_service unavailable: {_e}")
    _FOREIGN_OK = False

try:
    from sector_service import (
        get_sector_heatmap,
        get_vn30_symbols,
        get_vn100_symbols,
    )
    _SECTOR_OK = True
except Exception as _e:
    print(f"[phase2] sector_service unavailable: {_e}")
    _SECTOR_OK = False

try:
    from safety_screen import screen_many, screen_symbol
    _SAFETY_OK = True
except Exception as _e:
    print(f"[phase3] safety_screen unavailable: {_e}")
    _SAFETY_OK = False

# Import có chặn lỗi như các module khác: thiếu hay hỏng thì chỉ mất route kết luận,
# không làm sập cả backend.
try:
    from verdict_engine import verdict_for
    _VERDICT_OK = True
except Exception as _e:
    print(f"[verdict] verdict_engine unavailable: {_e}")
    _VERDICT_OK = False

try:
    from alerts_service import (
        create_alert,
        list_alerts,
        delete_alert,
        check_alerts,
    )
    _ALERTS_OK = True
except Exception as _e:
    print(f"[phase2] alerts_service unavailable: {_e}")
    _ALERTS_OK = False

try:
    from calendar_service import (
        get_dividend_calendar,
        get_upcoming_events,
    )
    _CALENDAR_OK = True
except Exception as _e:
    print(f"[phase2] calendar_service unavailable: {_e}")
    _CALENDAR_OK = False

try:
    from insider_service import get_insider_deals, get_insider_report
    _INSIDER_OK = True
except Exception as _e:
    print(f"[phase2] insider_service unavailable: {_e}")
    _INSIDER_OK = False

try:
    from portfolio_review_service import review_portfolio
    _REVIEW_OK = True
except Exception as _e:
    print(f"[phase2] portfolio_review_service unavailable: {_e}")
    _REVIEW_OK = False

try:
    from broker_import_service import (
        ImportError_,
        build_manual_record,
        parse_broker_csv,
        DEFAULT_BROKER_FEE_RATE,
    )
    from real_portfolio_service import get_real_portfolio, get_trading_stats
    _REAL_OK = True
except Exception as _e:
    print(f"[phase3] real portfolio unavailable: {_e}")
    _REAL_OK = False

try:
    from multitimeframe_service import (
        fetch_multi_timeframe,
        format_mtf_for_prompt,
    )
    _MTF_OK = True
except Exception as _e:
    print(f"[phase2] multitimeframe_service unavailable: {_e}")
    _MTF_OK = False

load_dotenv()

app = FastAPI(title="Vietnamese Stock AI Analyzer API")

# CORS.
#
# Đặt CORS_ORIGINS (phân tách bằng dấu phẩy) thì dùng ĐÚNG danh sách đó — production
# luôn đặt. Không đặt nghĩa là đang chạy local: cho phép localhost và mọi địa chỉ
# mạng nội bộ (10.x, 172.16-31.x, 192.168.x, 100.64-127.x của Tailscale), để mở từ
# điện thoại qua IP Wi-Fi không bị trình duyệt chặn dữ liệu. Danh sách ghim cứng từng
# IP thì hỏng mỗi lần hotspot cấp IP khác. Địa chỉ công khai không bao giờ khớp.
#
# Neo ^...$ là bắt buộc: không có $ thì "http://10.0.0.1.evil.com" khớp phần đầu.
DEV_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)

_env_origins = os.getenv("CORS_ORIGINS")
if _env_origins:
    allow_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
    allow_origin_regex = None
else:
    allow_origins = []
    allow_origin_regex = DEV_ORIGIN_REGEX

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from search_service import search_symbols, get_index as get_search_index
    _SEARCH_OK = True
except Exception as _e:
    print(f"[phase2] search_service unavailable: {_e}")
    _SEARCH_OK = False

# Danh sách dự phòng khi search_service không dựng được index từ vnstock.
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

@app.get("/api/health")
def health():
    """Healthcheck cho Railway/Render — không gọi API ngoài nên luôn trả nhanh."""
    return {
        "status": "ok",
        "services": {
            "foreign": _FOREIGN_OK,
            "sector": _SECTOR_OK,
            "alerts": _ALERTS_OK,
            "calendar": _CALENDAR_OK,
            "insider": _INSIDER_OK,
            "portfolio_review": _REVIEW_OK,
            "multitimeframe": _MTF_OK,
            "search": _SEARCH_OK,
            "real_portfolio": _REAL_OK,
            "safety_screen": _SAFETY_OK,
            "verdict": _VERDICT_OK,
        },
    }


@app.get("/api/stocks/search")
def search_stocks(query: Optional[str] = "", limit: int = 20):
    """
    Tìm mã theo ký hiệu, tên doanh nghiệp hoặc ngành trên toàn bộ danh sách niêm yết.
    """
    query = (query or "").strip()
    limit = max(1, min(50, limit))

    if _SEARCH_OK:
        try:
            # Index dựng được thì kết quả rỗng nghĩa là KHÔNG có mã nào khớp —
            # đó là câu trả lời đúng, không được bịa ra mã 3 chữ cái.
            if get_search_index():
                return search_symbols(query, limit=limit)
        except (SystemExit, Exception) as e:
            print(f"[search] fallback về danh sách tĩnh: {str(e)[:120]}")

    # Fallback: lọc trong danh sách tĩnh.
    upper = query.upper()
    if not upper:
        return POPULAR_STOCKS[:limit]

    results = [s for s in POPULAR_STOCKS if upper in s["symbol"] or upper in s["name"].upper()]
    # Mã VN đúng 3 chữ cái thì cho gợi ý dù không có trong danh sách tĩnh —
    # người dùng vẫn xem được biểu đồ nếu mã có thật.
    if not results and is_vn_stock(upper):
        results.append({"symbol": upper, "name": f"Cổ phiếu {upper}", "exchange": "HOSE / HNX"})
    return results[:limit]

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
    data = fetch_fundamentals(symbol)
    # Giải thích đi kèm luôn trong payload thay vì thành endpoint riêng: nó chỉ là
    # cách đọc của chính những con số này, tách ra thì UI phải chờ hai lần mạng để
    # hiện một panel.
    data["explain"] = explain_for_symbol(symbol, data)
    return data


@app.get("/api/news")
def get_news(symbol: str, limit: int = 5):
    symbol = symbol.strip().upper()
    if not is_vn_stock(symbol):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ mã chứng khoán Việt Nam (3 ký tự).")
    limit = max(1, min(20, limit))
    items = get_recent_news(symbol, limit=limit)
    return {"symbol": symbol, "count": len(items), "items": items}


class NewsSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    apiKey: Optional[str] = None
    symbols: Optional[List[str]] = None


@app.get("/api/vn30")
def api_vn30():
    return {"symbols": VN30_SYMBOLS}


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
def analyze_stock(req: AnalysisRequest, mtf: bool = Query(False, description="Include multi-timeframe analysis")):
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

        # nan_safe_float trả None thay vì NaN: mã mới niêm yết chưa đủ 200 phiên thì EMA200
        # là NaN, mà NaN không phải JSON hợp lệ (và không nên đưa vào prompt AI).
        indicators = {
            "rsi": nan_safe_float(latest_row["RSI"]),
            "macd": nan_safe_float(latest_row["MACD"]),
            "signal": nan_safe_float(latest_row["MACD_Signal"]),
            "hist": nan_safe_float(latest_row["MACD_Hist"]),
            "ema20": nan_safe_float(latest_row["EMA20"]),
            "ema50": nan_safe_float(latest_row["EMA50"]),
            "ema200": nan_safe_float(latest_row["EMA200"]),
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

        # Phase 2: foreign trade context (best-effort, never break the analyze flow)
        foreign_data = None
        foreign_summary = ""
        if _FOREIGN_OK:
            try:
                foreign_data = fetch_foreign_trade_for_symbol(symbol)
                foreign_summary = format_foreign_for_prompt(foreign_data) or ""
            except Exception as fe:
                print(f"[analyze] foreign fetch failed for {symbol}: {fe}")

        # Phase 2 (opt-in): multi-timeframe context
        mtf_data = None
        mtf_summary = ""
        if mtf and _MTF_OK:
            try:
                mtf_data = fetch_multi_timeframe(symbol)
                mtf_summary = format_mtf_for_prompt(mtf_data) or ""
            except Exception as me:
                print(f"[analyze] mtf fetch failed for {symbol}: {me}")

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
            foreign_summary=foreign_summary,
            mtf_summary=mtf_summary,
        )

        response = {
            "symbol": symbol,
            "formatted_symbol": formatted_symbol,
            "current_price": current_price,
            "indicators": indicators,
            "intraday_summary": intraday_summary,
            "fundamentals": fundamentals,
            "news": news_items,
            "analysis": analysis_result,
        }
        if foreign_data is not None:
            response["foreign"] = foreign_data
        if mtf_data is not None:
            response["multitimeframe"] = mtf_data
        return response
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
        
        def _fmt(key, prec=2):
            value = nan_safe_float(latest[key])
            return f"{value:.{prec}f}" if value is not None else "N/A"

        summary = (
            f"Cổ phiếu {symbol} ({formatted_symbol}) đang giao dịch ở giá {latest['Close']:.2f}. "
            f"Các chỉ số kỹ thuật hiện tại: RSI(14)={_fmt('RSI')}, MACD={_fmt('MACD', 4)}, "
            f"EMA20={_fmt('EMA20')}, EMA50={_fmt('EMA50')}.\n"
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

# ===========================================================================
# Phase 2 endpoints
# Each route is gated on its service flag; if a service failed to import the
# endpoint is simply not registered (request returns 404 naturally).
# Defensive: every handler wraps logic in try/except so an unexpected service
# error returns a clean HTTP 500 instead of crashing the worker.
# ===========================================================================

# ---- Foreign trade ----
if _FOREIGN_OK:
    @app.get("/api/foreign/top")
    def api_foreign_top(limit: int = 10):
        try:
            limit = max(1, min(50, limit))
            return fetch_top_foreign_today(top=limit)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi lấy top khối ngoại: {str(e)}")

    @app.get("/api/foreign")
    def api_foreign_symbol(symbol: str):
        try:
            symbol = symbol.strip().upper()
            if not is_vn_stock(symbol):
                raise HTTPException(status_code=400, detail="Chỉ hỗ trợ mã chứng khoán Việt Nam (3 ký tự).")
            data = fetch_foreign_trade_for_symbol(symbol)
            if data is None:
                return {"symbol": symbol, "available": False, "reason": "Không có dữ liệu khối ngoại cho mã này."}
            return data
        except HTTPException:
            raise
        except (SystemExit, Exception) as e:
            return {"symbol": symbol, "available": False, "reason": f"Lỗi dữ liệu khối ngoại: {str(e)[:120]}"}


# ---- Sector heatmap + VN100 ----
# Hardcoded VN30 fallback nếu vnstock rate-limit
_VN30_FALLBACK = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

if _SECTOR_OK:
    @app.get("/api/sectors/heatmap")
    def api_sector_heatmap():
        try:
            return get_sector_heatmap()
        except HTTPException:
            raise
        except (SystemExit, Exception) as e:
            # vnstock rate limit hoặc lỗi network - trả empty thay vì 500
            return {"available": False, "reason": f"Tạm thời không lấy được dữ liệu ngành: {str(e)[:120]}", "sectors": []}

    @app.get("/api/vn100")
    def api_vn100():
        try:
            return {"symbols": get_vn100_symbols()}
        except HTTPException:
            raise
        except (SystemExit, Exception):
            return {"symbols": _VN30_FALLBACK, "fallback": True}


# ---- Alerts ----
class AlertCreateRequest(BaseModel):
    symbol: str
    condition: str
    threshold: float


if _ALERTS_OK:
    @app.get("/api/alerts")
    def api_list_alerts(symbol: Optional[str] = None):
        try:
            sym = symbol.strip().upper() if symbol else None
            return {"alerts": list_alerts(symbol=sym)}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi danh sách cảnh báo: {str(e)}")

    @app.post("/api/alerts")
    def api_create_alert(req: AlertCreateRequest):
        try:
            symbol = req.symbol.strip().upper()
            if not is_vn_stock(symbol):
                raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
            if not req.condition or not req.condition.strip():
                raise HTTPException(status_code=400, detail="Thiếu điều kiện cảnh báo.")
            return create_alert(
                symbol=symbol,
                condition=req.condition.strip(),
                threshold=float(req.threshold),
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi tạo cảnh báo: {str(e)}")

    # Khai báo TRƯỚC /api/alerts/{alert_id}: FastAPI khớp route theo thứ tự, để
    # sau thì 'watch-portfolio' bị nuốt thành alert_id và trả 405.
    @app.post("/api/alerts/watch-portfolio")
    def api_watch_portfolio_news():
        """
        Bật cảnh báo "có tin mới" cho toàn bộ mã đang nắm trong danh mục thật.

        Người mới thường không biết mình cần theo dõi cái gì, mà tin doanh nghiệp
        lại là thứ ảnh hưởng trực tiếp tới tiền họ đang bỏ ra. Một nút bấm là đủ,
        không bắt họ tự tạo từng rule một.
        """
        # Endpoint này nằm trong khối alerts nhưng đọc danh mục thật, mà hai module
        # bật/tắt độc lập nhau.
        if not _REAL_OK:
            raise HTTPException(status_code=503, detail="Danh mục thật chưa khả dụng.")
        try:
            portfolio = get_real_portfolio()
            symbols = [
                p["symbol"]
                for p in (portfolio.get("positions") or [])
                if p.get("symbol") and (p.get("shares") or 0) > 0
            ]
            if not symbols:
                raise HTTPException(
                    status_code=400,
                    detail="Danh mục thật đang trống — nhập sao kê giao dịch trước đã.",
                )

            # Đã có rule đang theo dõi thì bỏ qua, tránh mỗi lần bấm lại đẻ thêm
            # một rule trùng rồi bắn cùng một tin nhiều lần.
            watched = {
                a["symbol"]
                for a in list_alerts()
                if a.get("condition") == "news_new" and a.get("active")
            }
            created = []
            for symbol in symbols:
                if symbol in watched:
                    continue
                created.append(create_alert(symbol=symbol, condition="news_new", threshold=0.0))

            return {
                "created": created,
                "created_count": len(created),
                "skipped": sorted(watched & set(symbols)),
                "symbols": symbols,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi bật theo dõi tin: {str(e)}")

    @app.delete("/api/alerts/{alert_id}")
    def api_delete_alert(alert_id: str):
        try:
            ok = delete_alert(alert_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo.")
            return {"ok": True, "id": alert_id}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi xoá cảnh báo: {str(e)}")

    @app.post("/api/alerts/check")
    def api_check_alerts():
        try:
            triggered = check_alerts()
            return {"triggered": triggered, "count": len(triggered) if isinstance(triggered, list) else 0}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi kiểm tra cảnh báo: {str(e)}")


# ---- Calendar ----
if _CALENDAR_OK:
    @app.get("/api/calendar/upcoming")
    def api_calendar_upcoming(symbols: str = "", days_ahead: int = 30):
        try:
            sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
            if not sym_list:
                # Không truyền mã -> lấy các mã trong danh mục THẬT của người dùng.
                try:
                    if _REAL_OK:
                        data = get_real_portfolio(include_prices=False)
                        sym_list = [p["symbol"] for p in data.get("positions", [])]
                except Exception:
                    sym_list = []
            sym_list = [s for s in sym_list if is_vn_stock(s)]
            if not sym_list:
                return {"dividends": [], "events": [], "symbols": []}

            dividends: List[Dict] = []
            events: List[Dict] = []
            try:
                dividends = get_dividend_calendar(sym_list, days_ahead=days_ahead) or []
            except (SystemExit, Exception) as de:
                print(f"[calendar] dividend fetch failed: {de}")
            try:
                events = get_upcoming_events(sym_list, days_ahead=max(days_ahead, 60)) or []
            except (SystemExit, Exception) as ee:
                print(f"[calendar] events fetch failed: {ee}")

            return {
                "symbols": sym_list,
                "dividends": dividends,
                "events": events,
            }
        except HTTPException:
            raise
        except (SystemExit, Exception) as e:
            return {"symbols": [], "dividends": [], "events": [], "error": str(e)[:120]}


# ---- Insider deals ----
if _INSIDER_OK:
    @app.get("/api/insider")
    def api_insider(symbol: str, days: int = 30):
        try:
            symbol = symbol.strip().upper()
            if not is_vn_stock(symbol):
                raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
            days = max(1, min(365, days))
            # get_insider_report gộp sẵn deals + summary + nhãn kỳ, khớp đúng
            # shape mà InsiderPanel đọc.
            return get_insider_report(symbol, days=days, last_n=50)
        except HTTPException:
            raise
        except (SystemExit, Exception) as e:
            return {"symbol": symbol, "days": days, "deals": [], "error": str(e)[:120]}


# ---- Portfolio review ----
class PortfolioReviewRequest(BaseModel):
    apiKey: Optional[str] = None


if _REVIEW_OK:
    @app.post("/api/portfolio/review")
    def api_portfolio_review(req: PortfolioReviewRequest):
        try:
            return review_portfolio(api_key=req.apiKey)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi đánh giá danh mục: {str(e)}")


# ---- Multi-timeframe ----
if _MTF_OK:
    @app.get("/api/multitimeframe")
    def api_multitimeframe(symbol: str):
        try:
            symbol = symbol.strip().upper()
            if not is_vn_stock(symbol):
                raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
            return fetch_multi_timeframe(symbol)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi đa khung thời gian: {str(e)}")


# ===========================================================================
# Danh mục THẬT
#
# Tách hẳn khỏi /api/portfolio (giả lập). Ở đây không có nút đặt lệnh: app chỉ
# GHI NHẬN những gì đã khớp ở công ty chứng khoán, không kết nối để mua bán hộ.
# ===========================================================================

class ManualTxnRequest(BaseModel):
    date: str
    symbol: str
    side: str
    quantity: int
    price: float
    fee: Optional[float] = None
    tax: Optional[float] = None
    note: Optional[str] = ""


if _REAL_OK:
    # Sao kê cá nhân hiếm khi quá vài trăm KB; chặn sớm để không ôm file lớn
    # vào RAM của dyno free tier.
    MAX_IMPORT_BYTES = 5 * 1024 * 1024

    @app.post("/api/real/import")
    async def api_real_import(
        file: UploadFile = File(...),
        fee_rate: float = Query(DEFAULT_BROKER_FEE_RATE, ge=0, le=0.01),
        dry_run: bool = Query(False, description="Chỉ xem trước, không ghi vào sổ"),
    ):
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="File rỗng.")
        if len(content) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=400, detail="File quá lớn (giới hạn 5 MB).")

        try:
            parsed = parse_broker_csv(content, filename=file.filename or "", fee_rate=fee_rate)
        except ImportError_ as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Không đọc được file: {str(e)[:200]}")

        records = parsed["records"]
        result = {
            "parsed": len(records),
            "skipped_rows": parsed["skipped"][:20],
            "skipped_count": len(parsed["skipped"]),
            "detected_columns": parsed["detected_columns"],
            "fee_from_file": parsed["fee_from_file"],
            "fee_rate_used": parsed["fee_rate_used"],
            "preview": records[:10],
            "dry_run": dry_run,
        }

        if dry_run or not records:
            result["inserted"] = 0
            result["duplicates"] = 0
            return result

        written = insert_real_transactions(records)
        result["inserted"] = written["inserted"]
        result["duplicates"] = written["skipped"]
        return result

    @app.get("/api/real/portfolio")
    def api_real_portfolio(prices: bool = True):
        try:
            return get_real_portfolio(include_prices=prices)
        except HTTPException:
            raise
        except (SystemExit, Exception) as e:
            raise HTTPException(status_code=500, detail=f"Lỗi dựng danh mục: {str(e)[:200]}")

    @app.get("/api/real/transactions")
    def api_real_transactions(symbol: Optional[str] = None):
        sym = symbol.strip().upper() if symbol else None
        return {"transactions": list_real_transactions(sym)}

    @app.post("/api/real/transactions")
    def api_real_add_transaction(req: ManualTxnRequest):
        try:
            record = build_manual_record(
                date=req.date,
                symbol=req.symbol,
                side=req.side,
                quantity=req.quantity,
                price=req.price,
                fee=req.fee,
                tax=req.tax,
                note=req.note or "",
            )
        except ImportError_ as e:
            raise HTTPException(status_code=400, detail=str(e))

        written = insert_real_transactions([record])
        if written["inserted"] == 0:
            raise HTTPException(
                status_code=409,
                detail="Giao dịch này đã có trong sổ (trùng ngày, mã, loại lệnh, khối lượng và giá).",
            )
        return {"ok": True, "transaction": record}

    @app.delete("/api/real/transactions/{txn_id}")
    def api_real_delete_transaction(txn_id: str):
        if not delete_real_transaction(txn_id):
            raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")
        return {"ok": True, "id": txn_id}

    @app.post("/api/real/reset")
    def api_real_reset(confirm: bool = Query(False)):
        # Xoá sổ giao dịch thật là không hoàn tác được -> bắt buộc confirm rõ ràng.
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Cần confirm=true. Thao tác này xoá toàn bộ sổ giao dịch thật và không hoàn tác được.",
            )
        return {"ok": True, "deleted": clear_real_transactions()}

    @app.get("/api/real/stats")
    def api_real_stats(year: Optional[int] = None):
        try:
            return get_trading_stats(year=year)
        except (SystemExit, Exception) as e:
            raise HTTPException(status_code=500, detail=f"Lỗi thống kê: {str(e)[:200]}")


# ===========================================================================
# Bộ lọc an toàn
#
# Không tìm mã tốt — chặn mã nguy hiểm. Toàn bộ tiêu chí là ngưỡng số công khai
# trong safety_screen.py, không dùng AI, không chấm điểm tổng.
# ===========================================================================

class SafetyScreenRequest(BaseModel):
    symbols: Optional[List[str]] = None


if _VERDICT_OK:
    @app.get("/api/verdict")
    def api_verdict(symbol: str):
        """Kết luận có thể cân nhắc mua / chờ thêm / không nên mua — xem verdict_engine."""
        symbol = symbol.strip().upper()
        if not is_vn_stock(symbol):
            raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
        try:
            return verdict_for(symbol)
        except (SystemExit, Exception) as e:
            raise HTTPException(status_code=500, detail=f"Lỗi tính kết luận: {str(e)[:200]}")


if _SAFETY_OK:
    @app.get("/api/safety")
    def api_safety_one(symbol: str):
        symbol = symbol.strip().upper()
        if not is_vn_stock(symbol):
            raise HTTPException(status_code=400, detail="Mã không hợp lệ.")
        try:
            return screen_many([symbol])["results"][0]
        except (SystemExit, Exception) as e:
            raise HTTPException(status_code=500, detail=f"Lỗi kiểm tra an toàn: {str(e)[:200]}")

    @app.post("/api/safety/screen")
    def api_safety_screen(req: SafetyScreenRequest):
        symbols = req.symbols
        if not symbols:
            # Không truyền mã -> kiểm tra chính danh mục thật của người dùng.
            symbols = []
            if _REAL_OK:
                try:
                    data = get_real_portfolio(include_prices=False)
                    symbols = [p["symbol"] for p in data.get("positions", [])]
                except Exception:
                    symbols = []
            if not symbols:
                symbols = VN30_SYMBOLS[:8]

        symbols = [s.strip().upper() for s in symbols if s and is_vn_stock(s.strip().upper())]
        if not symbols:
            raise HTTPException(status_code=400, detail="Không có mã hợp lệ nào.")
        try:
            return screen_many(symbols)
        except (SystemExit, Exception) as e:
            raise HTTPException(status_code=500, detail=f"Lỗi quét: {str(e)[:200]}")


# ===========================================================================
# Bản tin hằng ngày
#
# Chỉ ĐỌC từ DB. Nội dung do job nền (jobs/daily_brief.py) sinh ra bằng
# Antigravity CLI trên máy người dùng — app web không gọi AI, nên mở lên là có
# ngay và deploy được ở nơi không có quyền truy cập tài khoản AI.
# ===========================================================================

@app.get("/api/brief")
def api_brief(date: Optional[str] = None):
    brief = get_daily_brief(date)
    if brief is None:
        return {
            "available": False,
            "reason": (
                "Chưa có bản tin nào. Chạy `python -m jobs.daily_brief` trong thư mục "
                "backend, hoặc đặt lịch chạy tự động mỗi sáng."
            ),
            "dates": list_brief_dates(limit=10),
        }
    brief["available"] = True
    return brief


@app.get("/api/brief/dates")
def api_brief_dates(limit: int = 30):
    return {"dates": list_brief_dates(limit=max(1, min(180, limit)))}


# Chỉ ĐỌC từ DB. Job nền (jobs/verdict_scan.py) tự quét cả rổ sau giờ đóng cửa —
# một lượt mất ~20 phút vì hạn mức vnstock nên không chạy trong request.
@app.get("/api/verdict/scan")
def api_verdict_scan(date: Optional[str] = None):
    scan = get_verdict_scan(date)
    if scan is None:
        return {
            "available": False,
            "reason": (
                "Chưa có lượt quét nào. Job tự chạy lúc 15:30 các ngày thứ 2 đến thứ 6, "
                "hoặc chạy tay file run_verdict_scan.bat."
            ),
            "dates": list_verdict_scan_dates(limit=10),
        }
    scan["available"] = True
    return scan


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=True)  # 8765 = API_BASE mặc định của frontend
