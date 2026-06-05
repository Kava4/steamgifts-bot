"""Generate assets/icon.ico for the app window, tray, and exe."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icon.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]

BG = (20, 20, 20, 255)
BOX = (46, 46, 46, 255)
RIBBON = (120, 120, 120, 255)
ACCENT = (82, 82, 82, 255)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(1, size // 10)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=max(2, size // 5),
        fill=BG,
    )

    box_left = size * 0.22
    box_top = size * 0.30
    box_right = size * 0.78
    box_bottom = size * 0.78
    draw.rounded_rectangle(
        [box_left, box_top, box_right, box_bottom],
        radius=max(1, size // 16),
        fill=BOX,
    )

    ribbon_w = max(1, size // 10)
    cx = size // 2
    draw.rectangle(
        [cx - ribbon_w // 2, box_top, cx + ribbon_w // 2, box_bottom],
        fill=RIBBON,
    )
    bow_h = size * 0.14
    draw.rectangle(
        [box_left, box_top - bow_h * 0.2, box_right, box_top + bow_h],
        fill=ACCENT,
    )
    draw.ellipse(
        [cx - bow_h, box_top - bow_h * 0.8, cx, box_top + bow_h * 0.4],
        fill=RIBBON,
    )
    draw.ellipse(
        [cx, box_top - bow_h * 0.8, cx + bow_h, box_top + bow_h * 0.4],
        fill=RIBBON,
    )

    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [draw_icon(size) for size in SIZES]
    images[0].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[1:],
    )
    print(f"Created {OUT}")


if __name__ == "__main__":
    main()
