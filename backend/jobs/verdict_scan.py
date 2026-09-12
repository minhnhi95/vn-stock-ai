"""
Tìm mã đáng mua trên sàn HOSE: chấm kết luận "Có thể cân nhắc mua / Chờ thêm / Không
nên mua" rồi ghi vào DB.

Hai vòng, vì vnstock free tier chỉ cho 20 request/phút:

1. Lọc rẻ. Lấy danh sách cổ phiếu đang niêm yết trên sàn cần tìm và bảng giá phiên
   gần nhất. Bảng giá nhận 80 mã mỗi request nên cả sàn chỉ tốn vài request (~1 phút).
   Loại mã không khớp lệnh, giá dưới ngưỡng, hoặc giao dịch quá ít: những mã này đằng
   nào cũng trượt bộ lọc an toàn, tức là "Không nên mua".
2. Chấm kết luận. Chạy verdict_engine đầy đủ cho mã qua vòng lọc, cộng mã đang giữ,
   mã đang đặt cảnh báo và rổ VN100 — nhóm này luôn được chấm, không qua vòng lọc.

Số mã bị loại ở vòng 1 và lý do được lưu kèm, để người dùng biết lượt quét phủ tới đâu.

Kết luận từng mã lấy từ verdict_engine — cùng quy tắc với thẻ "Kết luận" trên giao
diện, nên danh sách và thẻ không bao giờ nói hai điều khác nhau.

Chạy (từ thư mục backend):
    python -m jobs.verdict_scan                    # sàn HOSE, ghi vào DB
    python -m jobs.verdict_scan --exchanges HOSE HNX UPCoM   # thêm sàn khác
    python -m jobs.verdict_scan --universe vn100   # chỉ VN100 + mã quan tâm (~15 phút)
    python -m jobs.verdict_scan --dry-run          # quét nhưng không ghi
    python -m jobs.verdict_scan --symbols FPT VNM  # vài mã, chỉ in
    python -m jobs.verdict_scan --limit 5          # 5 mã đầu, chỉ in

Lượt quét một phần (--symbols / --limit) không bao giờ ghi: nó sẽ đè lên danh sách
đầy đủ của ngày hôm đó bằng vài mã.
"""
from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage_service as storage  # noqa: E402
from market_service import now_vn  # noqa: E402
from safety_screen import MIN_DAILY_VALUE_VND, MIN_PRICE_VND  # noqa: E402
from symbol_utils import is_vn_symbol  # noqa: E402
from verdict_engine import DISCLAIMER, LABELS, RULE_TEXT  # noqa: E402

# Khoảng cách tối thiểu giữa hai mã: ~3 request mỗi mã (giá + 1-2 lần lấy chỉ số cơ
# bản) trên trần 20 request/phút. Tính từ lúc bắt đầu mã trước, nên thời gian chính
# request đó chạy không cộng thêm vào.
THROTTLE_SECONDS = 9.0

# Nghỉ trước lượt thử lại, đủ một phút để hạn mức vnstock hồi lại.
RETRY_PAUSE_SECONDS = 65.0

# Vòng lọc lỏng hơn bộ lọc an toàn (40% ngưỡng thanh khoản) vì chỉ nhìn MỘT phiên —
# có thể là phiên trầm. Bộ lọc an toàn đầy đủ ở vòng 2 dùng trung bình 20 phiên. Lỏng
# hơn để không loại nhầm mã thật ra đủ thanh khoản.
PREFILTER_MIN_VALUE = MIN_DAILY_VALUE_VND * 0.4

# Bảng giá bắt đầu trả thiếu khi danh sách quá dài, nên chia lô.
BOARD_BATCH = 80
BOARD_PAUSE_SECONDS = 3.0

# Quét được ít hơn tỷ lệ này thì coi cả lượt là hỏng (mất mạng, vnstock đổi API) và
# không ghi — thà giữ lượt quét phiên trước còn hơn hiện một danh sách thiếu quá nửa.
MIN_SUCCESS_RATIO = 0.5

# Job treo (mạng chập chờn làm vnstock chờ mãi) thì tự thoát, để lần chạy sau của
# Task Scheduler không bị chặn bởi một tiến trình cũ.
WATCHDOG_SECONDS = 85 * 60

