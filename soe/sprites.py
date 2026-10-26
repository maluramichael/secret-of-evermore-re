"""Graphics + real palette -> colored PNGs.

Combines the *uncompressed* 4bpp tiles (the raw-readable font/HUD/sprite bank
around 0x40000) with a verified palette from `soe.palettes` (character palette
block bank $10, see there). This yields colored, sensible-looking tiles
without guessing.

Compressed sprites (custom SoE LZ codec) are handled by
`colored_compressed_sprite` via `soe.lz.decompress_sprite`. It skips cleanly
if that module is unavailable.
"""
from __future__ import annotations
from pathlib import Path

from .rom import Rom
from . import palettes

# Uncompressed 4bpp graphics in the 0x40000 bank. 0x41900+ holds structured
# 4bpp tiles (verified: with the Boy palette they show recognizable figure parts).
GFX_4BPP = (0x41900, 0x41F00)
_COLS = 16
_SCALE = 4


def colorize_4bpp(rom: Rom, start: int, end: int, pal, cols: int = _COLS,
                  transparent0: bool = True):
    """Colorize 4bpp tiles [start,end) with an RGB palette (16 colors)."""
    from PIL import Image
    n = (end - start) // 32
    rows = (n + cols - 1) // cols
    img = Image.new("RGBA", (cols * 8, rows * 8), (0, 0, 0, 0))
    px = img.load()
    for t in range(n):
        tile = rom.decode_4bpp(rom.read(start + t * 32, 32))
        ox, oy = (t % cols) * 8, (t // cols) * 8
        for y in range(8):
            for x in range(8):
                v = tile[y][x]
                if transparent0 and v == 0:
                    continue
                r, g, b = pal[v]
                px[ox + x, oy + y] = (r, g, b, 255)
    if _SCALE != 1:
        img = img.resize((img.width * _SCALE, img.height * _SCALE), Image.NEAREST)
    return img, n


def colorize_1bpp_font(rom: Rom, key: str, fg, bg=None, cols: int = _COLS):
    """Colorize a 1bpp font with a real palette color as foreground."""
    from PIL import Image
    start, end = rom.span(key)
    n = (end - start) // 8
    rows = (n + cols - 1) // cols
    base = (*bg, 255) if bg else (0, 0, 0, 0)
    img = Image.new("RGBA", (cols * 8, rows * 8), base)
    px = img.load()
    for t in range(n):
        tile = rom.decode_1bpp(rom.read(start + t * 8, 8))
        ox, oy = (t % cols) * 8, (t // cols) * 8
        for y in range(8):
            for x in range(8):
                if tile[y][x]:
                    px[ox + x, oy + y] = (*fg, 255)
    if _SCALE != 1:
        img = img.resize((img.width * _SCALE, img.height * _SCALE), Image.NEAREST)
    return img, n


def colored_compressed_sprite(rom: Rom, pal, start=None, blocks=160):
    """Decompress + colorize compressed sprites.

    Walks the verified EU sprite chain from `SPRITE_CHAIN_START_EU`
    (soe.lz, sprite zero-word RLE) and colors it with `pal`. If soe.lz is
    missing or anything fails, None is returned (clean skip).
    """
    try:
        from .lz import decompress_sprite, SPRITE_CHAIN_START_EU
    except Exception:
        return None
    if start is None:
        start = SPRITE_CHAIN_START_EU
    try:
        raw = bytearray()
        off = start
        for _ in range(blocks):
            data, consumed = decompress_sprite(rom.data, off)
            if not consumed:
                break
            raw += data
            off += consumed
    except Exception:
        return None
    if len(raw) < 32:
        return None
    from PIL import Image
    n = len(raw) // 32
    cols = _COLS
    rows = (n + cols - 1) // cols
    img = Image.new("RGBA", (cols * 8, rows * 8), (0, 0, 0, 0))
    px = img.load()
    for t in range(n):
        tile = rom.decode_4bpp(bytes(raw[t * 32:t * 32 + 32]))
        ox, oy = (t % cols) * 8, (t // cols) * 8
        for y in range(8):
            for x in range(8):
                v = tile[y][x]
                if v:
                    px[ox + x, oy + y] = (*pal[v], 255)
    return img.resize((img.width * _SCALE, img.height * _SCALE), Image.NEAREST)


def extract(rom: Rom, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    chars = palettes.character_palettes(rom)
    summary = {}

    # Color the 4bpp bank with several real character palettes (Boy, Dog, +2 enemies)
    start, end = GFX_4BPP
    for c in chars[:4]:
        pal = c["colors"]
        img, n = colorize_4bpp(rom, start, end, pal)
        fn = f"gfx_{start:06X}_char{c['char_index']:02d}_pal{c['offset']:06X}.png"
        img.save(out / fn)
        summary[fn] = n

    # 1bpp fonts with a real palette color (light tone from the Boy palette)
    boy = chars[0]["colors"]
    fg = max(boy, key=lambda rgb: sum(rgb))          # brightest real color
    for key in ("font_main", "font_small"):
        img, n = colorize_1bpp_font(rom, key, fg=fg, bg=(24, 24, 48))
        img.save(out / f"{key}_colored.png")
        summary[f"{key}_colored"] = n

    # Compressed sprites: only if soe.lz exists
    demo = colored_compressed_sprite(rom, boy)   # verified EU sprite chain (soe.lz)
    summary["compressed_lz"] = "ready" if demo is not None else "waiting for soe.lz"
    if demo is not None:
        demo.save(out / "sprite_compressed_demo.png")

    return summary


if __name__ == "__main__":
    rom = Rom("Secret of Evermore (Europe).sfc")
    res = extract(rom, Path("assets/gfx/colored"))
    print(res)
