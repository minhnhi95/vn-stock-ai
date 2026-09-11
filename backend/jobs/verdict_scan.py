"""
Tự quét kết luận "Có thể cân nhắc mua / Chờ thêm / Không nên mua" cho cả rổ, ghi vào DB.

Vì sao là job chạy nền: mỗi mã tốn khoảng 3 request vnstock (giá 2 năm + chỉ số cơ
bản), trần free tier là 20 request/phút. Quét ~110 mã mất khoảng 20-25 phút — không
thể để người dùng bấm rồi ngồi chờ. Chạy sau giờ đóng cửa để kết luận dùng giá đóng
cửa của chính phiên đó.

Thứ tự quét: mã đang giữ → mã đang đặt cảnh báo → VN100. Job bị ngắt giữa chừng hay
dính hạn mức thì những mã người dùng quan tâm nhất vẫn đã có kết quả.

Kết luận từng mã lấy từ verdict_engine — cùng quy tắc với thẻ "Kết luận" trên giao
diện, nên danh sách quét và thẻ không bao giờ nói hai điều khác nhau.

Chạy (từ thư mục backend):
    python -m jobs.verdict_scan                    # đủ rổ, ghi vào DB
    python -m jobs.verdict_scan --dry-run          # đủ rổ, chỉ in
    python -m jobs.verdict_scan --symbols FPT VNM  # vài mã, chỉ in
    python -m jobs.verdict_scan --limit 5          # 5 mã đầu, chỉ in

Lượt quét một phần (--symbols / --limit) không bao giờ ghi: nó sẽ đè lên danh sách
cả rổ của ngày hôm đó bằng vài mã.
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
from symbol_utils import is_vn_symbol  # noqa: E402
from verdict_engine import DISCLAIMER, LABELS, RULE_TEXT  # noqa: E402

# ~3 request mỗi mã (giá + 1-2 lần lấy chỉ số cơ bản) trên trần 20 request/phút.
THROTTLE_SECONDS = 9.0

# Nghỉ trước lượt thử lại, đủ một phút để hạn mức vnstock hồi lại.
RETRY_PAUSE_SECONDS = 65.0

# Quét được ít hơn tỷ lệ này thì coi cả lượt là hỏng (mất mạng, vnstock đổi API) và
# không ghi — thà giữ lượt quét phiên trước còn hơn hiện một danh sách thiếu quá nửa.
MIN_SUCCESS_RATIO = 0.5

# Job treo (mạng chập chờn làm vnstock chờ mãi) thì tự thoát, để lần chạy sau của
# Task Scheduler không bị chặn bởi một tiến trình cũ.
WATCHDOG_SECONDS = 55 * 60

# Có thể mua lên đầu, rồi chờ thêm, rồi không nên mua. Trong cùng một kết luận, mã mà
# quy tắc từng đúng hơn chọn bừa lên trước — đó là kết luận đáng tin hơn.
_VERDICT_ORDER = {"buy_consider": 0, "wait": 1, "avoid": 2}
_EDGE_ORDER = {"better": 0, "same": 1, None: 2, "worse": 3}


def _dedupe(symbols: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = (raw or "").strip().upper()
        if symbol and symbol not in seen and is_vn_symbol(symbol):
            seen.add(symbol)
            out.append(symbol)
    return out


def pick_universe(explicit: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Mã cần quét, theo thứ tự ưu tiên, kèm danh sách mã đang giữ (để giao diện đánh
    dấu) và tập VN100 (bộ lọc an toàn cần nó, lấy một lần cho cả lượt).
    """
    held: List[str] = []
    try:
        from real_portfolio_service import get_real_portfolio

        held = [p["symbol"] for p in get_real_portfolio(include_prices=False).get("positions", [])]
    except Exception as e:
        print(f"[scan] khong doc duoc danh muc that: {str(e)[:120]}")

    try:
        from sector_service import get_vn100_symbols

        core = list(get_vn100_symbols())
    except Exception:
        from market_universe import vn100_fallback

        core = list(vn100_fallback())

    if explicit:
        symbols = _dedupe(explicit)
    else:
        watched: List[str] = []
        try:
            watched = [r["symbol"] for r in storage.list_alert_rules() if r.get("active")]
        except Exception as e:
            print(f"[scan] khong doc duoc canh bao: {str(e)[:120]}")
        symbols = _dedupe(held + watched + core)

    return {"symbols": symbols, "held": _dedupe(held), "vn100": set(_dedupe(core))}


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    """Bản rút gọn một kết luận để lưu cả rổ. Chi tiết từng tiêu chí: GET /api/verdict."""
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
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Kết luận từng mã. Mã lỗi ghi vào errors, không làm hỏng cả lượt."""
    if fetch is None:
        from verdict_engine import verdict_for

        def fetch(symbol: str) -> Dict[str, Any]:
            return verdict_for(symbol, vn100=vn100)

    results: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    for i, symbol in enumerate(symbols):
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
            time.sleep(throttle)
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
) -> Dict[str, Any]:
    """Gói kết quả để lưu: sắp xếp, đếm, và tìm mã đổi kết luận so với lượt trước."""
    held_set = set(held)
    rows = [{**row, "held": row["symbol"] in held_set} for row in results.values()]
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
    parser = argparse.ArgumentParser(description="Quet ket luan ca ro")
    parser.add_argument("--symbols", nargs="+", help="Chi quet cac ma nay (chi in, khong ghi)")
    parser.add_argument("--limit", type=int, default=0, help="Chi quet N ma dau (chi in, khong ghi)")
    parser.add_argument("--dry-run", action="store_true", help="Quet du ro nhung khong ghi")
    parser.add_argument("--throttle", type=float, default=THROTTLE_SECONDS)
    args = parser.parse_args(argv)

    universe = pick_universe(args.symbols)
    symbols = universe["symbols"][: args.limit] if args.limit else universe["symbols"]
    partial = bool(args.symbols or args.limit)
    print(
        f"{len(symbols)} ma se quet ({len(universe['held'])} ma dang giu), "
        f"~{len(symbols) * (args.throttle + 3) / 60:.0f} phut"
    )

    results, errors = scan(symbols, throttle=args.throttle, vn100=universe["vn100"])

    # Lỗi hoặc thiếu chỉ số cơ bản thường là do dính hạn mức — thử lại một lần sau
    # khi hạn mức hồi. Thiếu chỉ số cơ bản thì kết luận bị kéo về "Chờ thêm" dù có
    # thể không phải, nên đáng tốn thêm một lượt.
    retry = [s for s in symbols if s in errors or (results.get(s) or {}).get("data_gaps")]
    if retry:
        print(f"Thu lai {len(retry)} ma sau {RETRY_PAUSE_SECONDS:.0f}s...")
        time.sleep(RETRY_PAUSE_SECONDS)
        merge_retry(results, errors, *scan(retry, throttle=args.throttle, vn100=universe["vn100"]))

    today = _today()
    previous = storage.get_previous_verdict_scan(today)
    payload = build_payload(
        results, errors, universe["held"], today, now_vn().strftime("%Y-%m-%d %H:%M"), previous
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