# Có thể mua lên đầu, rồi chờ thêm, rồi không nên mua. Trong cùng một kết luận, mã mà
# quy tắc từng đúng hơn chọn bừa lên trước — đó là kết luận đáng tin hơn.
_VERDICT_ORDER = {"buy_consider": 0, "wait": 1, "avoid": 2}
_EDGE_ORDER = {"better": 0, "same": 1, None: 2, "worse": 3}

_EXCHANGE_NAMES = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCoM"}

# Mặc định chỉ tìm trên HOSE: sàn lớn nhất, chuẩn niêm yết và công bố thông tin chặt
# nhất. Mã đang giữ hoặc đang đặt cảnh báo vẫn luôn được chấm dù nằm ở sàn nào.
DEFAULT_EXCHANGES = ("HOSE",)


def _dedupe(symbols: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = (raw or "").strip().upper()
        if symbol and symbol not in seen and is_vn_symbol(symbol):
            seen.add(symbol)
            out.append(symbol)
    return out


def _industry_map() -> Dict[str, str]:
    """symbol -> ngành ICB cấp 2, cùng tên ngành với bảng trung vị (1 request, cache 24h)."""
    try:
        from jobs.sector_benchmarks import _sector_map

        return _sector_map()
    except (SystemExit, Exception) as e:
        print(f"[scan] khong lay duoc ban do nganh: {str(e)[:120]}")
        return {}


def _listed_stocks() -> Dict[str, Optional[str]]:
    """
    symbol -> sàn của mọi cổ phiếu đang niêm yết. Bỏ chứng quyền, ETF, trái phiếu, hợp
    đồng tương lai và mã đã huỷ niêm yết.

    Nguồn không trả được thì dùng danh sách mã theo ngành ICB (không có tên sàn); mã đã
    huỷ niêm yết trong đó tự rơi ở vòng bảng giá vì không có số liệu.
    """
    try:
        from vnstock import Listing

        df = Listing(source="VCI").symbols_by_exchange()
        out: Dict[str, Optional[str]] = {}
        for _, row in df.iterrows():
            symbol = str(row.get("symbol") or "").strip().upper()
            exchange = str(row.get("exchange") or "").strip().upper()
            if (
                str(row.get("type") or "").strip().upper() == "STOCK"
                and exchange in _EXCHANGE_NAMES
                and is_vn_symbol(symbol)
            ):
                out[symbol] = _EXCHANGE_NAMES[exchange]
        if out:
            return out
    except (SystemExit, Exception) as e:
        print(f"[scan] khong lay duoc danh sach niem yet: {str(e)[:120]}")
    return {symbol: None for symbol in _industry_map()}


def _price_board(symbols: List[str], retries: int = 3) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
    """
    Giá và giá trị khớp lệnh phiên gần nhất cho nhiều mã, 80 mã mỗi request.

    Trả kèm danh sách mã thuộc lô lỗi sau khi đã thử lại. Phải tách "không lấy được"
    khỏi "không có giao dịch": fetch_price_board nuốt lỗi hạn mức và trả rỗng, và coi
    rỗng là "không giao dịch" sẽ loại nhầm cả lô 80 mã.
    """
    try:
        from foreign_service import fetch_price_board
    except Exception:
        return {}, list(symbols)

    board: Dict[str, Dict[str, float]] = {}
    failed: List[str] = []
    for i in range(0, len(symbols), BOARD_BATCH):
        batch = symbols[i : i + BOARD_BATCH]
        got: Dict[str, Any] = {}
        for attempt in range(retries):
            # Nghỉ trước MỌI lần gọi, lần thử lại nghỉ lâu dần.
            time.sleep(BOARD_PAUSE_SECONDS * (attempt + 1))
            try:
                got = fetch_price_board(batch) or {}
            except (SystemExit, Exception):
                got = {}
            if got:
                break
        if not got:
            failed.extend(batch)
            continue
        for symbol, row in got.items():
            price = float(row.get("price") or 0)
            board[symbol] = {"price": price, "value": price * float(row.get("total_volume") or 0)}
    return board, failed


def prefilter(
    symbols: List[str],
    board: Dict[str, Dict[str, float]],
    failed: Iterable[str],
    min_value: float = PREFILTER_MIN_VALUE,
    min_price: float = MIN_PRICE_VND,
) -> Tuple[List[str], Dict[str, int]]:
    """
    Vòng lọc rẻ. Trả mã qua vòng (giao dịch nhiều nhất trước) và số mã bị loại theo lý do.
    """
    failed_set = set(failed)
    stats = {"board_failed": 0, "no_data": 0, "no_trade": 0, "penny": 0, "illiquid": 0}
    passed: List[str] = []
    for symbol in symbols:
        row = board.get(symbol)
        if row is None:
            stats["board_failed" if symbol in failed_set else "no_data"] += 1
        elif row["value"] <= 0:
            stats["no_trade"] += 1
        elif row["price"] < min_price:
            stats["penny"] += 1
        elif row["value"] < min_value:
            stats["illiquid"] += 1
        else:
            passed.append(symbol)
    passed.sort(key=lambda s: (-board[s]["value"], s))
    return passed, stats


def pick_universe(
    explicit: Optional[List[str]] = None,
    market: bool = True,
    exchanges: Iterable[str] = DEFAULT_EXCHANGES,
) -> Dict[str, Any]:
    """
    Mã cần chấm, theo thứ tự ưu tiên: mã đang giữ → mã đặt cảnh báo → VN100 → mã khác
    qua vòng lọc (giao dịch nhiều trước). Job bị ngắt giữa chừng thì mã quan trọng
    nhất đã có kết quả.

    Trả kèm: mã đang giữ (giao diện đánh dấu), tập VN100 và bản đồ ngành (bộ lọc an
    toàn và phép so trung vị cần, lấy một lần cho cả lượt), thông tin từng mã (sàn,
    ngành, giá trị giao dịch) và độ phủ của vòng lọc.
    """
    held: List[str] = []
    try:
        from real_portfolio_service import get_real_portfolio

        held = [p["symbol"] for p in get_real_portfolio(include_prices=False).get("positions", [])]
    except Exception as e:
        print(f"[scan] khong doc duoc danh muc that: {str(e)[:120]}")

    try:
        from sector_service import get_vn100_symbols

        core = _dedupe(get_vn100_symbols())
    except Exception:
        from market_universe import vn100_fallback

        core = _dedupe(vn100_fallback())

    industry = _industry_map()
    meta: Dict[str, Dict[str, Any]] = {}
    coverage: Optional[Dict[str, Any]] = None

    if explicit:
        symbols = _dedupe(explicit)
    else:
        watched: List[str] = []
        try:
            watched = [r["symbol"] for r in storage.list_alert_rules() if r.get("active")]
        except Exception as e:
            print(f"[scan] khong doc duoc canh bao: {str(e)[:120]}")
        priority = _dedupe(held + watched + core)
        symbols = list(priority)

        if market:
            wanted = tuple(exchanges)
            listed = _listed_stocks()
            # Mã ngoài sàn cần tìm chỉ được chấm nếu đang giữ hoặc đang đặt cảnh báo.
            in_scope = [s for s, exchange in listed.items() if exchange in wanted]
            priority_set = set(priority)
            everything = sorted(set(in_scope) | priority_set)
            print(f"Loc thanh khoan {len(everything)} ma tren {', '.join(wanted)}...")
            board, failed = _price_board(everything)
            rest = [s for s in sorted(in_scope) if s not in priority_set]
            passed, stats = prefilter(rest, board, failed)
            symbols += passed
            coverage = {
                "mode": "market",
                "exchanges": list(wanted),
                "listed": len(everything),
                "priority": len(priority),
                "prefilter_passed": len(passed),
                "excluded": sum(stats.values()),
                **stats,
                "min_value": PREFILTER_MIN_VALUE,
                "min_price": MIN_PRICE_VND,
                "board_ok": bool(board),
            }
            for symbol in everything:
                meta[symbol] = {
                    "exchange": listed.get(symbol),
                    "value": (board.get(symbol) or {}).get("value"),
                }
            print(
                f"  qua vong loc {len(passed)} ma; loai {coverage['excluded']} ma "
                f"(khong khop {stats['no_trade']}, gia thap {stats['penny']}, "
                f"it giao dich {stats['illiquid']}, khong co bang gia {stats['no_data']}, "
                f"lo loi {stats['board_failed']})"
            )
        else:
            coverage = {"mode": "vn100", "priority": len(priority)}

    core_set = set(core)
    meta = {
        symbol: {
            **meta.get(symbol, {}),
            "in_vn100": symbol in core_set,
            "industry": industry.get(symbol),
        }
        for symbol in symbols
    }
    return {
        "symbols": symbols,
        "held": _dedupe(held),
        "vn100": core_set,
        "sector_of": industry,
        "meta": meta,
        "coverage": coverage,
    }


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    """Bản rút gọn một kết luận để lưu cả danh sách. Chi tiết từng tiêu chí: GET /api/verdict."""
    history = result.get("history") or {}
    return {
        "symbol": result["symbol"],
        "verdict": result["verdict"],
        "label": result["label"],
        "headline": result["headline"],
        "sector": result.get("sector"),
        "price": result.get("price"),
        "failed": [c.get("label") for c in result.get("checks") or [] if c.get("status") == "fail"],
        "data_gaps": result.get("data_gaps") or [],
        "edge": history.get("edge"),
        "hit_ratio": history.get("hit_ratio"),
        "baseline_hit_ratio": history.get("baseline_hit_ratio"),
        "samples": history.get("samples"),
    }


def scan(
    symbols: List[str],
    throttle: float = THROTTLE_SECONDS,
    vn100: Optional[set] = None,
    fetch: Optional[Callable[[str], Dict[str, Any]]] = None,
    sector_of: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Kết luận từng mã. Mã lỗi ghi vào errors, không làm hỏng cả lượt."""
    if fetch is None:
        from verdict_engine import verdict_for

        def fetch(symbol: str) -> Dict[str, Any]:
            return verdict_for(symbol, vn100=vn100, sector_of=sector_of)

    results: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    for i, symbol in enumerate(symbols):
        started = time.monotonic()
        tag = f"  [{i + 1}/{len(symbols)}] {symbol}"
        try:
            results[symbol] = summarize(fetch(symbol))
            gap = " (thieu chi so co ban)" if results[symbol]["data_gaps"] else ""
            print(f"{tag}: {results[symbol]['label']}{gap}")
        # vnstock từng gọi sys.exit khi dính hạn mức — một mã như vậy không được
        # giết cả lượt quét.
        except (SystemExit, Exception) as e:
            errors[symbol] = str(e)[:160] or type(e).__name__
            print(f"{tag}: LOI - {errors[symbol][:80]}")
        if throttle and i < len(symbols) - 1:
            wait = throttle - (time.monotonic() - started)
            if wait > 0:
                time.sleep(wait)
    return results, errors


def merge_retry(
    results: Dict[str, Dict[str, Any]],
    errors: Dict[str, str],
    retry_results: Dict[str, Dict[str, Any]],
    retry_errors: Dict[str, str],
) -> None:
    """Gộp lượt thử lại: kết quả mới thay kết quả cũ; lỗi mới chỉ ghi khi chưa có kết quả nào."""
    for symbol, row in retry_results.items():
        results[symbol] = row
        errors.pop(symbol, None)
    for symbol, message in retry_errors.items():
        if symbol not in results:
            errors[symbol] = message


def is_healthy(ok_count: int, total: int) -> bool:
    return total > 0 and ok_count >= total * MIN_SUCCESS_RATIO


def build_payload(
    results: Dict[str, Dict[str, Any]],
    errors: Dict[str, str],
    held: List[str],
    scan_date: str,
    generated_at: str,
    previous: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Dict[str, Any]]] = None,
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Gói kết quả để lưu: gắn thông tin từng mã, sắp xếp, đếm, và tìm mã đổi kết luận."""
    held_set = set(held)
    meta = meta or {}
    rows = [
        {**row, **meta.get(row["symbol"], {}), "held": row["symbol"] in held_set}
        for row in results.values()
    ]
    rows.sort(
        key=lambda r: (
            _VERDICT_ORDER.get(r["verdict"], 9),
            _EDGE_ORDER.get(r.get("edge"), 2),
            r["symbol"],
        )
    )

    before = {r.get("symbol"): r for r in (previous or {}).get("results") or []}
    changes = []
    for row in rows:
        old = before.get(row["symbol"])
        if old and old.get("verdict") != row["verdict"]:
            changes.append(
                {
                    "symbol": row["symbol"],
                    "from": old.get("verdict"),
                    "to": row["verdict"],
                    "from_label": LABELS.get(old.get("verdict"), old.get("label")),
                    "to_label": row["label"],
                    "held": row["held"],
                }
            )
    # Mã đang giữ lên đầu: đổi kết luận trên thứ đang cầm tiền quan trọng hơn.
    changes.sort(key=lambda c: (not c["held"], _VERDICT_ORDER.get(c["to"], 9), c["symbol"]))

    return {
        "date": scan_date,
        "generated_at": generated_at,
        "universe": (coverage or {}).get("mode"),
        "coverage": coverage,
        "previous_date": (previous or {}).get("scan_date") or (previous or {}).get("date"),
        "counts": {key: sum(1 for r in rows if r["verdict"] == key) for key in LABELS},
        "results": rows,
        "errors": [{"symbol": s, "error": e} for s, e in errors.items()],
        "changes": changes,
        "held": list(held),
        "rule": RULE_TEXT,
        "disclaimer": DISCLAIMER,
    }


def _today() -> str:
    return now_vn().strftime("%Y-%m-%d")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Tim ma dang mua tren san niem yet")
    parser.add_argument(
        "--universe",
        choices=("market", "vn100"),
        default="market",
        help="market = loc ca san roi cham (mac dinh); vn100 = chi VN100 + ma quan tam",
    )
    parser.add_argument(
        "--exchanges",
        nargs="+",
        choices=("HOSE", "HNX", "UPCoM"),
        default=list(DEFAULT_EXCHANGES),
        help="San can tim (mac dinh HOSE). Ma dang giu / dat canh bao luon duoc cham.",
    )
    parser.add_argument("--symbols", nargs="+", help="Chi quet cac ma nay (chi in, khong ghi)")
    parser.add_argument("--limit", type=int, default=0, help="Chi quet N ma dau (chi in, khong ghi)")
    parser.add_argument("--dry-run", action="store_true", help="Quet nhung khong ghi")
    parser.add_argument("--throttle", type=float, default=THROTTLE_SECONDS)
    args = parser.parse_args(argv)

    universe = pick_universe(
        args.symbols, market=args.universe == "market", exchanges=tuple(args.exchanges)
    )
    symbols = universe["symbols"][: args.limit] if args.limit else universe["symbols"]
    partial = bool(args.symbols or args.limit)
    print(
        f"{len(symbols)} ma se cham ({len(universe['held'])} ma dang giu), "
        f"~{len(symbols) * args.throttle / 60:.0f} phut"
    )

    def run(batch: List[str]):
        return scan(
            batch,
            throttle=args.throttle,
            vn100=universe["vn100"],
            sector_of=universe.get("sector_of"),
        )

    results, errors = run(symbols)

    # Lỗi hoặc thiếu chỉ số cơ bản thường là do dính hạn mức — thử lại một lần sau
    # khi hạn mức hồi. Thiếu chỉ số cơ bản thì kết luận bị kéo về "Chờ thêm" dù có
    # thể không phải, nên đáng tốn thêm một lượt.
    retry = [s for s in symbols if s in errors or (results.get(s) or {}).get("data_gaps")]
    if retry:
        print(f"Thu lai {len(retry)} ma sau {RETRY_PAUSE_SECONDS:.0f}s...")
        time.sleep(RETRY_PAUSE_SECONDS)
        merge_retry(results, errors, *run(retry))

    today = _today()
    previous = storage.get_previous_verdict_scan(today)
    payload = build_payload(
        results,
        errors,
        universe["held"],
        today,
        now_vn().strftime("%Y-%m-%d %H:%M"),
        previous,
        meta=universe.get("meta"),
        coverage=universe.get("coverage"),
    )
    counts = payload["counts"]
    print(
        f"\nKet qua: {counts['buy_consider']} co the can nhac mua, {counts['wait']} cho them, "
        f"{counts['avoid']} khong nen mua, {len(errors)} loi."
    )
    for change in payload["changes"]:
        print(f"  Doi ket luan: {change['symbol']} {change['from']} -> {change['to']}")

    if not is_healthy(len(results), len(symbols)):
        print(f"Chi quet duoc {len(results)}/{len(symbols)} ma -> KHONG ghi, giu luot quet cu.")
        return 1
    if partial or args.dry_run:
        print("Quet thu -> khong ghi vao DB.")
        return 0
    storage.save_verdict_scan(today, payload)
    print(f"Da ghi luot quet ngay {today}.")
    return 0


if __name__ == "__main__":
    from vnstock_safe import force_utf8_console

    force_utf8_console()
    faulthandler.dump_traceback_later(WATCHDOG_SECONDS, exit=True)
    raise SystemExit(main())
