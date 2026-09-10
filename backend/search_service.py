"""
Tìm kiếm mã chứng khoán trên toàn sàn.

Trước đây /api/stocks/search chỉ dò trong 10 mã hardcode rồi "đoán" bất kỳ chuỗi
3 chữ cái nào cũng là mã hợp lệ — gõ "Hòa Phát" hay "thủy sản" không ra gì, còn
gõ "XYZ" lại được gợi ý như một mã có thật.

Module này dựng index từ danh sách niêm yết của vnstock (~1.700 mã kèm tên doanh
nghiệp và ngành ICB), cache 24 giờ. Khi vnstock không dùng được thì rơi về danh
sách mã phổ biến để ô tìm kiếm không chết hẳn.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional

from market_service import TTLCache
from symbol_utils import is_vn_symbol

try:
    from vnstock import Listing
    HAS_LISTING = True
except ImportError:
    HAS_LISTING = False


LISTING_TTL_SECONDS = 24 * 3600.0

# Dùng khi vnstock fail. Giữ đúng shape với entry dựng từ listing.
FALLBACK_STOCKS: List[Dict[str, Any]] = [
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

# Mã mặc định hiển thị khi ô tìm kiếm còn trống.
POPULAR_SYMBOLS = [s["symbol"] for s in FALLBACK_STOCKS]

# Tên thương hiệu quen thuộc không trùng tên pháp nhân trong danh sách niêm yết
# ("Vinamilk" vs "Công ty Cổ phần Sữa Việt Nam") — không có bảng này thì gõ đúng
# cái tên ai cũng biết lại không ra kết quả nào.
BRAND_ALIASES: Dict[str, str] = {
    "VNM": "Vinamilk",
    "TCB": "Techcombank",
    "VCB": "Vietcombank",
    "BID": "BIDV",
    "CTG": "VietinBank",
    "VPB": "VPBank",
    "MBB": "MB Bank MBBank",
    "STB": "Sacombank",
    "ACB": "ACB Á Châu",
    "HDB": "HDBank",
    "TPB": "TPBank",
    "VIB": "VIB",
    "SHB": "SHB",
    "EIB": "Eximbank",
    "MSB": "Maritime Bank MSB",
    "OCB": "OCB Phương Đông",
    "LPB": "LPBank Bưu điện Liên Việt",
    "SSB": "SeABank",
    "MWG": "Thế Giới Di Động Điện Máy Xanh Bách Hoá Xanh",
    "FRT": "FPT Retail FPT Shop Long Châu",
    "PNJ": "Phú Nhuận PNJ",
    "VIC": "Vingroup",
    "VHM": "Vinhomes",
    "VRE": "Vincom Retail",
    "VJC": "Vietjet Air",
    "HVN": "Vietnam Airlines",
    "GAS": "PV Gas",
    "PLX": "Petrolimex",
    "BSR": "Lọc hoá dầu Bình Sơn Dung Quất",
    "SAB": "Sabeco Bia Sài Gòn",
    "BHN": "Habeco Bia Hà Nội",
    "MSN": "Masan",
    "HPG": "Hoà Phát",
    "SSI": "SSI Chứng khoán Sài Gòn",
    "VND": "VNDirect",
    "HCM": "HSC Chứng khoán TP HCM",
    "VCI": "Vietcap Bản Việt",
    "FPT": "FPT Corp",
    "CMG": "CMC",
    "GVR": "Cao su Việt Nam",
    "DGC": "Đức Giang",
    "REE": "REE Cơ Điện Lạnh",

}

_cache = TTLCache()


def _fold(text: str) -> str:
    """Bỏ dấu + hạ chữ thường để 'hoa phat' khớp được 'Hòa Phát'."""
    lowered = unicodedata.normalize("NFD", (text or "").lower())
    stripped = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    return stripped.replace("đ", "d")


def _is_stock_ticker(symbol: str) -> bool:
    """Mã cổ phiếu niêm yết VN (cho phép chữ số: HT1, PC1...)."""
    return is_vn_symbol(symbol)


def _build_index() -> List[Dict[str, Any]]:
    """
    Dựng danh sách {symbol, name, sector, search} từ vnstock.
    Trả [] nếu không lấy được — caller tự fallback.
    """
    if not HAS_LISTING:
        return []

    try:
        df = Listing(source="VCI").symbols_by_industries()
    except Exception as e:
        print(f"[search] không lấy được danh sách niêm yết: {str(e)[:150]}")
        return []

    if df is None or df.empty or "symbol" not in df.columns:
        return []

    name_col = "organ_name" if "organ_name" in df.columns else None
    sector_col = "icb_name" if "icb_name" in df.columns else None
    level_col = "icb_level" if "icb_level" in df.columns else None

    # Long-format: mỗi mã 4 dòng theo cấp ICB. Giữ cấp 2 để có tên ngành gọn.
    if level_col is not None:
        levels = df[level_col].astype(str).str.strip()
        subset = df[levels == "2"]
        if not subset.empty:
            df = subset

    entries: Dict[str, Dict[str, Any]] = {}
    for row in df.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "") or "").strip().upper()
        if not _is_stock_ticker(symbol) or symbol in entries:
            continue
        name = str(getattr(row, name_col, "") or "").strip() if name_col else ""
        sector = str(getattr(row, sector_col, "") or "").strip() if sector_col else ""
        alias = BRAND_ALIASES.get(symbol, "")
        entries[symbol] = {
            "symbol": symbol,
            "name": name or f"Cổ phiếu {symbol}",
            "sector": sector,
            # Tách riêng để xếp hạng: khớp tên doanh nghiệp có ý nghĩa hơn nhiều
            # so với khớp tên ngành (cả trăm mã dùng chung một ngành).
            "_name": _fold(f"{name} {alias}"),
            "_sector": _fold(sector),
        }

    return sorted(entries.values(), key=lambda e: e["symbol"])


def get_index() -> List[Dict[str, Any]]:
    """Index mã chứng khoán, cache 24h. [] khi vnstock không khả dụng."""
    cached = _cache.get("symbol_index")
    if cached is not None:
        return cached

    index = _build_index()
    if index:
        _cache.set("symbol_index", index, LISTING_TTL_SECONDS)
    return index


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Bỏ field nội bộ (_search) trước khi trả ra API."""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def _liquidity_rank(symbol: str) -> int:
    """
    0 = VN30, 1 = VN100, 2 = còn lại.

    Dùng làm tiêu chí phụ khi nhiều mã cùng mức khớp: gõ "hoà phát" thì HPG (VN30)
    phải đứng trên HPA (công ty con), dù cả hai đều khớp tên.
    """
    baskets = _cache.get("liquidity_baskets")
    if baskets is None:
        vn30: set = set()
        vn100: set = set()
        try:
            from sector_service import get_vn30_symbols, get_vn100_symbols

            vn30 = set(get_vn30_symbols())
            vn100 = set(get_vn100_symbols())
        except Exception as e:
            print(f"[search] không lấy được rổ chỉ số: {str(e)[:120]}")
        baskets = (vn30, vn100)
        _cache.set("liquidity_baskets", baskets, LISTING_TTL_SECONDS)

    vn30, vn100 = baskets
    if symbol in vn30:
        return 0
    if symbol in vn100:
        return 1
    return 2


