"""
Tài chính cá nhân: tổng tài sản, phân bổ, và vài kiểm tra an toàn cơ bản.

Vì sao có phần này: đầu tư an toàn không bắt đầu từ chọn mã mà từ câu hỏi "tiền của
tôi đang nằm ở đâu". Người mới hay dồn hết vào cổ phiếu mà không giữ quỹ dự phòng, nên
chỉ cần một khoản chi bất ngờ đúng lúc thị trường giảm 20% là phải bán cổ phiếu để trang
trải — khoản lỗ tạm thời biến thành lỗ thật.

Người dùng tự nhập tiền mặt, tiết kiệm, chi tiêu, nợ; phần cổ phiếu lấy từ danh mục thật
(real_portfolio_service). Các ngưỡng dưới đây là quy tắc phổ biến cho người mới, đặt ở
đầu file để ai cũng soi được — không phải lời khuyên tài chính cá nhân hoá.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

# ---------- Ngưỡng ----------

# Quỹ dự phòng tính bằng số tháng chi tiêu mà tiền mặt + tiết kiệm trang trải được.
# Dưới 3 tháng: một lần mất việc hay ốm là phải bán tài sản. 6 tháng là mức thường khuyến
# nghị cho người có thu nhập ổn định.
EMERGENCY_MONTHS_MIN = 3.0
EMERGENCY_MONTHS_TARGET = 6.0

# Phần cổ phiếu trong tổng tài sản. Trên 50% thì một đợt giảm 30% của thị trường (đã xảy
# ra năm 2022) lấy đi hơn 15% toàn bộ tài sản.
STOCK_SHARE_OK_PCT = 50.0
STOCK_SHARE_HIGH_PCT = 70.0

# Một mã trên tổng tài sản. Cùng tinh thần với trần 20% vốn mỗi mã ở trade_plan.py.
SINGLE_STOCK_OK_PCT = 20.0
SINGLE_STOCK_HIGH_PCT = 35.0

# Nợ trên tổng tài sản.
DEBT_OK_PCT = 30.0
DEBT_HIGH_PCT = 50.0

# Lãi tiết kiệm mặc định khi người dùng chưa nhập, dùng làm mốc so sánh.
DEFAULT_SAVINGS_RATE_PCT = 5.0
MAX_SAVINGS_RATE_PCT = 20.0

INPUT_FIELDS: Dict[str, str] = {
    "cash": "Tiền mặt và tài khoản thanh toán",
    "savings": "Tiền gửi tiết kiệm",
    "broker_cash": "Tiền mặt trong tài khoản chứng khoán",
    "other_assets": "Tài sản khác (vàng, chứng chỉ quỹ...)",
    "debts": "Khoản nợ phải trả",
    "monthly_expenses": "Chi tiêu trung bình mỗi tháng",
    "savings_rate_pct": "Lãi suất tiết kiệm (%/năm)",
}

# Có ít nhất một trong các ô này thì mới biết "tổng tài sản" ngoài cổ phiếu. Không có thì
# mọi tỷ lệ trên tổng tài sản đều là tỷ lệ trên... chính cổ phiếu, tức luôn 100%.
_NON_STOCK_FIELDS = ("cash", "savings", "broker_cash", "other_assets")

DISCLAIMER = (
    "Các ngưỡng là quy tắc chung cho người mới, không phải lời khuyên của chuyên gia tư vấn "
    "tài chính có giấy phép. App không đặt lệnh và không biết hết hoàn cảnh của bạn (thu "
    "nhập, người phụ thuộc, kế hoạch dùng tiền)."
)


class FinanceInputError(ValueError):
    pass


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(" ", "")
        if not text:
            return None
        # Người Việt gõ 1.000.000 hoặc 1,000,000 đều là một triệu.
        text = text.replace(".", "").replace(",", "") if text.count(".") + text.count(",") > 1 else text.replace(",", ".")
        try:
            number = float(text)
        except ValueError:
            raise FinanceInputError(f"'{value}' không phải là số.")
    if number != number:
        return None
    return number


def validate_inputs(raw: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Chuẩn hoá dữ liệu người dùng nhập. Bỏ trống thì là None, không phải 0."""
    cleaned: Dict[str, Optional[float]] = {}
    for field, label in INPUT_FIELDS.items():
        number = _to_number((raw or {}).get(field))
        if number is not None and number < 0:
            raise FinanceInputError(f"{label} không được âm.")
        if field == "savings_rate_pct" and number is not None and number > MAX_SAVINGS_RATE_PCT:
            raise FinanceInputError(f"Lãi suất tiết kiệm {number}%/năm cao bất thường, kiểm tra lại.")
        cleaned[field] = number
    return cleaned


