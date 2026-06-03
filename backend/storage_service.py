"""
Persistence layer cho portfolio giả lập.

Dual driver:
- Có DATABASE_URL bắt đầu bằng "postgres" → dùng Neon Postgres (production)
- Còn lại → SQLite local (dev)

Cùng schema, cùng API public. Code gọi `get_portfolio()`, `record_buy()`...
không cần biết backend nào.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")

DB_PATH = Path(os.getenv("STOCK_DB_PATH", Path(__file__).parent / "data.db"))
INITIAL_CAPITAL = 100_000_000.0
DEFAULT_PORTFOLIO_ID = 1
_init_lock = threading.Lock()
_initialized = False

# --- Postgres pool (chỉ khởi tạo khi cần) ---
_pg_pool = None
if USE_POSTGRES:
    try:
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row
        # Neon yêu cầu sslmode=require; thường đã trong URL
        _pg_pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=False,  # open lazily lần đầu dùng
        )
    except ImportError as e:
        print(f"[storage] psycopg chưa cài: {e}. Fallback SQLite.")
        USE_POSTGRES = False


@contextmanager
def _conn():
    """Yield connection (sqlite3.Connection hoặc psycopg.Connection)."""
    if USE_POSTGRES:
        if not _pg_pool.closed and not _pg_pool._opened:  # lazy open
            _pg_pool.open()
        with _pg_pool.connection() as con:
            yield con
    else:
        con = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            yield con
        finally:
            con.close()


def _execute(con, sql: str, params: tuple = ()):
    """Adapter exec — chuyển ? sang %s cho Postgres."""
    if USE_POSTGRES:
        sql = sql.replace("?", "%s")
        cur = con.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return con.execute(sql, params)


def _fetchone(con, sql: str, params: tuple = ()):
    cur = _execute(con, sql, params)
    if USE_POSTGRES:
        return cur.fetchone()
    return cur.fetchone()


def _fetchall(con, sql: str, params: tuple = ()):
    cur = _execute(con, sql, params)
    return cur.fetchall()


def _begin(con):
    """Khởi BEGIN với row lock cho safety."""
    if USE_POSTGRES:
        # psycopg auto-begins. Đặt isolation cao nhất cho atomic check-and-update.
        # SERIALIZABLE đảm bảo check shares + insert lot không bị race.
        con.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
    else:
        con.execute("BEGIN IMMEDIATE")


def _commit(con):
    if USE_POSTGRES:
        con.commit()
    else:
        con.execute("COMMIT")


def _rollback(con):
    if USE_POSTGRES:
        con.rollback()
    else:
        con.execute("ROLLBACK")


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY,
    cash REAL NOT NULL,
    initial_capital REAL NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS holding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    avg_price REAL NOT NULL,
    UNIQUE(portfolio_id, symbol)
);
CREATE TABLE IF NOT EXISTS lot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    holding_id INTEGER NOT NULL REFERENCES holding(id) ON DELETE CASCADE,
    shares INTEGER NOT NULL,
    buy_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS txn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    type TEXT NOT NULL,
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    executor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_portfolio_ts ON txn(portfolio_id, ts_ms DESC);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS portfolio (
    id BIGINT PRIMARY KEY,
    cash DOUBLE PRECISION NOT NULL,
    initial_capital DOUBLE PRECISION NOT NULL,
    created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS holding (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id BIGINT NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    avg_price DOUBLE PRECISION NOT NULL,
    UNIQUE(portfolio_id, symbol)
);
CREATE TABLE IF NOT EXISTS lot (
    id BIGSERIAL PRIMARY KEY,
    holding_id BIGINT NOT NULL REFERENCES holding(id) ON DELETE CASCADE,
    shares BIGINT NOT NULL,
    buy_at_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS txn (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id BIGINT NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    ts_ms BIGINT NOT NULL,
    symbol TEXT NOT NULL,
    type TEXT NOT NULL,
    shares BIGINT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    executor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_portfolio_ts ON txn(portfolio_id, ts_ms DESC);
"""


def _init_schema_once():
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        with _conn() as con:
            if USE_POSTGRES:
                # psycopg cần execute từng statement
                for stmt in SCHEMA_PG.split(";"):
                    s = stmt.strip()
                    if s:
                        con.execute(s)
                con.commit()
            else:
                con.executescript(SCHEMA_SQLITE)

            row = _fetchone(con, "SELECT id FROM portfolio WHERE id = ?", (DEFAULT_PORTFOLIO_ID,))
            if not row:
                _execute(con, "INSERT INTO portfolio(id, cash, initial_capital, created_at) VALUES (?, ?, ?, ?)",
                         (DEFAULT_PORTFOLIO_ID, INITIAL_CAPITAL, INITIAL_CAPITAL, int(time.time() * 1000)))
                if USE_POSTGRES:
                    con.commit()
        _initialized = True


