"""
Danh mục THẬT: dựng vị thế và lãi/lỗ từ sổ lệnh đã nhập.

Khác danh mục giả lập ở chỗ tính đúng tiền: phí môi giới hai chiều và thuế TNCN
0,1% trên giá trị bán. Đây là chỗ các bảng theo dõi tự làm bằng Excel hay sai —
lấy (giá bán - giá mua) × số lượng rồi tưởng đó là lãi, trong khi riêng phí +
thuế đã ăn khoảng 0,4% mỗi vòng mua-bán. Với người giao dịch nhiều lần trong
tháng, khoản đó lớn hơn phần lớn "tín hiệu" mà app này đưa ra.

Khớp lệnh bán theo FIFO — cách cơ quan thuế và công ty chứng khoán VN ghi nhận.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls
from typing import Any, Dict, List, Optional

import storage_service as storage

# Ngưỡng cảnh báo tỷ trọng một mã trên tổng giá trị danh mục.
CONCENTRATION_WARN_PCT = 30.0


def _safe_div(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator else None


def _build_positions(transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Chạy FIFO qua sổ lệnh -> vị thế còn nắm giữ + lãi/lỗ đã thực hiện.

    Giá vốn của lô mua đã gồm phí mua (phí là tiền thật bỏ ra để sở hữu cổ phiếu).
    Tiền thu về khi bán đã trừ phí bán và thuế.
    """
    lots: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    realized: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"proceeds": 0.0, "cost": 0.0, "pnl": 0.0, "fees": 0.0, "taxes": 0.0, "sold_qty": 0}
    )
    total_fees = 0.0
    total_taxes = 0.0
    total_invested = 0.0
    warnings: List[str] = []

    for txn in transactions:
        symbol = txn["symbol"]
        qty = int(txn["quantity"])
        price = float(txn["price"])
        fee = float(txn.get("fee") or 0.0)
        tax = float(txn.get("tax") or 0.0)
        total_fees += fee
        total_taxes += tax

        if txn["side"] == "BUY":
            lots[symbol].append(
                {
                    "date": txn["date"],
                    "quantity": qty,
                    "price": price,
                    # Phí mua phân bổ vào giá vốn từng cổ phiếu.
                    "cost_per_share": price + (fee / qty if qty else 0.0),
                }
            )
            total_invested += qty * price + fee
            continue

        # --- BÁN: khớp FIFO ---
        remaining = qty
        matched_cost = 0.0
        while remaining > 0 and lots[symbol]:
            lot = lots[symbol][0]
            take = min(remaining, lot["quantity"])
            matched_cost += take * lot["cost_per_share"]
            lot["quantity"] -= take
            remaining -= take
            if lot["quantity"] == 0:
                lots[symbol].pop(0)

        if remaining > 0:
            # Bán nhiều hơn số đang có: sổ lệnh thiếu giao dịch mua (thường do
            # nhập thiếu kỳ sao kê cũ). Báo rõ thay vì âm thầm tính sai giá vốn.
            warnings.append(
                f"{symbol}: bán {qty} CP ngày {txn['date']} nhưng sổ chỉ có "
                f"{qty - remaining} CP — thiếu giao dịch mua trước đó, lãi/lỗ mã này chưa chính xác."
            )

        net_proceeds = qty * price - fee - tax
        entry = realized[symbol]
        entry["proceeds"] += net_proceeds
        entry["cost"] += matched_cost
        entry["pnl"] += net_proceeds - matched_cost
        entry["fees"] += fee
        entry["taxes"] += tax
        entry["sold_qty"] += qty

    positions = []
    for symbol, symbol_lots in lots.items():
        shares = sum(l["quantity"] for l in symbol_lots)
        if shares <= 0:
            continue
        cost_basis = sum(l["quantity"] * l["cost_per_share"] for l in symbol_lots)
        positions.append(
            {
                "symbol": symbol,
                "shares": shares,
                "cost_basis": round(cost_basis, 0),
                "avg_cost": round(cost_basis / shares, 2),
                "first_buy": min(l["date"] for l in symbol_lots),
                "lots": [
                    {"date": l["date"], "quantity": l["quantity"], "price": round(l["price"], 2)}
                    for l in symbol_lots
                ],
            }
        )

    positions.sort(key=lambda p: p["cost_basis"], reverse=True)
    return {
        "positions": positions,
        "realized": dict(realized),
        "total_fees": round(total_fees, 0),
        "total_taxes": round(total_taxes, 0),
        "total_invested": round(total_invested, 0),
        "warnings": warnings,
    }