def _band(value: float, ok: float, high: float) -> str:
    if value <= ok:
        return "pass"
    return "warn" if value <= high else "fail"


def _vnd(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") + " đ"


def _check(key, label, status, display, threshold, explain=None) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "display": display,
        "threshold": threshold,
        "explain": explain,
    }


def compute(
    inputs: Optional[Dict[str, Optional[float]]],
    portfolio: Optional[Dict[str, Any]],
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Tính tổng tài sản, phân bổ và các kiểm tra. Không gọi mạng — xem finance_for.

    `portfolio` là kết quả get_real_portfolio(). Thiếu giá thị trường thì dùng giá vốn,
    và nói rõ điều đó.
    """
    inputs = inputs or {}
    today = today or date.today()
    val = lambda key: float(inputs.get(key) or 0.0)  # noqa: E731

    summary = (portfolio or {}).get("summary") or {}
    positions = (portfolio or {}).get("positions") or []
    stocks_cost = float(summary.get("total_cost") or 0.0)
    market_value = float(summary.get("market_value") or 0.0)
    stocks_priced = market_value > 0
    stocks_value = market_value if stocks_priced else stocks_cost

    has_non_stock = any(inputs.get(k) is not None for k in _NON_STOCK_FIELDS)
    total_assets = val("cash") + val("savings") + val("broker_cash") + val("other_assets") + stocks_value
    debts = val("debts")
    net_worth = total_assets - debts

    parts = [
        ("cash", "Tiền mặt", val("cash")),
        ("savings", "Tiết kiệm", val("savings")),
        ("broker_cash", "Tiền trong TK chứng khoán", val("broker_cash")),
        ("stocks", "Cổ phiếu", stocks_value),
        ("other_assets", "Tài sản khác", val("other_assets")),
    ]
    allocation = [
        {"key": key, "label": label, "value": round(value, 0),
         "pct": round(value / total_assets * 100.0, 2) if total_assets else None}
        for key, label, value in parts
        if value > 0
    ]

    checks: List[Dict[str, Any]] = []

    # 1. Quỹ dự phòng
    expenses = inputs.get("monthly_expenses")
    liquid = val("cash") + val("savings")
    if not expenses:
        checks.append(_check(
            "emergency", "Quỹ dự phòng", "unknown", "Chưa nhập chi tiêu hằng tháng",
            f"Tiền mặt + tiết kiệm đủ ít nhất {EMERGENCY_MONTHS_TARGET:.0f} tháng chi tiêu",
        ))
    else:
        months = liquid / float(expenses)
        status = "pass" if months >= EMERGENCY_MONTHS_TARGET else ("warn" if months >= EMERGENCY_MONTHS_MIN else "fail")
        checks.append(_check(
            "emergency", "Quỹ dự phòng", status, f"{months:.1f} tháng chi tiêu",
            f"Ít nhất {EMERGENCY_MONTHS_TARGET:.0f} tháng (tối thiểu {EMERGENCY_MONTHS_MIN:.0f})",
            None if status == "pass" else (
                "Không có quỹ dự phòng thì một khoản chi bất ngờ lúc thị trường giảm sẽ buộc "
                "bán cổ phiếu, biến lỗ tạm thời thành lỗ thật."
            ),
        ))

    # 2. Phần cổ phiếu trên tổng tài sản
    if not has_non_stock:
        checks.append(_check(
            "stock_share", "Cổ phiếu trên tổng tài sản", "unknown", "Chưa nhập tiền mặt, tiết kiệm",
            f"Không quá {STOCK_SHARE_OK_PCT:.0f}% tổng tài sản",
        ))
    elif total_assets > 0:
        share = stocks_value / total_assets * 100.0
        status = _band(share, STOCK_SHARE_OK_PCT, STOCK_SHARE_HIGH_PCT)
        checks.append(_check(
            "stock_share", "Cổ phiếu trên tổng tài sản", status, f"{share:.1f}%",
            f"Không quá {STOCK_SHARE_OK_PCT:.0f}% tổng tài sản",
            None if status == "pass" else (
                f"Thị trường giảm 30% thì tổng tài sản của bạn giảm khoảng {share * 0.3:.0f}%."
            ),
        ))

    # 3. Một mã trên tổng tài sản
    priced_positions = [p for p in positions if (p.get("market_value") or p.get("cost_basis"))]
    if priced_positions and has_non_stock and total_assets > 0:
        top = max(priced_positions, key=lambda p: float(p.get("market_value") or p.get("cost_basis") or 0))
        top_value = float(top.get("market_value") or top.get("cost_basis") or 0)
        share = top_value / total_assets * 100.0
        status = _band(share, SINGLE_STOCK_OK_PCT, SINGLE_STOCK_HIGH_PCT)
        checks.append(_check(
            "single_stock", f"Mã lớn nhất ({top['symbol']}) trên tổng tài sản", status, f"{share:.1f}%",
            f"Không quá {SINGLE_STOCK_OK_PCT:.0f}% tổng tài sản",
            None if status == "pass" else (
                f"Riêng {top['symbol']} giảm thêm 20% thì tổng tài sản giảm khoảng {share * 0.2:.1f}%. "
                f"Rủi ro của một doanh nghiệp không được bù bởi mã nào khác."
            ),
        ))
    elif priced_positions:
        checks.append(_check(
            "single_stock", "Mã lớn nhất trên tổng tài sản", "unknown", "Chưa nhập tiền mặt, tiết kiệm",
            f"Không quá {SINGLE_STOCK_OK_PCT:.0f}% tổng tài sản",
        ))

    # 4. Nợ
    if debts > 0 and total_assets > 0:
        ratio = debts / total_assets * 100.0
        status = _band(ratio, DEBT_OK_PCT, DEBT_HIGH_PCT)
        checks.append(_check(
            "debt", "Nợ trên tổng tài sản", status, f"{ratio:.1f}%",
            f"Không quá {DEBT_OK_PCT:.0f}%",
            "Lãi vay chắc chắn phải trả, còn lợi nhuận cổ phiếu thì không." if stocks_value > 0 and status != "pass" else None,
        ))

    # 5. So với gửi tiết kiệm — thông tin, không chấm đạt/trượt
    rate = inputs.get("savings_rate_pct")
    rate = DEFAULT_SAVINGS_RATE_PCT if rate is None else float(rate)
    comparison = None
    if stocks_cost > 0 and stocks_priced:
        comparison = _savings_comparison(positions, summary, rate, today)

    fails = sum(1 for c in checks if c["status"] == "fail")
    warns = sum(1 for c in checks if c["status"] == "warn")
    unknown = sum(1 for c in checks if c["status"] == "unknown")
    if not has_non_stock and not expenses:
        headline = "Nhập tiền mặt, tiết kiệm và chi tiêu hằng tháng để app kiểm tra tài chính của bạn."
    elif fails:
        headline = f"{fails} điểm vượt ngưỡng an toàn, {warns} điểm cần chú ý."
    elif warns:
        headline = f"Không có điểm vượt ngưỡng, {warns} điểm cần chú ý."
    else:
        headline = "Các kiểm tra đã có dữ liệu đều trong ngưỡng an toàn." + (
            f" Còn {unknown} mục thiếu dữ liệu." if unknown else ""
        )

    return {
        "inputs": {k: inputs.get(k) for k in INPUT_FIELDS},
        "fields": INPUT_FIELDS,
        "needs_setup": not has_non_stock and not expenses,
        "total_assets": round(total_assets, 0),
        "debts": round(debts, 0),
        "net_worth": round(net_worth, 0),
        "stocks": {
            "value": round(stocks_value, 0),
            "cost": round(stocks_cost, 0),
            "priced": stocks_priced,
            "unrealized_pnl": summary.get("unrealized_pnl"),
            "unrealized_pct": summary.get("unrealized_pct"),
        },
        "allocation": allocation,
        "checks": checks,
        "savings_comparison": comparison,
        "headline": headline,
        "disclaimer": DISCLAIMER,
    }


def _savings_comparison(
    positions: List[Dict[str, Any]], summary: Dict[str, Any], rate: float, today: date
) -> Optional[Dict[str, Any]]:
    """
    Cùng số tiền đã bỏ vào cổ phiếu, nếu gửi tiết kiệm thì đến nay lãi bao nhiêu.

    Tính theo từng lô mua: tiền của lô mua tháng 3 không thể sinh lãi tiết kiệm từ tháng
    7 năm trước. Lấy chung ngày giao dịch đầu tiên cho mọi đồng sẽ thổi phồng khoản lãi
    bỏ lỡ và khiến cổ phiếu trông tệ hơn thực tế. Không có chi tiết lô thì mới dùng ngày
    giao dịch đầu tiên, và nói rõ.
    """
    def parse(value: Any) -> Optional[date]:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    lots = []
    for position in positions:
        for lot in position.get("lots") or []:
            lot_date = parse(lot.get("date"))
            amount = float(lot.get("quantity") or 0) * float(lot.get("price") or 0)
            if lot_date and amount > 0 and lot_date <= today:
                lots.append((lot_date, amount))

    by_lot = bool(lots)
    if not lots:
        start = parse(summary.get("first_txn"))
        cost = float(summary.get("total_cost") or 0.0)
        if not start or start > today or cost <= 0:
            return None
        lots = [(start, cost)]

    invested = sum(amount for _, amount in lots)
    savings_gain = sum(amount * rate / 100.0 * (today - lot_date).days / 365.0 for lot_date, amount in lots)
    since = min(lot_date for lot_date, _ in lots)
    stock_pnl = float(summary.get("unrealized_pnl") or 0.0) + float(summary.get("realized_pnl") or 0.0)
    basis = "tính từ ngày mua của từng lô" if by_lot else f"tính từ {since.strftime('%d/%m/%Y')}"
    return {
        "since": since.isoformat(),
        "days": (today - since).days,
        "by_lot": by_lot,
        "rate_pct": rate,
        "invested": round(invested, 0),
        "savings_gain": round(savings_gain, 0),
        "stock_pnl": round(stock_pnl, 0),
        "difference": round(stock_pnl - savings_gain, 0),
        "text": (
            f"Nếu {_vnd(invested)} đã bỏ vào cổ phiếu được gửi tiết kiệm {rate:g}%/năm ({basis}), "
            f"đến nay lãi khoảng {_vnd(savings_gain)}. Danh mục cổ phiếu đang "
            f"{'lãi' if stock_pnl >= 0 else 'lỗ'} {_vnd(abs(stock_pnl))} (đã trừ phí, thuế nếu bán)."
        ),
    }


def finance_for() -> Dict[str, Any]:
    """Đọc số liệu người dùng đã lưu và danh mục thật (có giá thị trường), rồi tính."""
    import storage_service as storage
    from real_portfolio_service import get_real_portfolio

    saved = storage.get_personal_finance() or {}
    try:
        portfolio = get_real_portfolio(include_prices=True)
    except Exception:
        portfolio = get_real_portfolio(include_prices=False)
    result = compute(saved.get("inputs") or {}, portfolio)
    result["updated_at"] = saved.get("updated_at")
    return result


def save_and_compute(raw: Dict[str, Any]) -> Dict[str, Any]:
    import storage_service as storage

    inputs = validate_inputs(raw)
    storage.save_personal_finance({"inputs": inputs})
    return finance_for()
