"""
Bối cảnh vĩ mô thế giới tác động tới chứng khoán Việt Nam.

Chọn 4 chỉ số này chứ không phải "tin tức thế giới" chung chung, vì đây là
những thứ có đường truyền dẫn RÕ RÀNG tới VN-Index:

- USD/VND       : tỷ giá tăng -> khối ngoại rút vốn, doanh nghiệp vay USD chịu
                  lỗ tỷ giá (HPG, hàng không, điện).
- Lợi suất TP Mỹ: lãi suất Mỹ cao -> dòng vốn rời thị trường mới nổi.
- Dầu Brent     : chi phí đầu vào cho vận tải/hoá chất; ngược lại có lợi cho
                  GAS, PLX, BSR.
- S&P 500       : chỉ báo khẩu vị rủi ro toàn cầu.

Toàn bộ là số liệu thị trường lấy qua yfinance (miễn phí), KHÔNG dùng AI. AI chỉ
đọc lại các con số này để viết bối cảnh — nó không được tự bịa ra số.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# PHẢI chạy trước khi import yfinance: đường dẫn dự án có dấu tiếng Việt làm
# libcurl không nạp được CA bundle, yfinance sẽ lỗi SSL ở mọi request.
from ssl_bootstrap import ensure_ca_bundle

ensure_ca_bundle()

import yfinance as yf  # noqa: E402 - phải sau ensure_ca_bundle()

# (mã yfinance, tên hiển thị, đơn vị, giải thích đường truyền dẫn tới TTCK VN)
MACRO_TICKERS = (
    (
        "VND=X",
        "USD/VND",
        "đ",
        "Tỷ giá tăng thường đi kèm khối ngoại bán ròng và gây lỗ tỷ giá cho doanh nghiệp vay USD.",
    ),
    (
        "^TNX",
        "Lợi suất trái phiếu Mỹ 10 năm",
        "%",
        "Lợi suất Mỹ tăng khiến dòng vốn rút khỏi thị trường mới nổi như Việt Nam.",
    ),
    (
        "BZ=F",
        "Dầu Brent",
        "USD/thùng",
        "Dầu tăng làm tăng chi phí vận tải và hoá chất, nhưng có lợi cho nhóm dầu khí (GAS, PLX, BSR).",
    ),
    (
        "^GSPC",
        "S&P 500",
        "điểm",
        "Đại diện khẩu vị rủi ro toàn cầu; chứng khoán Mỹ giảm mạnh thường kéo tâm lý thị trường VN đi xuống.",
    ),
)


def _pct(current: float, previous: float) -> Optional[float]:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 2)


def fetch_macro_snapshot() -> Dict[str, Any]:
    """
    Giá mới nhất + thay đổi 1 phiên và 5 phiên cho từng chỉ số vĩ mô.

    Lỗi một mã không được làm hỏng cả bản tin — mã nào không lấy được thì bỏ
    qua và ghi vào `errors` để còn biết mà sửa.
    """
    items: List[Dict[str, Any]] = []
    errors: List[str] = []

    for ticker, label, unit, transmission in MACRO_TICKERS:
        try:
            history = yf.Ticker(ticker).history(period="1mo", interval="1d")
            closes = history["Close"].dropna()
            if len(closes) < 2:
                errors.append(f"{label}: không đủ dữ liệu")
                continue

            latest = float(closes.iloc[-1])
            item = {
                "ticker": ticker,
                "label": label,
                "unit": unit,
                "value": round(latest, 2),
                "change_1d_pct": _pct(latest, float(closes.iloc[-2])),
                "change_5d_pct": _pct(latest, float(closes.iloc[-6])) if len(closes) >= 6 else None,
                "transmission": transmission,
                "as_of": str(closes.index[-1].date()),
            }
            items.append(item)
        except Exception as e:
            errors.append(f"{label}: {str(e)[:100]}")

    return {"items": items, "errors": errors}


def format_macro_for_prompt(snapshot: Dict[str, Any]) -> str:
    """Bảng số liệu vĩ mô để nhét vào prompt. AI đọc bảng này, không tự tra cứu."""
    items = snapshot.get("items") or []
    if not items:
        return "Bối cảnh vĩ mô: không lấy được dữ liệu."

    lines = ["Bối cảnh vĩ mô thế giới (số liệu thật, không được thay đổi):"]
    for item in items:
        change_1d = f"{item['change_1d_pct']:+.2f}%" if item["change_1d_pct"] is not None else "N/A"
        change_5d = f"{item['change_5d_pct']:+.2f}%" if item["change_5d_pct"] is not None else "N/A"
        lines.append(
            f"- {item['label']}: {item['value']:,} {item['unit']} "
            f"(1 phiên {change_1d}, 5 phiên {change_5d}, tính đến {item['as_of']})"
        )
        lines.append(f"  Cơ chế tác động: {item['transmission']}")
    return "\n".join(lines)
