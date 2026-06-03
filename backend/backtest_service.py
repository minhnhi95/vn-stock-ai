"""
Backtest engine cho chiến lược kỹ thuật trên cổ phiếu VN.

Tại sao không backtest trực tiếp LLM:
- Gọi Gemini cho mỗi phiên trong 1 năm = ~250 call → đắt + chậm + non-deterministic.
- Thay vào đó: dùng chiến lược kỹ thuật rule-based xấp xỉ logic AI đang dùng.
- Người dùng có thể chọn `ema_cross` (đơn giản) hoặc `rsi_macd` (bám sát chỉ báo AI nhìn).

Chiến lược trả về:
- equity curve theo phiên
- danh sách trades
- metrics: total_return, max_drawdown, win_rate, num_trades, sharpe
- so sánh với buy-and-hold cùng vốn ban đầu

Quy định T+ áp dụng: cổ phiếu vừa mua bị khóa 2 phiên giao dịch.
"""
from __future__ import annotations

import math
import concurrent.futures
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from stock_service import fetch_stock_data


T_PLUS_LOCK_DAYS = 2  # T+2 sau cải cách KRX

STRATEGIES = {"ema_cross", "rsi_macd", "ai_ensemble"}

# VN30 thực tế (cập nhật quý 2025). Có thể điều chỉnh.
VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]


def _ema_cross_signals(df: pd.DataFrame) -> pd.Series:
    """1 = buy, -1 = sell, 0 = hold."""
    cross_up = (df['EMA20'].shift(1) <= df['EMA50'].shift(1)) & (df['EMA20'] > df['EMA50'])
    cross_dn = (df['EMA20'].shift(1) >= df['EMA50'].shift(1)) & (df['EMA20'] < df['EMA50'])
    sig = pd.Series(0, index=df.index)
    sig[cross_up] = 1
    sig[cross_dn] = -1
    return sig


def _rsi_macd_signals(df: pd.DataFrame) -> pd.Series:
    """Buy: RSI < 35 và MACD hist chuyển dương. Sell: RSI > 70 hoặc MACD hist chuyển âm."""
    macd_turn_up = (df['MACD_Hist'].shift(1) <= 0) & (df['MACD_Hist'] > 0)
    macd_turn_dn = (df['MACD_Hist'].shift(1) >= 0) & (df['MACD_Hist'] < 0)
    buy = (df['RSI'] < 35) & macd_turn_up
    sell = (df['RSI'] > 70) | macd_turn_dn
    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    return sig


def _ai_ensemble_signals(df: pd.DataFrame) -> pd.Series:
    """
    Mô phỏng cách AI đánh giá: kết hợp 4 tín hiệu kỹ thuật + volume.
    Buy khi cả 3 trong 4 điều kiện:
      - Xu hướng tăng:    EMA20 > EMA50
      - RSI vùng tích lũy: 40 <= RSI <= 65  (không quá mua)
      - MACD hist > 0     (động lực dương)
      - Volume confirm:    Volume > MA20 của Volume
    Sell khi 2 trong 3 điều kiện:
      - EMA20 < EMA50
      - RSI > 72 (quá mua)
      - MACD hist < 0
    """
    df = df.copy()
    df['VolMA20'] = df['Volume'].rolling(20, min_periods=1).mean()

    trend_up = df['EMA20'] > df['EMA50']
    rsi_ok = (df['RSI'] >= 40) & (df['RSI'] <= 65)
    macd_up = df['MACD_Hist'] > 0
    vol_up = df['Volume'] > df['VolMA20']
    buy_score = trend_up.astype(int) + rsi_ok.astype(int) + macd_up.astype(int) + vol_up.astype(int)
    buy = buy_score >= 3

    trend_dn = df['EMA20'] < df['EMA50']
    rsi_hot = df['RSI'] > 72
    macd_dn = df['MACD_Hist'] < 0
    sell_score = trend_dn.astype(int) + rsi_hot.astype(int) + macd_dn.astype(int)
    sell = sell_score >= 2

    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    # Tạo edge: chỉ phát tín hiệu khi chuyển trạng thái (tránh re-fire mỗi phiên)
    sig = sig.where(sig != sig.shift(1).fillna(0), 0)
    return sig


