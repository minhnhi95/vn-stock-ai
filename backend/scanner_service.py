"""
AI Scanner — quét nhiều mã, trả về top opportunities có AI score.

Mục tiêu:
- Quét hàng loạt mã VN30/VNINDEX trên timeframe daily 6 tháng
- Áp dụng chiến lược ai_ensemble (reuse từ backtest_service) để tìm mã có
  buy signal gần đây (trong 5 phiên cuối)
- Chấm điểm momentum 0-100 dựa trên 4 yếu tố:
    + 40 điểm cho strength signal (số điều kiện ai_ensemble thoả mãn)
    + 30 điểm cho volume confirm (volume vs MA20 volume)
    + 20 điểm cho RSI vùng tốt (40-65 là sweet spot)
    + 10 điểm cho EMA trend (EMA20 vs EMA50, mức chênh)

Defensive:
- Skip mã không đủ data (< 60 phiên)
- ThreadPoolExecutor 8 workers để tránh ban từ vnstock
- Cache TTL 1 giờ để tránh re-scan liên tục
- try/except quanh từng symbol; lỗi 1 mã không làm chết cả scan

API:
- scan_universe(symbols, strategy_filter='ai_ensemble', api_key=None) -> Dict
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from market_service import TTLCache, VN_TZ
from stock_service import fetch_stock_data
from backtest_service import _ai_ensemble_signals, _ema_cross_signals, _rsi_macd_signals


# Cache TTL trong-process, share cho mọi scan request
_scan_cache = TTLCache()

# 1 giờ — scan toàn vũ trụ tốn nhiều I/O, không cần real-time
SCAN_TTL_SECONDS = 3600.0

# Số phiên cuối được coi là "buy signal gần đây"
RECENT_SIGNAL_WINDOW = 5

# Tối thiểu phiên dữ liệu để chấm điểm (đủ EMA50, RSI14, MACD)
MIN_BARS = 60

# Số luồng song song — đồng bộ với backtest_service để tránh ban vnstock
MAX_WORKERS = 8

# Thang điểm chi tiết
STRENGTH_WEIGHT = 40.0
VOLUME_WEIGHT = 30.0
RSI_WEIGHT = 20.0
EMA_WEIGHT = 10.0


# ---------- Helpers chấm điểm ----------

def _strength_score(row: pd.Series, vol_ma: float) -> float:
    """
    Số điều kiện ai_ensemble thoả mãn tại phiên signal (0-4) → quy về 0-40 điểm.
    Logic phải bám sát _ai_ensemble_signals trong backtest_service.
    """
    score = 0
    # Điều kiện 1: xu hướng tăng
    if row["EMA20"] > row["EMA50"]:
        score += 1
    # Điều kiện 2: RSI vùng tích lũy (không quá mua)
    if 40 <= row["RSI"] <= 65:
        score += 1
    # Điều kiện 3: MACD histogram dương (động lực)
    if row["MACD_Hist"] > 0:
        score += 1
    # Điều kiện 4: Volume confirm
    if vol_ma > 0 and row["Volume"] > vol_ma:
        score += 1
    # Quy về thang 0-40
    return (score / 4.0) * STRENGTH_WEIGHT


def _volume_score(row: pd.Series, vol_ma: float) -> float:
    """
    Volume cao hơn MA20 càng nhiều, điểm càng cao. Cap ở 2x MA = full điểm.
    """
    if vol_ma <= 0:
        return 0.0
    ratio = float(row["Volume"]) / vol_ma
    # 1.0x → 0 điểm, 2.0x trở lên → 30 điểm. Tuyến tính giữa.
    if ratio <= 1.0:
        return 0.0
    if ratio >= 2.0:
        return VOLUME_WEIGHT
    return (ratio - 1.0) * VOLUME_WEIGHT


def _rsi_score(rsi: float) -> float:
    """
    RSI trong vùng 45-60 = sweet spot (đang lên, chưa quá mua) → full điểm.
    Càng xa vùng này, điểm càng giảm.
    """
    if rsi != rsi:  # NaN
        return 0.0
    if 45 <= rsi <= 60:
        return RSI_WEIGHT
    # Vùng 40-45 hoặc 60-65 — vẫn ổn, nửa điểm
    if 40 <= rsi < 45 or 60 < rsi <= 65:
        return RSI_WEIGHT * 0.75
    # Vùng 35-40 hoặc 65-72 — yếu hơn
    if 35 <= rsi < 40 or 65 < rsi <= 72:
        return RSI_WEIGHT * 0.4
    # Còn lại — quá bán hoặc quá mua, không phù hợp ai_ensemble
    return 0.0


def _ema_trend_score(row: pd.Series) -> float:
    """
    EMA20 cao hơn EMA50 càng nhiều (theo %), trend càng mạnh.
    Cap ở 5% chênh lệch = full 10 điểm.
    """
    ema20 = float(row["EMA20"])
    ema50 = float(row["EMA50"])
    if ema50 <= 0:
        return 0.0
    if ema20 <= ema50:
        return 0.0
    gap_pct = (ema20 - ema50) / ema50 * 100.0
    if gap_pct >= 5.0:
        return EMA_WEIGHT
    return (gap_pct / 5.0) * EMA_WEIGHT


def _select_strategy_signals(strategy_filter: str):
    """Map tên strategy → hàm tính signals từ backtest_service."""
    if strategy_filter == "ema_cross":
        return _ema_cross_signals
    if strategy_filter == "rsi_macd":
        return _rsi_macd_signals
    # Mặc định: ai_ensemble (yêu cầu của task)
    return _ai_ensemble_signals


# ---------- Quét 1 mã ----------

def _scan_single(symbol: str, strategy_filter: str) -> Optional[Dict[str, Any]]:
    """
    Quét 1 mã. Trả về dict opportunity nếu có buy signal trong RECENT_SIGNAL_WINDOW phiên cuối.
    Trả None nếu không đủ điều kiện (data thiếu, không có signal, lỗi).
    """
    try:
        df, formatted_symbol = fetch_stock_data(symbol, period="6mo", interval="1d")
    except Exception:
        return None

    if df is None or df.empty or len(df) < MIN_BARS:
        # Không đủ data để chấm điểm (cần EMA50 + RSI14 ổn định)
        return None

    try:
        signal_fn = _select_strategy_signals(strategy_filter)
        signals = signal_fn(df)
    except Exception:
        return None

    # Chỉ xét các phiên gần đây — tránh trả về tín hiệu cũ
    recent_window = min(RECENT_SIGNAL_WINDOW, len(signals))
    recent_signals = signals.iloc[-recent_window:]
    buy_indices = np.where(recent_signals.values == 1)[0]
    if len(buy_indices) == 0:
        return None

    # Lấy buy signal mới nhất trong cửa sổ
    # buy_indices index theo recent_signals — chuyển sang index toàn df
    latest_buy_idx_in_window = int(buy_indices[-1])
    latest_buy_idx = len(df) - recent_window + latest_buy_idx_in_window
    signal_age_days = (len(df) - 1) - latest_buy_idx

    signal_row = df.iloc[latest_buy_idx]

    # Volume MA20 tại thời điểm signal — bám sát logic ai_ensemble
    vol_ma_series = df["Volume"].rolling(20, min_periods=1).mean()
    vol_ma_at_signal = float(vol_ma_series.iloc[latest_buy_idx])

    # Chấm 4 thành phần điểm
    strength = _strength_score(signal_row, vol_ma_at_signal)
    volume_pts = _volume_score(signal_row, vol_ma_at_signal)
    rsi_pts = _rsi_score(float(signal_row["RSI"]))
    ema_pts = _ema_trend_score(signal_row)
    total_score = strength + volume_pts + rsi_pts + ema_pts

    # Lấy giá đóng cửa phiên gần nhất (không phải phiên signal) — UI hiển thị giá hiện tại
    latest_row = df.iloc[-1]

    # EMA trend label cho UI
    if latest_row["EMA20"] > latest_row["EMA50"]:
        ema_trend = "up"
    elif latest_row["EMA20"] < latest_row["EMA50"]:
        ema_trend = "down"
    else:
        ema_trend = "flat"

    return {
        "symbol": symbol,
        "formatted_symbol": formatted_symbol,
        "score": round(float(total_score), 2),
        "score_breakdown": {
            "strength": round(float(strength), 2),
            "volume": round(float(volume_pts), 2),
            "rsi": round(float(rsi_pts), 2),
            "ema_trend": round(float(ema_pts), 2),
        },
        "latest_close": float(latest_row["Close"]),
        "signal_age_days": int(signal_age_days),
        "signal_date": df.index[latest_buy_idx].strftime("%Y-%m-%d"),
        "rsi": round(float(latest_row["RSI"]), 2),
        "macd_hist": round(float(latest_row["MACD_Hist"]), 4),
        "ema_trend": ema_trend,
        "ema20": float(latest_row["EMA20"]),
        "ema50": float(latest_row["EMA50"]),
        "volume": int(latest_row["Volume"]),
        "volume_ma20": int(vol_ma_series.iloc[-1]) if not pd.isna(vol_ma_series.iloc[-1]) else 0,
    }


def _scan_single_safe(symbol: str, strategy_filter: str) -> Optional[Dict[str, Any]]:
    """Wrapper bắt mọi exception — 1 mã hỏng không làm chết cả batch."""
    try:
        return _scan_single(symbol, strategy_filter)
    except Exception:
        return None


# ---------- Entry point ----------

def _make_cache_key(symbols: List[str], strategy_filter: str) -> str:
    """
    Hash danh sách symbols để tạo cache key ổn định bất kể thứ tự.
    Dùng MD5 vì chỉ là cache key, không phải security.
    """
    normalized = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    joined = ",".join(normalized) + f"|{strategy_filter}"
    digest = hashlib.md5(joined.encode("utf-8")).hexdigest()[:16]
    return f"scan:{digest}"


def scan_universe(
    symbols: List[str],
    strategy_filter: str = "ai_ensemble",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Quét danh sách mã và trả về top opportunities có buy signal gần đây.

    Args:
        symbols: Danh sách mã cần quét (vd VN30_SYMBOLS).
        strategy_filter: 'ai_ensemble' (mặc định) / 'ema_cross' / 'rsi_macd'.
        api_key: Reserved cho mở rộng (vd gọi AI để diễn giải top picks).
                 Hiện chưa dùng — scanner thuần kỹ thuật để chạy nhanh và rẻ.

    Returns:
        {
          results: [{symbol, score, latest_close, signal_age_days, rsi,
                     macd_hist, ema_trend, ...}, ...],  # sort desc theo score
          scanned_at: ISO timestamp giờ VN,
          scanned_count: int,
          opportunity_count: int,
          strategy_filter: str,
          cached: bool,
        }
    """
    # Khử trùng và chuẩn hoá đầu vào
    cleaned = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not cleaned:
        return {
            "results": [],
            "scanned_at": datetime.now(VN_TZ).isoformat(),
            "scanned_count": 0,
            "opportunity_count": 0,
            "strategy_filter": strategy_filter,
            "cached": False,
            "reason": "Danh sách mã rỗng",
        }

    cache_key = _make_cache_key(cleaned, strategy_filter)
    cached = _scan_cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    opportunities: List[Dict[str, Any]] = []
    start_ts = time.time()

    # I/O bound (vnstock/yfinance) → ThreadPoolExecutor phù hợp
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {
            ex.submit(_scan_single_safe, sym, strategy_filter): sym
            for sym in cleaned
        }
        for future in concurrent.futures.as_completed(future_map):
            result = future.result()
            if result is not None:
                opportunities.append(result)

    # Sort theo score giảm dần — top opportunities lên đầu
    opportunities.sort(key=lambda r: r["score"], reverse=True)

    payload = {
        "results": opportunities,
        "scanned_at": datetime.now(VN_TZ).isoformat(),
        "scanned_count": len(cleaned),
        "opportunity_count": len(opportunities),
        "strategy_filter": strategy_filter,
        "duration_seconds": round(time.time() - start_ts, 2),
        "cached": False,
    }

    _scan_cache.set(cache_key, payload, SCAN_TTL_SECONDS)
    return payload