def _fetch_prices(symbols: List[str]) -> Dict[str, Optional[float]]:
    """
    Giá hiện tại cho từng mã. Ưu tiên price_board (1 request cho cả rổ) rồi mới
    rơi về từng mã — quan trọng vì vnstock chỉ cho 20 request/phút.
    """
    prices: Dict[str, Optional[float]] = {s: None for s in symbols}
    if not symbols:
        return prices

    try:
        from foreign_service import _fetch_foreign_via_price_board

        board = _fetch_foreign_via_price_board(symbols)
        for symbol, row in board.items():
            price = row.get("price")
            if price:
                prices[symbol] = float(price)
    except Exception as e:
        print(f"[real_portfolio] price_board fail: {str(e)[:120]}")

    missing = [s for s, p in prices.items() if not p]
    if missing:
        try:
            from market_service import fetch_realtime_price

            for symbol in missing:
                data = fetch_realtime_price(symbol) or {}
                if data.get("price"):
                    prices[symbol] = float(data["price"])
        except Exception as e:
            print(f"[real_portfolio] realtime fail: {str(e)[:120]}")

    return prices


def get_real_portfolio(include_prices: bool = True) -> Dict[str, Any]:
    """
    Danh mục thật hiện tại + lãi/lỗ.

    `unrealized_pnl` là lãi/lỗ nếu bán ngay hôm nay, ĐÃ trừ phí bán và thuế ước
    tính — nếu không trừ, con số luôn đẹp hơn thực tế khoảng 0,25%.
    """
    transactions = storage.list_real_transactions()
    if not transactions:
        return {
            "empty": True,
            "reason": "Chưa có giao dịch nào. Tải file sao kê hoặc nhập tay để bắt đầu.",
            "positions": [],
            "summary": {},
        }

    built = _build_positions(transactions)
    positions = built["positions"]
    symbols = [p["symbol"] for p in positions]
    prices = _fetch_prices(symbols) if include_prices else {s: None for s in symbols}

    from broker_import_service import DEFAULT_BROKER_FEE_RATE, SELL_TAX_RATE

    exit_cost_rate = DEFAULT_BROKER_FEE_RATE + SELL_TAX_RATE

    market_value = 0.0
    unrealized = 0.0
    priced_cost = 0.0
    for position in positions:
        price = prices.get(position["symbol"])
        position["price"] = price
        position["price_available"] = price is not None
        if price is None:
            position["market_value"] = None
            position["unrealized_pnl"] = None
            position["unrealized_pct"] = None
            continue

        gross_value = position["shares"] * price
        exit_costs = gross_value * exit_cost_rate
        net_value = gross_value - exit_costs
        pnl = net_value - position["cost_basis"]

        position["market_value"] = round(gross_value, 0)
        position["exit_costs"] = round(exit_costs, 0)
        position["unrealized_pnl"] = round(pnl, 0)
        position["unrealized_pct"] = round(pnl / position["cost_basis"] * 100, 2) if position["cost_basis"] else None
        market_value += gross_value
        unrealized += pnl
        priced_cost += position["cost_basis"]

    for position in positions:
        value = position.get("market_value")
        position["weight_pct"] = round(value / market_value * 100, 2) if value and market_value else None

    realized_pnl = sum(r["pnl"] for r in built["realized"].values())
    realized_by_symbol = [
        {
            "symbol": symbol,
            "pnl": round(data["pnl"], 0),
            "proceeds": round(data["proceeds"], 0),
            "cost": round(data["cost"], 0),
            "sold_qty": data["sold_qty"],
            "pnl_pct": round(data["pnl"] / data["cost"] * 100, 2) if data["cost"] else None,
        }
        for symbol, data in built["realized"].items()
    ]
    realized_by_symbol.sort(key=lambda r: r["pnl"], reverse=True)

    warnings = list(built["warnings"])
    heaviest = max(
        (p for p in positions if p.get("weight_pct") is not None),
        key=lambda p: p["weight_pct"],
        default=None,
    )
    if heaviest and heaviest["weight_pct"] > CONCENTRATION_WARN_PCT:
        warnings.append(
            f"{heaviest['symbol']} chiếm {heaviest['weight_pct']:.1f}% danh mục "
            f"(ngưỡng cảnh báo {CONCENTRATION_WARN_PCT:.0f}%)."
        )

    total_cost = sum(p["cost_basis"] for p in positions)
    return {
        "empty": False,
        "positions": positions,
        "realized_by_symbol": realized_by_symbol,
        "warnings": warnings,
        "summary": {
            "position_count": len(positions),
            "total_cost": round(total_cost, 0),
            "market_value": round(market_value, 0) if market_value else 0,
            "unrealized_pnl": round(unrealized, 0),
            # Chỉ tính % trên phần có giá — trộn mã không lấy được giá vào sẽ
            # làm mẫu số phình lên và % thấp giả tạo.
            "unrealized_pct": round(unrealized / priced_cost * 100, 2) if priced_cost else None,
            "realized_pnl": round(realized_pnl, 0),
            "net_pnl": round(realized_pnl + unrealized, 0),
            "total_fees": built["total_fees"],
            "total_taxes": built["total_taxes"],
            "cost_drag": round(built["total_fees"] + built["total_taxes"], 0),
            "txn_count": len(transactions),
            "first_txn": transactions[0]["date"],
            "last_txn": transactions[-1]["date"],
            "priced_positions": sum(1 for p in positions if p["price_available"]),
        },
    }


