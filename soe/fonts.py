"""Fonts -> PNG.

1bpp SNES font (8 bytes per 8x8 tile). Europe offsets: main font 0x40003
(corrected by alignment search, the Datacrystal US value 0x40002 is wrong
here), small font 0x40C84. Needs Pillow.
"""
from __future__ import annotations
from pathlib import Path

from .rom import Rom

_COLS = 16          # glyphs per row in the sheet
_SCALE = 2          # upscale factor for viewable PNGs


def _render_sheet(rom: Rom, key: str):
    from PIL import Image
    start, end = rom.span(key)
    n_tiles = (end - start) // 8
    rows = (n_tiles + _COLS - 1) // _COLS
    img = Image.new("RGBA", (_COLS * 8, rows * 8), (0, 0, 0, 0))
    px = img.load()
    for t in range(n_tiles):
        tile = rom.decode_1bpp(rom.read(start + t * 8, 8))
        ox, oy = (t % _COLS) * 8, (t // _COLS) * 8
        for y in range(8):
            for x in range(8):
                if tile[y][x]:
                    px[ox + x, oy + y] = (255, 255, 255, 255)
    if _SCALE != 1:
        img = img.resize((img.width * _SCALE, img.height * _SCALE), Image.NEAREST)
    return img, n_tiles


def extract(rom: Rom, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for key, fname in (("font_main", "font_main.png"), ("font_small", "font_small.png")):
        img, n = _render_sheet(rom, key)
        img.save(out / fname)
        summary[key] = n
    return summary
