"""
Tính trung vị chỉ số cơ bản theo ngành ICB, ghi ra data/sector_benchmarks.json.

Vì sao là job chạy nền chứ không tính lúc người dùng bấm: muốn biết P/E trung
bình ngành Công nghệ, phải lấy chỉ số của toàn bộ mã trong ngành đó. vnstock free
tier chỉ cho 20 request/phút, nên một lần quét VN100 mất vài phút — không thể để
người dùng ngồi đợi. Chỉ số cơ bản chỉ đổi mỗi quý, chạy lại mỗi tuần là thừa đủ.

Vì sao ghi ra file JSON chứ không vào DB: đây là dữ liệu tham chiếu chỉ-đọc, đi
kèm mã nguồn. Deploy lên đâu cũng có sẵn, không cần migration, không cần DB ghi
được. DB để dành cho dữ liệu của người dùng.

Dùng TRUNG VỊ chứ không phải trung bình: một mã có P/E 400 vì lợi nhuận sắp về 0
sẽ kéo lệch trung bình cả ngành, còn trung vị thì không nhúc nhích.

Chạy:
    python -m jobs.sector_benchmarks                  # đủ 19 ngành, ~20 phút
    python -m jobs.sector_benchmarks --universe vn100 # chỉ rổ VN100, ~8 phút
    python -m jobs.sector_benchmarks --dry-run        # in ra, không ghi file
    python -m jobs.sector_benchmarks --limit 20       # quét thử ít mã
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_service import fetch_fundamentals, now_vn  # noqa: E402
from sector_service import get_industries, get_vn100_symbols  # noqa: E402
from symbol_utils import is_vn_symbol  # noqa: E402
from vnstock_safe import force_utf8_console  # noqa: E402

# Chỉ số có ý nghĩa khi so ngang trong ngành. EPS/BVPS/beta cố ý không có mặt:
# EPS và BVPS phụ thuộc số cổ phiếu lưu hành nên không cùng thang giữa hai doanh
# nghiệp, còn beta là chỉ số thị trường chứ không phải chỉ số ngành.
BENCHMARK_METRICS = [
    "pe",
    "pb",
    "roe",
    "roa",
    "net_margin",
    "gross_margin",
    "debt_to_equity",
    "dividend_yield",
    "revenue_growth",
    "earnings_growth",
]

# Ngành dưới ngần này mã có số liệu thì không ghi — trung vị của 3 mã không đại
# diện cho ngành, hiển thị ra chỉ làm người đọc tin nhầm.
MIN_SAMPLE = 5

# Giá trị ngoài khoảng này gần như chắc chắn là lỗi dữ liệu nguồn, không phải
# doanh nghiệp thật. Lọc trước khi lấy trung vị.
SANE_RANGE = {
    "pe": (0.0, 200.0),
    "pb": (0.0, 30.0),
    "roe": (-200.0, 200.0),
    "roa": (-100.0, 100.0),
    "net_margin": (-500.0, 100.0),
    "gross_margin": (-100.0, 100.0),
    "debt_to_equity": (0.0, 20.0),
    "dividend_yield": (0.0, 50.0),
    "revenue_growth": (-100.0, 500.0),
    "earnings_growth": (-500.0, 500.0),
}

# vnstock free tier: 20 request/phút. fetch_fundamentals tốn 1-2 request mỗi mã,
# nên nghỉ 4s giữa các mã để ở dưới trần một cách chắc chắn.
THROTTLE_SECONDS = 4.0

# Số mã lấy cho mỗi ngành ở chế độ 'all'. 12 đủ để trung vị ổn định mà vẫn giữ
# tổng thời gian quét dưới 25 phút với 19 ngành.
PER_SECTOR = 12

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sector_benchmarks.json"
)


def _sector_map() -> Dict[str, str]:
    """symbol -> tên ngành ICB cấp 2."""
    mapping: Dict[str, str] = {}
    for industry in get_industries():
        for symbol in industry.get("symbols") or []:
            if is_vn_symbol(symbol):
                mapping[symbol] = industry["name"]
    return mapping


def _liquidity_rank(
    symbols: List[str], retries: int = 3, pause: float = 3.0
) -> Optional[Dict[str, float]]:
    """
    Giá trị khớp lệnh phiên gần nhất của từng mã, dùng để xếp hạng.

    price_board nhận nhiều mã trong MỘT request nên xếp hạng cả ngành chỉ tốn
    1-2 request — rẻ hơn nhiều so với gọi lịch sử giá từng mã.

    Trả None khi có lô vẫn trống sau khi thử lại. Phải tách bạch "không xếp
    hạng được" với "mã không có giao dịch": fetch_price_board nuốt lỗi rate limit
    và trả dict rỗng, và bản đầu của job coi dict rỗng là "mọi mã thanh khoản
    bằng 0" rồi lấp chỗ trống theo thứ tự ABC. Ngành Hàng cá nhân & Gia dụng vì
    thế được đại diện bởi A32, AAT, ADS, BBT... thay vì PNJ, TCM, TNG.
    """
    try:
        from foreign_service import fetch_price_board
    except Exception:
        return None

    out: Dict[str, float] = {}
    # price_board bắt đầu trả thiếu khi danh sách quá dài, nên chia lô.
    for i in range(0, len(symbols), 80):
        batch = symbols[i : i + 80]
        board: Dict[str, Any] = {}
        for attempt in range(retries):
            # Nghỉ trước MỌI lần gọi, kể cả lô đầu của mỗi ngành. Bản trước chỉ
            # nghỉ giữa các lô trong cùng một ngành, nên đầu mỗi ngành bắn liền
            # nhau và dính hạn mức 20 request/phút. Lần thử lại nghỉ lâu dần.
            time.sleep(pause * (attempt + 1))
            try:
                board = fetch_price_board(batch) or {}
            except Exception:
                board = {}
            if board:
                break
        if not board:
            return None
        for symbol, row in board.items():
            price = row.get("price") or 0
            volume = row.get("total_volume") or 0
            out[symbol] = float(price) * float(volume)
    return out


def pick_universe(per_sector: int, core: List[str]) -> List[str]:
    """
    Chọn mã đại diện cho MỌI ngành, ưu tiên mã thanh khoản cao nhất ngành đó.

    Vì sao không quét sạch sàn: 1.800 mã x 4 giây là hơn hai tiếng, và phần lớn
    là mã gần như không có giao dịch. Vì sao không chỉ dùng VN100: 12 trên 19
    ngành không đủ 5 mã trong rổ đó, nên những ngành ấy vĩnh viễn không có số để
    so — kể cả ngành Công nghệ Thông tin, tức là chính FPT.

    Vì sao xếp theo thanh khoản chứ không lấy bừa: trung vị dựng từ 12 mã penny
    trong ngành Xây dựng không mô tả ngành xây dựng mà người dùng đang cân nhắc
    mua. Ưu tiên mã giao dịch nhiều = ưu tiên phần thị trường thật sự đầu tư được.

    Hai trường hợp KHÔNG được lấp chỗ trống theo thứ tự ABC:
      - mã không khớp lệnh nào: loại hẳn, không xếp cuối;
      - ngành mà price_board không trả được dù đã thử lại: chỉ giữ mã VN100.
    Ngành vì thế có thể rớt khỏi bảng do không đủ mẫu — đúng như mong muốn.
    """
    core_set = {s for s in core if is_vn_symbol(s)}
    chosen: List[str] = []
    seen = set()
    unranked: List[str] = []

    for industry in get_industries():
        members = [s for s in (industry.get("symbols") or []) if is_vn_symbol(s)]
        if not members:
            continue
        ranks = _liquidity_rank(members)
        if ranks is None:
            unranked.append(industry["name"])
            picked = [s for s in members if s in core_set][:per_sector]
            note = "KHONG xep hang duoc, chi dung ma VN100"
        else:
            candidates = [s for s in members if s in core_set or ranks.get(s, 0.0) > 0]
            candidates.sort(key=lambda s: (s not in core_set, -ranks.get(s, 0.0), s))
            picked = candidates[:per_sector]
            traded = sum(1 for v in ranks.values() if v > 0)
            note = f"co giao dich {traded}/{len(members)}"
        print(f"  {industry['name']}: chon {len(picked)} ma ({note})")
        for symbol in picked:
            if symbol not in seen:
                seen.add(symbol)
                chosen.append(symbol)

    if unranked:
        print(
            f"CANH BAO: khong xep hang thanh khoan duoc {len(unranked)} nganh "
            f"({', '.join(unranked)}) - cac nganh nay chi dung ma VN100."
        )

    # Giữ lại toàn bộ rổ chính kể cả khi mã đó không lọt top ngành — đó là những
    # mã người dùng tra cứu nhiều nhất.
    for symbol in core:
        if is_vn_symbol(symbol) and symbol not in seen:
            seen.add(symbol)
            chosen.append(symbol)

    return chosen


def _sane(metric: str, value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    low, high = SANE_RANGE[metric]
    return v if low <= v <= high else None


def collect(symbols: List[str], throttle: float = THROTTLE_SECONDS) -> Dict[str, Dict[str, Any]]:
    """
    Lấy chỉ số cơ bản từng mã. Mã lỗi thì bỏ qua, không làm hỏng cả lượt quét.

    Bỏ luôn mã có số liệu quá cũ. Nhiều mã nhỏ ngừng công bố từ 2019-2020 nhưng
    nguồn vẫn trả về kỳ cuối cùng đó; gộp một P/E của năm 2019 vào trung vị năm
    nay là so cổ phiếu hôm nay với mặt bằng lãi suất và giá vốn của bảy năm trước.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for i, symbol in enumerate(symbols):
        try:
            data = fetch_fundamentals(symbol)
        except Exception as e:
            print(f"  [{i + 1}/{len(symbols)}] {symbol}: loi - {str(e)[:60]}")
            continue
        if not data.get("available"):
            print(f"  [{i + 1}/{len(symbols)}] {symbol}: khong co du lieu")
            continue
        if data.get("stale"):
            print(f"  [{i + 1}/{len(symbols)}] {symbol}: BO QUA, so lieu cu ({data.get('period')})")
            if throttle and not data.get("cached"):
                time.sleep(throttle)
            continue
        out[symbol] = data
        print(f"  [{i + 1}/{len(symbols)}] {symbol}: OK ({data.get('period')})")
        # Bản cache trong market_service trả ngay, không tốn request -> không cần nghỉ.
        if throttle and not data.get("cached"):
            time.sleep(throttle)
    return out