def get_trading_stats(year: Optional[int] = None) -> Dict[str, Any]:
    """
    Thống kê hành vi giao dịch: số vòng mua-bán, tỷ lệ thắng, và chi phí đã trả.

    Mục đích không phải khoe số đẹp mà để trả lời một câu rất cụ thể: phí + thuế
    đang ăn bao nhiêu phần lợi nhuận. Giao dịch càng nhiều, con số này càng đáng
    sợ, và đó là thứ người dùng kiểm soát được ngay — khác với hướng đi thị trường.
    """
    transactions = storage.list_real_transactions()
    if year is not None:
        transactions = [t for t in transactions if t["date"][:4] == str(year)]
    if not transactions:
        return {"empty": True, "reason": "Chưa có giao dịch trong kỳ."}

    built = _build_positions(transactions)
    realized = built["realized"]

    wins = [r for r in realized.values() if r["pnl"] > 0]
    losses = [r for r in realized.values() if r["pnl"] < 0]
    realized_pnl = sum(r["pnl"] for r in realized.values())
    costs = built["total_fees"] + built["total_taxes"]

    buy_count = sum(1 for t in transactions if t["side"] == "BUY")
    sell_count = sum(1 for t in transactions if t["side"] == "SELL")
    turnover = sum(t["quantity"] * t["price"] for t in transactions)

    return {
        "empty": False,
        "year": year,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "turnover": round(turnover, 0),
        "symbols_closed": len(realized),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(len(wins) / len(realized) * 100, 1) if realized else None,
        "realized_pnl": round(realized_pnl, 0),
        "total_fees": built["total_fees"],
        "total_taxes": built["total_taxes"],
        "total_costs": round(costs, 0),
        # Phí+thuế so với lãi gộp: >100% nghĩa là giao dịch nhiều đến mức chi phí
        # nuốt sạch phần lãi kiếm được.
        "cost_vs_gross_profit_pct": (
            round(costs / (realized_pnl + costs) * 100, 1) if (realized_pnl + costs) > 0 else None
        ),
        "cost_vs_turnover_pct": round(costs / turnover * 100, 3) if turnover else None,
    }


def format_real_portfolio_for_prompt(data: Dict[str, Any]) -> str:
    """Tóm tắt danh mục thật để đưa vào prompt AI đánh giá rủi ro."""
    if data.get("empty"):
        return "Danh mục thật: chưa có dữ liệu."

    summary = data["summary"]
    lines = [
        f"Danh mục thật ({summary['position_count']} mã, "
        f"{summary['txn_count']} giao dịch từ {summary['first_txn']} đến {summary['last_txn']}):",
        f"- Giá vốn: {summary['total_cost']:,.0f} đ | Giá thị trường: {summary['market_value']:,.0f} đ",
        f"- Lãi/lỗ chưa thực hiện: {summary['unrealized_pnl']:,.0f} đ",
        f"- Lãi/lỗ đã thực hiện: {summary['realized_pnl']:,.0f} đ",
        f"- Phí + thuế đã trả: {summary['cost_drag']:,.0f} đ",
        "Chi tiết vị thế:",
    ]
    for position in data["positions"][:15]:
        weight = f"{position['weight_pct']:.1f}%" if position.get("weight_pct") else "N/A"
        pnl = f"{position['unrealized_pnl']:,.0f} đ" if position.get("unrealized_pnl") is not None else "N/A"
        lines.append(
            f"- {position['symbol']}: {position['shares']:,} CP, giá vốn "
            f"{position['avg_cost']:,.0f} đ, tỷ trọng {weight}, lãi/lỗ {pnl}"
        )
    for warning in data.get("warnings", []):
        lines.append(f"- CẢNH BÁO: {warning}")
    return "\n".join(lines)
