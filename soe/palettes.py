"""Real SoE palettes from the ROM (not guessed heuristically).

Evidence:
---------
The character/sprite data table is at SNES $8E:B678 (HiROM, file offset
0x0EB678). The layout is verified against SoETilesViewer (characterdata.h:
`BASE_ADDR=0x8eB678`, `SIZE=74`, 16-bit field `palette` at +0x09). Each entry
carries a 16-bit **palette pointer** at +0x09. All 25 valid entries (name
pointer = Boy/Dog $7E22xx or text $C5xxxx) resolve with bank $10 to valid SNES
palettes (file = (0x100000 | ptr) & 0x3FFFFF): a brute force over all banks
0x00..0x3F yields bank 0x10 as the unique hit (94/140 clean blocks; all 25
real entries are bit15-clean, Boy@0x10AD10 = real skin tones + blue clothing).

=> Palette data block: bank $10, file offset 0x10xxxx.
   Range referenced by the character table: 0x10AD10 .. 0x10C050.
   Palettes sit on a 32-byte grid (16 colors * 2 bytes).

SNES palettes: 15-bit BGR, bit15 always 0. `Rom.snes_color`/`Rom.palette`
provide the low-level decoders; this module only holds the verified offsets
and the mapping.
"""
from __future__ import annotations
import json
from pathlib import Path

from .rom import Rom

# --- Verified offsets (see module docstring) --------------------------------
PALETTE_BANK = 0x100000          # SNES bank $10 -> file offset (HiROM: addr & 0x3FFFFF)
CHAR_TABLE = 0x0EB678            # SNES $8E:B678, characterdata.h BASE_ADDR
CHAR_SIZE = 74                   # characterdata.h SIZE
CHAR_PALETTE_OFF = 0x09         # 16-bit palette pointer in the character record
CHAR_COUNT = 25                  # contiguous run of valid entries

# Contiguous palette data block referenced by the character table.
# Start = smallest, end = largest referenced pointer (+ one palette).
PAL_TABLE_START = 0x10AD10
PAL_TABLE_END = 0x10C070         # exclusive (0xC050 + 32)
PAL_STRIDE = 32                  # 16 colors * 2 bytes

_MAP = 0x3FFFFF                  # HiROM file mapping


def _file_off(snes_or_ptr: int, bank: int = PALETTE_BANK) -> int:
    """16-bit palette pointer -> file offset in bank $10 (HiROM)."""
    return (bank | (snes_or_ptr & 0xFFFF)) & _MAP


def read_palette_ptr(rom: Rom, ptr16: int) -> list[tuple[int, int, int]]:
    """16 RGB colors at a native 16-bit palette pointer (bank $10)."""
    return rom.palette(_file_off(ptr16), 16)


def read_palette(rom: Rom, index: int) -> list[tuple[int, int, int]]:
    """Palette #index from the data block (32-byte grid from PAL_TABLE_START)."""
    off = PAL_TABLE_START + index * PAL_STRIDE
    if not (PAL_TABLE_START <= off < PAL_TABLE_END):
        raise IndexError(f"palette index {index} out of table range")
    return rom.palette(off, 16)


def character_palettes(rom: Rom) -> list[dict]:
    """Verified mapping character -> palette (Boy=0, Dog=1, then enemies/NPCs)."""
    out = []
    for i in range(CHAR_COUNT):
        rec = CHAR_TABLE + i * CHAR_SIZE
        ptr = rom.u16(rec + CHAR_PALETTE_OFF)
        off = _file_off(ptr)
        out.append({
            "char_index": i,
            "ptr": ptr,
            "offset": off,
            "colors": rom.palette(off, 16),
        })
    return out


def all_palettes(rom: Rom) -> list[dict]:
    """All palettes of the referenced data block (32-byte grid).

    Marks which offsets the character table references directly.
    """
    referenced = {p["offset"] for p in character_palettes(rom)}
    out = []
    idx = 0
    off = PAL_TABLE_START
    while off < PAL_TABLE_END:
        out.append({
            "index": idx,
            "offset": off,
            "referenced": off in referenced,
            "colors": rom.palette(off, 16),
        })
        idx += 1
        off += PAL_STRIDE
    return out


# --- Export ------------------------------------------------------------------
def _stripe_png(colors, path: Path, sw: int = 16, h: int = 16) -> None:
    from PIL import Image
    img = Image.new("RGB", (sw * 16, h))
    px = img.load()
    for i, c in enumerate(colors):
        for x in range(sw):
            for y in range(h):
                px[i * sw + x, y] = c
    img.save(path)


def extract(rom: Rom, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    pals = all_palettes(rom)
    meta = []
    for p in pals:
        name = f"pal_{p['index']:03d}"
        _stripe_png(p["colors"], out / f"{name}.png")
        meta.append({
            "name": name,
            "index": p["index"],
            "offset": f"0x{p['offset']:06X}",
            "referenced_by_char_table": p["referenced"],
            "rgb": [list(c) for c in p["colors"]],
        })
    chars = character_palettes(rom)
    (out / "palettes.json").write_text(json.dumps({
        "source": "character table SNES $8E:B678 (+0x09 palette-ptr), data block bank $10",
        "palette_table_start": f"0x{PAL_TABLE_START:06X}",
        "palette_table_end": f"0x{PAL_TABLE_END:06X}",
        "stride": PAL_STRIDE,
        "count": len(pals),
        "character_map": [
            {"char_index": c["char_index"], "ptr": f"0x{c['ptr']:04X}",
             "offset": f"0x{c['offset']:06X}", "rgb": [list(x) for x in c["colors"]]}
            for c in chars
        ],
        "palettes": meta,
    }, indent=2))
    return {"palettes": len(pals), "char_palettes": len(chars),
            "table": f"0x{PAL_TABLE_START:06X}-0x{PAL_TABLE_END:06X}"}


def _selftest(rom: Rom) -> None:
    chars = character_palettes(rom)
    assert len(chars) == CHAR_COUNT
    for c in chars:
        # every real palette: bit15 of all color words is 0 (SNES invariant)
        for j in range(16):
            assert (rom.u16(c["offset"] + j * 2) & 0x8000) == 0
    # Boy (char0) has real skin tones: at least one light, warm color
    boy = chars[0]["colors"]
    assert any(r > 200 and r > b for (r, g, b) in boy), "Boy palette without skin tones?"
    print("palettes selftest ok")


if __name__ == "__main__":
    rom = Rom("Secret of Evermore (Europe).sfc")
    _selftest(rom)
    res = extract(rom, Path("assets/palettes"))
    print(res)