def aggregate(
    fundamentals: Dict[str, Dict[str, Any]],
    sector_of: Dict[str, str],
    universe: str = "all",
) -> Dict[str, Any]:
    """Gom theo ngành rồi lấy trung vị từng chỉ số."""
    buckets: Dict[str, Dict[str, List[float]]] = {}
    members: Dict[str, List[str]] = {}

    for symbol, data in fundamentals.items():
        sector = sector_of.get(symbol)
        if not sector:
            continue
        members.setdefault(sector, []).append(symbol)
        bucket = buckets.setdefault(sector, {m: [] for m in BENCHMARK_METRICS})
        for metric in BENCHMARK_METRICS:
            value = _sane(metric, data.get(metric))
            if value is not None:
                bucket[metric].append(value)

    sectors: Dict[str, Any] = {}
    for sector, bucket in buckets.items():
        metrics = {}
        for metric, values in bucket.items():
            if len(values) >= MIN_SAMPLE:
                metrics[metric] = {
                    "median": round(statistics.median(values), 4),
                    "sample": len(values),
                }
        if metrics:
            sectors[sector] = {"metrics": metrics, "members": sorted(members[sector])}

    # Chỉ ghi ánh xạ của mã thuộc ngành thật sự có số liệu — tránh trường hợp UI
    # biết mã thuộc ngành nào nhưng ngành đó lại không có trung vị để so.
    symbol_sector = {
        symbol: sector
        for sector, payload in sectors.items()
        for symbol in payload["members"]
    }

    return {
        "generated_at": now_vn().strftime("%Y-%m-%d"),
        "universe": universe,
        "min_sample": MIN_SAMPLE,
        "sectors": sectors,
        "symbol_sector": symbol_sector,
    }