def _row_get(row, key):
    """Compat: sqlite3.Row dùng [] index, psycopg dict_row dùng dict."""
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _holding_with_lots(con, holding_row) -> Dict[str, Any]:
    holding_id = _row_get(holding_row, "id")
    lots = _fetchall(con, "SELECT shares, buy_at_ms FROM lot WHERE holding_id = ? ORDER BY buy_at_ms ASC", (holding_id,))
    total = sum(_row_get(l, "shares") for l in lots)
    return {
        "symbol": _row_get(holding_row, "symbol"),
        "avgPrice": _row_get(holding_row, "avg_price"),
        "shares": total,
        "lots": [{"shares": _row_get(l, "shares"), "buyAt": _row_get(l, "buy_at_ms")} for l in lots],
    }


def get_portfolio() -> Dict[str, Any]:
    _init_schema_once()
    with _conn() as con:
        port = _fetchone(con, "SELECT id, cash, initial_capital, created_at FROM portfolio WHERE id = ?", (DEFAULT_PORTFOLIO_ID,))
        holdings_rows = _fetchall(con, "SELECT id, symbol, avg_price FROM holding WHERE portfolio_id = ? ORDER BY symbol", (DEFAULT_PORTFOLIO_ID,))
        return {
            "cash": _row_get(port, "cash"),
            "initial_capital": _row_get(port, "initial_capital"),
            "created_at": _row_get(port, "created_at"),
            "holdings": [_holding_with_lots(con, h) for h in holdings_rows],
        }


def get_transactions(limit: int = 200) -> List[Dict[str, Any]]:
    _init_schema_once()
    with _conn() as con:
        rows = _fetchall(con, "SELECT ts_ms, symbol, type, shares, price, executor FROM txn WHERE portfolio_id = ? ORDER BY ts_ms DESC LIMIT ?",
                         (DEFAULT_PORTFOLIO_ID, limit))
    return [{
        "timestamp": _row_get(r, "ts_ms"),
        "symbol": _row_get(r, "symbol"),
        "type": _row_get(r, "type"),
        "shares": _row_get(r, "shares"),
        "price": _row_get(r, "price"),
        "executor": _row_get(r, "executor"),
    } for r in rows]


def record_buy(symbol: str, shares: int, price: float, executor: str = "USER") -> Dict[str, Any]:
    _init_schema_once()
    cost = shares * price
    now_ms = int(time.time() * 1000)
    with _conn() as con:
        port = _fetchone(con, "SELECT cash FROM portfolio WHERE id = ?", (DEFAULT_PORTFOLIO_ID,))
        if not port:
            return {"ok": False, "error": "Portfolio không tồn tại."}
        if cost > _row_get(port, "cash"):
            return {"ok": False, "error": "Số dư tiền mặt không đủ."}

        _begin(con)
        try:
            _execute(con, "UPDATE portfolio SET cash = cash - ? WHERE id = ?", (cost, DEFAULT_PORTFOLIO_ID))
            holding = _fetchone(con, "SELECT id, avg_price FROM holding WHERE portfolio_id = ? AND symbol = ?",
                                (DEFAULT_PORTFOLIO_ID, symbol))
            if holding:
                lots = _fetchall(con, "SELECT shares FROM lot WHERE holding_id = ?", (_row_get(holding, "id"),))
                total_shares = sum(_row_get(l, "shares") for l in lots)
                new_shares = total_shares + shares
                new_avg = (total_shares * _row_get(holding, "avg_price") + cost) / new_shares
                _execute(con, "UPDATE holding SET avg_price = ? WHERE id = ?", (round(new_avg, 2), _row_get(holding, "id")))
                holding_id = _row_get(holding, "id")
            else:
                if USE_POSTGRES:
                    cur = _execute(con, "INSERT INTO holding(portfolio_id, symbol, avg_price) VALUES (?, ?, ?) RETURNING id",
                                   (DEFAULT_PORTFOLIO_ID, symbol, price))
                    holding_id = cur.fetchone()["id"]
                else:
                    cur = _execute(con, "INSERT INTO holding(portfolio_id, symbol, avg_price) VALUES (?, ?, ?)",
                                   (DEFAULT_PORTFOLIO_ID, symbol, price))
                    holding_id = cur.lastrowid

            _execute(con, "INSERT INTO lot(holding_id, shares, buy_at_ms) VALUES (?, ?, ?)",
                     (holding_id, shares, now_ms))
            _execute(con, "INSERT INTO txn(portfolio_id, ts_ms, symbol, type, shares, price, executor) VALUES (?, ?, ?, 'BUY', ?, ?, ?)",
                     (DEFAULT_PORTFOLIO_ID, now_ms, symbol, shares, price, executor))
            _commit(con)
        except Exception:
            _rollback(con)
            raise
    return {"ok": True, "portfolio": get_portfolio()}


