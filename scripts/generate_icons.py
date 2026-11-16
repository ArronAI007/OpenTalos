"""Generate deterministic desktop icons from the OpenTalos vector mark."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "assets" / "icon"


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=220,
        fill="#4f46e5",
    )
    outer = [
        (512, 196),
        (764, 342),
        (764, 682),
        (512, 828),
        (260, 682),
        (260, 342),
    ]
    inner = [
        (512, 260),
        (714, 377),
        (714, 647),
        (512, 764),
        (310, 647),
        (310, 377),
    ]
    draw.polygon(outer, fill="#ffffff")
    draw.polygon(inner, fill="#4f46e5")
    spark = [
        (512, 350),
        (576, 448),
        (674, 512),
        (576, 576),
        (512, 674),
        (448, 576),
        (350, 512),
        (448, 448),
    ]
    draw.polygon(spark, fill="#ffffff")

    png = ICON_DIR / "opentalos.png"
    image.save(png)
    image.save(
        ICON_DIR / "opentalos.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    try:
        image.save(ICON_DIR / "opentalos.icns", format="ICNS")
    except OSError:
        # PyInstaller accepts the PNG on non-macOS hosts; release CI regenerates
        # the ICNS on macOS with the platform's icon encoder.
        pass


if __name__ == "__main__":
    main()