def main() -> int:
    force_utf8_console()
    parser = argparse.ArgumentParser(description="Tinh trung vi chi so co ban theo nganh")
    parser.add_argument(
        "--universe",
        choices=("all", "vn100"),
        default="all",
        help="all = top thanh khoan moi nganh (mac dinh); vn100 = chi ro VN100",
    )
    parser.add_argument("--per-sector", type=int, default=PER_SECTOR)
    parser.add_argument("--limit", type=int, default=0, help="Chi quet N ma dau (de test)")
    parser.add_argument("--dry-run", action="store_true", help="In ket qua, khong ghi file")
    parser.add_argument("--throttle", type=float, default=THROTTLE_SECONDS)
    args = parser.parse_args()

    print("Lay danh sach VN100...")
    core = [s for s in get_vn100_symbols() if is_vn_symbol(s)]
    print(f"  {len(core)} ma trong ro")

    if args.universe == "vn100":
        symbols = core
    else:
        print(f"Chon top {args.per_sector} ma thanh khoan cao nhat moi nganh...")
        symbols = pick_universe(args.per_sector, core)
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"  {len(symbols)} ma se quet (~{len(symbols) * args.throttle / 60:.0f} phut)")

    print("Lay ban do nganh ICB...")
    sector_of = _sector_map()
    print(f"  {len(sector_of)} ma co nganh")

    print(f"Lay chi so co ban ({args.throttle}s/ma)...")
    fundamentals = collect(symbols, throttle=args.throttle)
    print(f"  lay duoc {len(fundamentals)}/{len(symbols)} ma")

    payload = aggregate(fundamentals, sector_of, universe=args.universe)
    print(f"\n{len(payload['sectors'])} nganh du {MIN_SAMPLE} mau:")
    for sector, data in sorted(payload["sectors"].items()):
        pe = data["metrics"].get("pe")
        pe_text = f"P/E {pe['median']:.1f} (n={pe['sample']})" if pe else "khong co P/E"
        print(f"  - {sector}: {len(data['members'])} ma, {pe_text}")

    if args.dry_run:
        print("\n--dry-run: khong ghi file")
        return 0

    # Quét hỏng (mất mạng, sai interpreter, vnstock đổi API) cũng chạy hết vòng lặp
    # và cho ra bảng rỗng. Ghi đè bằng bảng rỗng là âm thầm tắt tính năng so sánh
    # ngành, nên thà giữ bảng cũ còn hơn.
    if not payload["sectors"]:
        print("\nKhong nganh nao du mau -> GIU NGUYEN file cu, khong ghi de.")
        return 1

    # Ghi qua file tạm rồi đổi tên: web server đang chạy có thể đọc file này bất
    # cứ lúc nào, mà ghi thẳng thì có một khoảnh khắc file rỗng hoặc mới nửa chừng
    # — đủ để một request rơi vào JSONDecodeError.
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    tmp_path = OUTPUT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp_path, OUTPUT_PATH)
    print(f"\nDa ghi {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