def record_sell(symbol: str, shares: int, price: float, executor: str = "USER",
                t_plus_lock_ms: int = 2 * 24 * 3600 * 1000) -> Dict[str, Any]:
    _init_schema_once()
    now_ms = int(time.time() * 1000)
    proceeds = shares * price

    with _conn() as con:
        holding = _fetchone(con, "SELECT id FROM holding WHERE portfolio_id = ? AND symbol = ?",
                            (DEFAULT_PORTFOLIO_ID, symbol))
        if not holding:
            return {"ok": False, "error": "Không nắm giữ cổ phiếu này."}

        holding_id = _row_get(holding, "id")
        lots = _fetchall(con, "SELECT id, shares, buy_at_ms FROM lot WHERE holding_id = ? ORDER BY buy_at_ms ASC", (holding_id,))
        available = sum(_row_get(l, "shares") for l in lots if (now_ms - _row_get(l, "buy_at_ms")) >= t_plus_lock_ms)
        if available < shares:
            locked = sum(_row_get(l, "shares") for l in lots) - available
            return {"ok": False, "error": f"Chỉ có {available} CP khả dụng ({locked} đang khóa T+)."}

        _begin(con)
        try:
            remaining = shares
            for l in lots:
                if remaining <= 0:
                    break
                if (now_ms - _row_get(l, "buy_at_ms")) < t_plus_lock_ms:
                    continue
                lot_shares = _row_get(l, "shares")
                if lot_shares <= remaining:
                    _execute(con, "DELETE FROM lot WHERE id = ?", (_row_get(l, "id"),))
                    remaining -= lot_shares
                else:
                    _execute(con, "UPDATE lot SET shares = shares - ? WHERE id = ?", (remaining, _row_get(l, "id")))
                    remaining = 0

            remain_row = _fetchone(con, "SELECT COALESCE(SUM(shares),0) AS s FROM lot WHERE holding_id = ?", (holding_id,))
            if _row_get(remain_row, "s") == 0:
                _execute(con, "DELETE FROM holding WHERE id = ?", (holding_id,))

            _execute(con, "UPDATE portfolio SET cash = cash + ? WHERE id = ?", (proceeds, DEFAULT_PORTFOLIO_ID))
            _execute(con, "INSERT INTO txn(portfolio_id, ts_ms, symbol, type, shares, price, executor) VALUES (?, ?, ?, 'SELL', ?, ?, ?)",
                     (DEFAULT_PORTFOLIO_ID, now_ms, symbol, shares, price, executor))
            _commit(con)
        except Exception:
            _rollback(con)
            raise

    return {"ok": True, "portfolio": get_portfolio()}


def reset_portfolio() -> Dict[str, Any]:
    _init_schema_once()
    with _conn() as con:
        _begin(con)
        try:
            if USE_POSTGRES:
                _execute(con, "DELETE FROM lot WHERE holding_id IN (SELECT id FROM holding WHERE portfolio_id = ?)", (DEFAULT_PORTFOLIO_ID,))
            else:
                _execute(con, "DELETE FROM lot WHERE holding_id IN (SELECT id FROM holding WHERE portfolio_id = ?)", (DEFAULT_PORTFOLIO_ID,))
            _execute(con, "DELETE FROM holding WHERE portfolio_id = ?", (DEFAULT_PORTFOLIO_ID,))
            _execute(con, "DELETE FROM txn WHERE portfolio_id = ?", (DEFAULT_PORTFOLIO_ID,))
            _execute(con, "UPDATE portfolio SET cash = ?, created_at = ? WHERE id = ?",
                     (INITIAL_CAPITAL, int(time.time() * 1000), DEFAULT_PORTFOLIO_ID))
            _commit(con)
        except Exception:
            _rollback(con)
            raise
    return get_portfolio()