def _calc_max_drawdown(equity: List[float]) -> float:
    peak = -math.inf
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            dd = (v - peak) / peak * 100.0
            max_dd = min(max_dd, dd)
    return max_dd


def _calc_sharpe(daily_returns: List[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    arr = np.array(daily_returns)
    std = arr.std()
    if std == 0:
        return 0.0
    # Annualize giả sử 252 phiên giao dịch/năm
    return float((arr.mean() / std) * math.sqrt(252))


def run_backtest(
    symbol: str,
    strategy: str = "ema_cross",
    period: str = "1y",
    initial_capital: float = 100_000_000.0,
) -> Dict[str, Any]:
    if strategy not in STRATEGIES:
        raise ValueError(f"Strategy không hợp lệ. Chọn một trong: {sorted(STRATEGIES)}")

    df, formatted_symbol = fetch_stock_data(symbol, period=period, interval="1d")
    if df is None or df.empty or len(df) < 60:
        raise ValueError("Không đủ dữ liệu lịch sử để backtest (cần ít nhất 60 phiên).")

    if strategy == "ema_cross":
        signals = _ema_cross_signals(df)
    elif strategy == "rsi_macd":
        signals = _rsi_macd_signals(df)
    else:
        signals = _ai_ensemble_signals(df)

    cash = initial_capital
    shares = 0
    locked_until = -1  # chỉ số phiên mà cổ phiếu được giải khoá
    trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    daily_returns: List[float] = []
    prev_nav = initial_capital

    closes = df['Close'].values
    dates = df.index

    for i in range(len(df)):
        price = float(closes[i])
        sig = int(signals.iloc[i])
        date_str = dates[i].strftime('%Y-%m-%d')

        if sig == 1 and shares == 0 and i + T_PLUS_LOCK_DAYS < len(df):
            qty = int(cash // price)
            if qty > 0:
                cost = qty * price
                cash -= cost
                shares += qty
                locked_until = i + T_PLUS_LOCK_DAYS
                trades.append({
                    "date": date_str,
                    "type": "BUY",
                    "price": price,
                    "shares": qty,
                    "value": cost,
                })

        elif sig == -1 and shares > 0 and i >= locked_until:
            proceeds = shares * price
            entry_trade = next((t for t in reversed(trades) if t["type"] == "BUY"), None)
            entry_price = entry_trade["price"] if entry_trade else price
            pnl = (price - entry_price) * shares
            cash += proceeds
            trades.append({
                "date": date_str,
                "type": "SELL",
                "price": price,
                "shares": shares,
                "value": proceeds,
                "pnl": pnl,
                "pnl_percent": (price / entry_price - 1) * 100 if entry_price else 0,
            })
            shares = 0

        nav = cash + shares * price
        equity_curve.append({"date": date_str, "nav": nav, "price": price})

        if prev_nav > 0:
            daily_returns.append((nav - prev_nav) / prev_nav)
        prev_nav = nav

    # Close any open position tại phiên cuối
    if shares > 0:
        last_price = float(closes[-1])
        proceeds = shares * last_price
        entry_trade = next((t for t in reversed(trades) if t["type"] == "BUY"), None)
        entry_price = entry_trade["price"] if entry_trade else last_price
        cash += proceeds
        trades.append({
            "date": dates[-1].strftime('%Y-%m-%d'),
            "type": "SELL",
            "price": last_price,
            "shares": shares,
            "value": proceeds,
            "pnl": (last_price - entry_price) * shares,
            "pnl_percent": (last_price / entry_price - 1) * 100 if entry_price else 0,
            "forced_close": True,
        })
        shares = 0
        nav = cash
        equity_curve[-1]["nav"] = nav

    sell_trades = [t for t in trades if t["type"] == "SELL"]
    winning = [t for t in sell_trades if t.get("pnl", 0) > 0]
    win_rate = (len(winning) / len(sell_trades) * 100) if sell_trades else 0.0

    final_nav = equity_curve[-1]["nav"] if equity_curve else initial_capital
    total_return_pct = (final_nav / initial_capital - 1) * 100

    nav_series = [pt["nav"] for pt in equity_curve]
    max_dd = _calc_max_drawdown(nav_series)
    sharpe = _calc_sharpe(daily_returns)

    # So với mua-giữ (buy-and-hold): mua tối đa cổ phiếu ở phiên đầu, giữ đến phiên cuối
    first_price = float(closes[0])
    bh_shares = int(initial_capital // first_price)
    bh_cash_left = initial_capital - bh_shares * first_price
    buy_hold_curve = [
        {"date": dates[i].strftime('%Y-%m-%d'), "nav": bh_cash_left + bh_shares * float(closes[i])}
        for i in range(len(df))
    ]
    bh_final = buy_hold_curve[-1]["nav"]
    bh_return_pct = (bh_final / initial_capital - 1) * 100
    bh_dd = _calc_max_drawdown([pt["nav"] for pt in buy_hold_curve])

    return {
        "symbol": symbol,
        "strategy": strategy,
        "period": period,
        "initial_capital": initial_capital,
        "metrics": {
            "final_nav": final_nav,
            "total_return_percent": total_return_pct,
            "max_drawdown_percent": max_dd,
            "win_rate_percent": win_rate,
            "num_trades": len(sell_trades),
            "sharpe": sharpe,
        },
        "buy_hold": {
            "final_nav": bh_final,
            "total_return_percent": bh_return_pct,
            "max_drawdown_percent": bh_dd,
        },
        "alpha_percent": total_return_pct - bh_return_pct,
        "equity_curve": equity_curve,
        "buy_hold_curve": buy_hold_curve,
        "trades": trades,
    }


def _run_single_safe(symbol: str, strategy: str, period: str, initial_capital: float):
    try:
        r = run_backtest(symbol, strategy, period, initial_capital)
        m = r["metrics"]
        bh = r["buy_hold"]
        return {
            "symbol": symbol,
            "strategy_return": m["total_return_percent"],
            "buy_hold_return": bh["total_return_percent"],
            "alpha": m["total_return_percent"] - bh["total_return_percent"],
            "max_drawdown": m["max_drawdown_percent"],
            "win_rate": m["win_rate_percent"],
            "num_trades": m["num_trades"],
            "sharpe": m["sharpe"],
            "final_nav": m["final_nav"],
            "ok": True,
        }
    except Exception as e:
        return {"symbol": symbol, "ok": False, "error": str(e)}


def run_batch_backtest(
    symbols: List[str],
    strategy: str = "ema_cross",
    period: str = "1y",
    initial_capital: float = 100_000_000.0,
) -> Dict[str, Any]:
    """
    Chạy backtest cho nhiều mã song song bằng ThreadPoolExecutor (yfinance/vnstock chủ yếu I/O bound).
    Trả về ranking, có thể sort phía client.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Strategy không hợp lệ. Chọn một trong: {sorted(STRATEGIES)}")

    results: List[Dict[str, Any]] = []
    # Giới hạn 8 worker để tránh ban từ vnstock/yfinance
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_run_single_safe, s, strategy, period, initial_capital): s for s in symbols}
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    successful = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    successful.sort(key=lambda r: r["strategy_return"], reverse=True)

    return {
        "strategy": strategy,
        "period": period,
        "initial_capital": initial_capital,
        "summary": {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "winners_count": sum(1 for r in successful if r["strategy_return"] > 0),
            "beat_buy_hold_count": sum(1 for r in successful if r["alpha"] > 0),
        },
        "results": successful,
        "failures": failed,
    }
