"""
"Tin này thị trường đã biết chưa?" — trả lời bằng phép tính, không hỏi AI.

Đây là phần có giá trị nhất với nhà đầu tư mới. Người mới đọc tin tốt rồi mua
ngay, mà không kiểm tra xem giá đã chạy trước tin bao nhiêu. Rất nhiều lần tin
tốt là lúc người biết trước THOÁT hàng.

Cách đo (thuần số liệu, kiểm chứng được):
- Giá đã đi bao nhiêu % kể từ ngày tin xuất hiện, và trong 5 phiên trước đó.
- Khối lượng những phiên quanh tin gấp mấy lần mức bình thường TRƯỚC đó.

Quy tắc kết luận cố ý đơn giản và công khai, để người dùng tự kiểm được — khác
với một con số "confidence 87%" mà không ai truy được nguồn.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

# Giá chạy quá ngưỡng này trước/quanh tin thì coi như thị trường đã biết.
_STRONG_MOVE_PCT = 5.0
_MILD_MOVE_PCT = 2.0
# Khối lượng gấp bằng này lần mức nền trước đó = có dòng tiền bất thường.
_HIGH_VOLUME_RATIO = 1.5


def _to_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "").split(".")[0])
    except ValueError:
        return None


def analyze_reaction(
    df: pd.DataFrame,
    news_date: Optional[str] = None,
    lookback_days: int = 5,
) -> Dict[str, Any]:
    """
    Đo phản ứng giá quanh mốc `news_date` (mặc định: phiên gần nhất).

    df: khung dữ liệu từ stock_service.fetch_stock_data (có Close, Volume).
    """
    if df is None or df.empty or len(df) < 6:
        return {"available": False, "reason": "Không đủ dữ liệu giá để đánh giá."}

    closes = df["Close"].dropna()
    volumes = df["Volume"].dropna()
    if len(closes) < 6:
        return {"available": False, "reason": "Không đủ phiên giao dịch."}

    # Vị trí phiên tương ứng ngày tin; không có tin thì lấy phiên cuối.
    anchor_idx = len(closes) - 1
    parsed = _to_date(news_date)
    if parsed is not None:
        target = pd.Timestamp(parsed)
        index = closes.index
        if getattr(index, "tz", None) is not None:
            target = target.tz_localize(index.tz)
        earlier = [i for i, ts in enumerate(index) if ts <= target]
        if earlier:
            anchor_idx = earlier[-1]

    latest = float(closes.iloc[-1])
    anchor_price = float(closes.iloc[anchor_idx])

    # Giá chạy TRƯỚC tin: dấu hiệu có người biết trước.
    before_idx = max(0, anchor_idx - lookback_days)
    price_before = float(closes.iloc[before_idx])
    run_up_pct = round((anchor_price - price_before) / price_before * 100, 2) if price_before else None

    # Giá chạy SAU tin (0 nếu tin là của phiên gần nhất).
    since_news_pct = round((latest - anchor_price) / anchor_price * 100, 2) if anchor_price else None

    # Mốc so sánh phải là khối lượng TRƯỚC cửa sổ quanh tin. Nếu lấy trung bình
    # 20 phiên gần nhất (bao gồm chính mấy phiên đột biến cần đo) thì đúng cái
    # đột biến đó tự kéo mốc so sánh lên và tỷ lệ bị pha loãng — một cú tăng gấp
    # đôi có thể chỉ hiện ra thành 1,1 lần.
    baseline_slice = volumes.iloc[max(0, before_idx - 20) : before_idx]
    if len(baseline_slice) < 3:
        # Chuỗi quá ngắn để có mốc riêng; đành dùng phần ngoài cửa sổ.
        baseline_slice = volumes.drop(volumes.index[before_idx : anchor_idx + 1])
    avg_volume = float(baseline_slice.mean()) if len(baseline_slice) >= 3 else None
    window_volume = float(volumes.iloc[before_idx : anchor_idx + 1].mean()) if avg_volume else None
    volume_ratio = round(window_volume / avg_volume, 2) if avg_volume and window_volume else None

    total_move = abs(run_up_pct or 0) + abs(since_news_pct or 0)
    heavy_volume = bool(volume_ratio and volume_ratio >= _HIGH_VOLUME_RATIO)

    if total_move >= _STRONG_MOVE_PCT and heavy_volume:
        verdict = "likely_priced_in"
        summary = (
            f"Giá đã biến động {total_move:.1f}% quanh thời điểm tin, khối lượng gấp "
            f"{volume_ratio:.1f} lần trung bình 20 phiên — thị trường nhiều khả năng đã biết và phản ánh."
        )
    elif total_move >= _MILD_MOVE_PCT:
        verdict = "partly_priced_in"
        summary = (
            f"Giá đã biến động {total_move:.1f}% quanh thời điểm tin"
            + (f", khối lượng gấp {volume_ratio:.1f} lần mức nền" if volume_ratio else "")
            + " — có thể đã phản ánh một phần."
        )
    else:
        verdict = "little_reaction"
        summary = (
            f"Giá gần như chưa phản ứng (biến động {total_move:.1f}%)"
            + (f", khối lượng {volume_ratio:.1f} lần mức nền" if volume_ratio else "")
            + " — hoặc thị trường chưa chú ý, hoặc tin không quan trọng như tiêu đề."
        )

    return {
        "available": True,
        "verdict": verdict,
        "summary": summary,
        "anchor_date": str(closes.index[anchor_idx].date()),
        "latest_price": round(latest, 0),
        "run_up_pct": run_up_pct,
        "since_news_pct": since_news_pct,
        "volume_ratio": volume_ratio,
        "heavy_volume": heavy_volume,
    }


def format_reaction_for_prompt(symbol: str, reaction: Dict[str, Any]) -> str:
    """Đưa kết quả đo vào prompt. AI phải dùng đúng số này, không được tự tính lại."""
    if not reaction.get("available"):
        return f"{symbol}: chưa đo được phản ứng giá ({reaction.get('reason', '')})."

    lines = [
        f"{symbol} — phản ứng giá đo được (số liệu thật, KHÔNG được thay đổi):",
        f"- Giá hiện tại: {reaction['latest_price']:,.0f} đ",
        f"- Biến động 5 phiên trước mốc tin: {reaction['run_up_pct']:+.2f}%"
        if reaction.get("run_up_pct") is not None
        else "- Biến động trước tin: N/A",
        f"- Biến động từ mốc tin tới nay: {reaction['since_news_pct']:+.2f}%"
        if reaction.get("since_news_pct") is not None
        else "- Biến động sau tin: N/A",
    ]
    if reaction.get("volume_ratio"):
        lines.append(f"- Khối lượng quanh tin: {reaction['volume_ratio']:.2f}× mức bình thường trước đó")
    lines.append(f"- Kết luận máy tính: {reaction['summary']}")
    return "\n".join(lines)
