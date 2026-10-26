"""Graphics tiles -> PNG.

NOTE (verified): most SoE graphics are **compressed** (custom 16-mode RLE/LZ
codec, per-tile flag). The codecs live in soe.lz, this module does not use
them. Raw (uncompressed) and therefore cleanly extractable are mainly the
font banks (see soe.fonts). Here: a 4bpp survey sheet of the low-entropy
graphics bank as a rough guide, plus a note about the compression. Needs
Pillow.
"""
from __future__ import annotations
from pathlib import Path

from .rom import Rom

_COLS = 16
_SCALE = 2
_SURVEY = (0x40000, 0x42000)     # font/window bank, visible raw


def _render_4bpp(rom: Rom, start: int, end: int):
    from PIL import Image
    n_tiles = (end - start) // 32
    rows = (n_tiles + _COLS - 1) // _COLS
    img = Image.new("L", (_COLS * 8, rows * 8), 0)
    px = img.load()
    for t in range(n_tiles):
        tile = rom.decode_4bpp(rom.read(start + t * 32, 32))
        ox, oy = (t % _COLS) * 8, (t // _COLS) * 8
        for y in range(8):
            for x in range(8):
                px[ox + x, oy + y] = tile[y][x] * 17   # 0..15 -> 0..255
    if _SCALE != 1:
        img = img.resize((img.width * _SCALE, img.height * _SCALE), Image.NEAREST)
    return img, n_tiles


def extract(rom: Rom, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    start, end = _SURVEY
    img, n = _render_4bpp(rom, start, end)
    img.save(out / f"survey_4bpp_{start:06X}_{end:06X}.png")
    (out / "README.md").write_text(
        "# Graphics\n\n"
        "Most SoE graphics are compressed (custom 16-mode RLE/LZ codec, "
        "see `soe.lz`). The font banks can be extracted raw (see "
        "`assets/fonts/`). The survey PNG is a 4bpp grayscale dump of "
        f"bank 0x{start:X}-0x{end:X} as a rough guide, not a finished tileset.\n\n"
        "Decoded sprites and backgrounds come from the sprites and maps domains.\n")
    return {"survey_tiles": n, "note": "most graphics are compressed, see soe.lz"}
