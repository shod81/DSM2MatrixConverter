"""Generate the Dsm2Empirum application icon (assets/icon.ico).

Renders the master SVG (large variant) plus a simplified low-res variant for
16/24 px via PySide6's QSvgRenderer and packs everything into a multi-size
Windows .ico: a PNG-compressed 256 px frame and classic 32bpp BMP frames for
the smaller sizes (maximum shell/installer compatibility).

Usage:
    python tools/make_icon.py

Outputs:
    assets/icon.svg      master SVG (large variant)
    assets/icon.ico      multi-size Windows icon
    assets/icon_256.png  256 px preview (docs/screenshots)
    scratch/icon_preview.png  size grid on light/dark background (not shipped)
"""

from __future__ import annotations

import io
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]
SMALL_VARIANT_SIZES = {16, 24}


def _large_svg() -> str:
    """Detailed variant: outlined source block, arrow, validated target block."""
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0ea5e9"/>
      <stop offset="0.55" stop-color="#0284c7"/>
      <stop offset="1" stop-color="#075985"/>
    </linearGradient>
    <linearGradient id="green" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4ade80"/>
      <stop offset="1" stop-color="#16a34a"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.20"/>
      <stop offset="0.45" stop-color="#ffffff" stop-opacity="0.04"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
  </defs>

  <rect x="4" y="4" width="248" height="248" rx="56" fill="url(#bg)"/>
  <rect x="4" y="4" width="248" height="248" rx="56" fill="url(#sheen)"/>
  <rect x="10" y="10" width="236" height="236" rx="50" fill="none"
        stroke="#bae6fd" stroke-opacity="0.5" stroke-width="3"/>

  <!-- source package (Ivanti DSM): outlined -->
  <rect x="28" y="82" width="72" height="92" rx="16" fill="#ffffff"
        fill-opacity="0.14" stroke="#e0f2fe" stroke-width="9"/>
  <line x1="46" y1="114" x2="82" y2="114" stroke="#e0f2fe"
        stroke-opacity="0.9" stroke-width="7" stroke-linecap="round"/>
  <line x1="46" y1="132" x2="74" y2="132" stroke="#e0f2fe"
        stroke-opacity="0.55" stroke-width="7" stroke-linecap="round"/>
  <line x1="46" y1="150" x2="78" y2="150" stroke="#e0f2fe"
        stroke-opacity="0.55" stroke-width="7" stroke-linecap="round"/>

  <!-- conversion arrow -->
  <path d="M106 125 h36 v-17 l36 28 -36 28 v-17 h-36 z"
        transform="translate(0,-8)" fill="#f8fafc"/>

  <!-- target package (Matrix42 Empirum): filled, validated -->
  <rect x="156" y="82" width="72" height="92" rx="16" fill="url(#green)"/>
  <path d="M172 128 l14 14 26 -28" fill="none" stroke="#f0fdf4"
        stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def _small_svg() -> str:
    """Simplified variant: solid blocks with a bold dark arrow (16/24 px)."""
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0ea5e9"/>
      <stop offset="0.55" stop-color="#0284c7"/>
      <stop offset="1" stop-color="#075985"/>
    </linearGradient>
  </defs>
  <rect x="4" y="4" width="248" height="248" rx="56" fill="url(#bg)"/>
  <rect x="20" y="72" width="92" height="112" rx="18" fill="#e0f2fe"/>
  <rect x="144" y="72" width="92" height="112" rx="18" fill="#22c55e"/>
  <path d="M64 112 h56 v-24 l72 40 -72 40 v-24 h-56 z" fill="#0c4a6e"/>
</svg>
"""


def render_svg_to_image(svg: str, size: int) -> Image.Image:
    """Render an SVG string to a square RGBA PIL image at native size."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        msg = f"QImage save failed for size {size}"
        raise RuntimeError(msg)
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def _bmp_frame(img: Image.Image) -> bytes:
    """Encode an RGBA image as a 32bpp BITMAPINFOHEADER + XOR + AND-mask frame."""
    width, height = img.size
    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, width * height * 4, 0, 0, 0, 0
    )
    bgra = img.convert("RGBA").tobytes("raw", "BGRA")
    row = width * 4
    xor = b"".join(bgra[y * row : (y + 1) * row] for y in range(height - 1, -1, -1))
    mask_row = ((width + 31) // 32) * 4
    and_mask = bytes(mask_row * height)
    return header + xor + and_mask


def build_ico(images: dict[int, Image.Image]) -> bytes:
    """Pack size -> RGBA image mappings into an .ico container."""
    ordered = [size for size in ICO_SIZES if size in images]
    entries: list[tuple[int, int, int, bytes]] = []
    for size in ordered:
        data = (
            _png_bytes(images[size]) if size == 256 else _bmp_frame(images[size])
        )
        entries.append((size, size, 32, data))

    offset = 6 + 16 * len(entries)
    directory = b""
    payload = b""
    for width, height, bitcount, data in entries:
        directory += struct.pack(
            "<BBBBHHII",
            width % 256,
            height % 256,
            0,
            0,
            1,
            bitcount,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(entries)) + directory + payload


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def build_preview(images: dict[int, Image.Image], out: Path) -> None:
    """Compose a size grid on light and dark backgrounds for visual review."""
    sizes = sorted((size for size in ICO_SIZES if size in images), reverse=True)
    pad, cell = 24, 300
    width = pad + sum(min(size * 2, 256) + pad for size in sizes)
    height = cell * 2 + pad * 3
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    dark = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    canvas.paste(dark, (0, cell + pad))
    x = pad
    for size in sizes:
        target = min(size * 2, 256)
        icon = images[size].resize((target, target), Image.Resampling.LANCZOS)
        canvas.paste(icon, (x, pad), icon)
        dark_bg_y = cell + pad + (cell - target) // 2
        canvas.paste(icon, (x, dark_bg_y), icon)
        x += target + pad
    canvas.save(out)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - required by Qt paint system
    assets = REPO_ROOT / "assets"
    assets.mkdir(exist_ok=True)

    large = _large_svg()
    (assets / "icon.svg").write_text(large, encoding="utf-8")

    images: dict[int, Image.Image] = {}
    for size in ICO_SIZES:
        svg = _small_svg() if size in SMALL_VARIANT_SIZES else large
        images[size] = render_svg_to_image(svg, size)

    ico_path = assets / "icon.ico"
    ico_path.write_bytes(build_ico(images))
    images[256].save(assets / "icon_256.png")

    scratch = REPO_ROOT / "scratch"
    scratch.mkdir(exist_ok=True)
    build_preview(images, scratch / "icon_preview.png")

    print(f"Wrote {ico_path} ({ico_path.stat().st_size} bytes)")
    print(f"Wrote {assets / 'icon.svg'}")
    print(f"Wrote {assets / 'icon_256.png'}")
    print(f"Wrote {scratch / 'icon_preview.png'}")


if __name__ == "__main__":
    main()
