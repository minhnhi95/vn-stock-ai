"""
Sinh icon PNG cho PWA từ cùng một thiết kế với public/icon.svg.

Vì sao cần PNG dù đã có SVG: tiêu chí "installable" của Chrome/Android đòi ít
nhất một icon PNG >= 192px, và icon maskable phải chừa safe zone (nội dung nằm
trong 80% giữa) nếu không launcher bo tròn sẽ cắt mất.

Chạy lại khi đổi thiết kế:
    pip install pillow
    python frontend/scripts/generate_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

BG_TOP = (11, 18, 38)
BG_BOTTOM = (4, 8, 21)
ACCENT = (6, 182, 212)
UP = (34, 197, 94)
DOWN = (244, 63, 94)

# Toạ độ thiết kế trên canvas 512 — khớp với public/icon.svg.
DESIGN = 512
TREND = [(84, 348), (196, 244), (288, 300), (428, 140)]
CANDLES = [
    # (x tâm, đỉnh râu, đáy râu, đỉnh thân, đáy thân, màu)
    (152, 196, 392, 232, 360, UP),
    (256, 236, 420, 276, 388, DOWN),
    (360, 112, 348, 148, 308, UP),
]
CANDLE_HALF_WIDTH = 26
WICK_HALF_WIDTH = 8


def _rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render(size: int, scale: float = 1.0) -> Image.Image:
    """
    scale < 1 co phần hình vẽ vào giữa để chừa safe zone cho icon maskable;
    nền vẫn phủ kín toàn khung.
    """
    # Vẽ ở độ phân giải gấp 4 rồi thu nhỏ — cách khử răng cưa rẻ nhất với Pillow.
    ss = size * 4
    img = Image.new("RGB", (ss, ss), BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    # Nền gradient dọc.
    for y in range(ss):
        t = y / max(ss - 1, 1)
        draw.line(
            [(0, y), (ss, y)],
            fill=tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )

    # Hình vẽ không nằm chính giữa canvas thiết kế, nên khi thu nhỏ phải dịch
    # theo tâm bounding box thật — nếu không icon maskable sẽ lệch lên góc.
    xs = [x for x, _ in TREND] + [c[0] - CANDLE_HALF_WIDTH for c in CANDLES] + [
        c[0] + CANDLE_HALF_WIDTH for c in CANDLES
    ]
    ys = [y for _, y in TREND] + [c[1] for c in CANDLES] + [c[2] for c in CANDLES]
    bbox_cx = (min(xs) + max(xs)) / 2
    bbox_cy = (min(ys) + max(ys)) / 2

    unit = ss * scale / DESIGN  # 1 đơn vị thiết kế bằng bấy nhiêu pixel

    def px_x(value: float) -> float:
        return ss / 2 + (value - bbox_cx) * unit

    def px_y(value: float) -> float:
        return ss / 2 + (value - bbox_cy) * unit

    draw.line(
        [(px_x(x), px_y(y)) for x, y in TREND],
        fill=ACCENT,
        width=max(1, round(22 * unit)),
        joint="curve",
    )

    for cx, wick_top, wick_bottom, body_top, body_bottom, color in CANDLES:
        _rounded_rect(
            draw,
            [
                px_x(cx - WICK_HALF_WIDTH),
                px_y(wick_top),
                px_x(cx + WICK_HALF_WIDTH),
                px_y(wick_bottom),
            ],
            radius=WICK_HALF_WIDTH * unit,
            fill=color,
        )
        _rounded_rect(
            draw,
            [
                px_x(cx - CANDLE_HALF_WIDTH),
                px_y(body_top),
                px_x(cx + CANDLE_HALF_WIDTH),
                px_y(body_bottom),
            ],
            radius=12 * unit,
            fill=color,
        )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    outputs = {
        "icon-192.png": render(192),
        "icon-512.png": render(512),
        # Maskable: nội dung co còn 72% để launcher bo tròn không cắt vào nến.
        "icon-maskable-512.png": render(512, scale=0.72),
    }
    for name, image in outputs.items():
        path = PUBLIC_DIR / name
        image.save(path, format="PNG", optimize=True)
        print(f"{path.name}: {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