def search_symbols(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Tìm theo mã, tên doanh nghiệp hoặc ngành. Không phân biệt hoa thường và dấu.

    Xếp hạng: mã khớp chính xác > mã bắt đầu bằng query > tên bắt đầu bằng query
    > tên chứa query > ngành chứa query. Cùng hạng thì mã thanh khoản cao lên trước.
    """
    index = get_index()
    if not index:
        index = [
            {
                **s,
                "sector": "",
                "_name": _fold(f"{s['name']} {BRAND_ALIASES.get(s['symbol'], '')}"),
                "_sector": "",
            }
            for s in FALLBACK_STOCKS
        ]

    q = (query or "").strip()
    if not q:
        popular = {s: i for i, s in enumerate(POPULAR_SYMBOLS)}
        featured = [e for e in index if e["symbol"] in popular]
        featured.sort(key=lambda e: popular[e["symbol"]])
        return [_public(e) for e in featured[:limit]] or [
            {**s, "sector": ""} for s in FALLBACK_STOCKS[:limit]
        ]

    q_folded = _fold(q)
    q_upper = q.upper()

    scored: List[tuple] = []
    for entry in index:
        symbol = entry["symbol"]
        name = entry.get("_name", "")
        if symbol == q_upper:
            rank = 0
        elif symbol.startswith(q_upper):
            rank = 1
        elif name.startswith(q_folded):
            rank = 2
        elif q_folded in name:
            rank = 3
        elif q_folded in entry.get("_sector", ""):
            rank = 4
        else:
            continue
        scored.append((rank, _liquidity_rank(symbol), symbol, entry))

    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [_public(entry) for _, _, _, entry in scored[:limit]]


def resolve_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Thông tin 1 mã. None nếu mã không có trong danh sách niêm yết."""
    symbol = (symbol or "").strip().upper()
    if not _is_stock_ticker(symbol):
        return None
    for entry in get_index():
        if entry["symbol"] == symbol:
            return _public(entry)
    return None
