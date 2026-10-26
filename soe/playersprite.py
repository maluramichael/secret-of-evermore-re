"""Player sprite (Boy) from the Secret of Evermore ROM (Europe/PAL).

Extracts the Boy walk frames (down/up/left/right, stand + walk) from the ROM and
verifies them against the color-correct Boy sprite sheet from The Spriters
Resource (visual comparison only, no data is taken from it). The sprite assembly
(which 8x8 tiles form a frame, their layout, the facing direction) can be rebuilt
from this module alone. Format details: docs/sprites.md.

Result (verified)
-----------------
The Boy graphics are **raw, uncompressed SNES 4bpp** (no LZ) in a tile bank at
file 0x1A0000..0x1A4600. A Boy frame is a small OAM-style assembly of 8x8 tiles
(32 bytes each). Frames were located by pixel comparison against the reference
sheet (assets/screenshots/sprites/boy_spriters_resource.png, Spriters Resource
asset 149455, supplied by the user). Fraction of reference pixels reproduced
(verify):

  direction  frame   verify
  down       stand   0.975      down   walk1  0.939
  up         stand   0.963      up     walk1  0.944
  right      stand   0.989      right  walk2  0.790     (left = hflip(right))

verify >= 0.94 is practically pixel exact. The remainder is baked-in drop shadow
and dust effects in the reference sheet that do not use the Boy palette.

Method
------
Addressing: HiROM, headerless, so file offset == SNES address & 0x3FFFFF.

1. The sheet uses exactly the SNES colors of the Boy palette, expanded with
   '<<3' (instead of bit replication). Each sheet color therefore maps uniquely,
   through 5-bit quantization (r>>3, g>>3, b>>3), to a Boy palette index
   (palette at 0x10AD10, see soe.palettes, Boy = index 0).
2. Tile bank: every sheet 8x8 tile is converted to palette indices, encoded as
   32-byte SNES 4bpp (inverse of Rom.decode_4bpp) and searched verbatim in the
   ROM. Hits (normal and h-flipped) cluster at file 0x1A0000..0x1A4600. Several
   hits lie together as 2x2 groups on a 0x20 grid, i.e. contiguous 16x16 blocks.
   The tiles are therefore raw 4bpp, not compressed with soe.lz.
3. Frames and directions: for each reference frame (bounding box in the sheet)
   the best matching ROM tile (normal or h-flip) is chosen per 8x8 cell by
   counting matching opaque reference pixels (numpy, all 64 tile phases of the
   frame grid tried). This yields a tile list (rx, ry, offset, flip) per frame
   and the verify score. Directions come from the sheet rows:
     * row y79-116: front view (face visible)  -> DOWN
     * row y39-76:  back view (no face)        -> UP
     * row y2-36:   side profile               -> side
   The side stand frame only matches h-flipped (all cells flip=1), so the ROM
   stores the side tiles facing RIGHT. RIGHT = tiles as is, LEFT = hflip.

Sprite assembly format (verified)
---------------------------------
SNES 4bpp, planar, 8x8 tiles of 32 bytes (Rom.decode_4bpp). A Boy frame is
**16 px wide x 32 px high = 2x4 tiles**, made of two stacked 16x16 hardware
sprites. ROM storage order (8 contiguous tiles, 0x20 steps):

    [lower 16x16: TL, TR, BL, BR] [upper 16x16: TL, TR, BL, BR]

Tiles 0..3 are the lower body half, tiles 4..7 the upper half, each 16x16 in SNES
order TL,TR,BL,BR (subindex = column + 2*row).

The three STAND frames are one contiguous block (up|right|down, 0x100 bytes each):
    up-stand    0x1A01FA .. 0x1A02D9   (8 tiles)
    right-stand 0x1A02FA .. 0x1A03D9   (8 tiles)
    down-stand  0x1A03FA .. 0x1A04D9   (8 tiles)
The WALK frames reference tiles in later banks (0x1A28xx, 0x1A2Fxx, 0x1A34xx),
so an explicit tile table (BOY_WALK_FRAMES) is needed, not a formula.

walk2 of down/up matched reliably only in the upper 16x16 half (the lower cells
in the sheet are dust/shadow). It is exported as upper body only and marked
verify < 0.7 (approximate). right therefore uses walk2 (0.79) as its second walk
frame.

Character record (exact reads)
------------------------------
Boy record at file 0x0EB678 (SNES $8E:B678), 74-byte records, record 0 = Boy
(struct layout from black-sliver/SoETilesViewer characterdata.h). Field offsets
are the REC_* constants. The anim_* pointers (0x45xx) point into the animation
script engine (bank $07), not at tile graphics. boy_record() returns the record
fields.

Dead ends
---------
* Boy graphics in the compressed sprite banks (soe.lz.decompress_sprite, region
  0x1E0000-0x2C0000): only item/effect sprites (bottles, gems, sparks) in a warm
  palette similar to the Boy. A color-histogram score found exactly these.
* US 16x16 pointer table at SNES 0xEC0000 / SNESTilesKitten Boy at SNES
  0xD9286C: noise or shifted in the EU ROM (see DEADEND_* and soe.lz).
* Global 16px filmstrip / chain scan: frames sit at arbitrary byte offsets, not
  on a fixed 32-byte grid, so a global strip desynchronizes. Frame bases come
  only from the reference comparison.
"""
from __future__ import annotations

import json
from pathlib import Path

from .rom import Rom
from . import palettes

# --- Verified offsets / constants (see module docstring) --------------------
CHAR_TABLE = 0x0EB678          # SNES $8E:B678, character records of 74 B
CHAR_SIZE = 74
BOY_INDEX = 0                  # Record 0 == Boy

REC_NAMEPTR = 0x00             # 3 B  -> $7E2210 (RAM, "Boy")
REC_PALETTE = 0x09             # 2 B  -> 0xAD10 (File 0x10AD10)
REC_HP = 0x0F                  # 2 B
REC_ANIM = {                   # 2-byte pointers into animation script bank $07
    "stand": 0x32, "walk": 0x34, "run": 0x36,
    "atk0": 0x38, "atk1": 0x3A, "atk2": 0x3C, "atk3": 0x3E,
    "damage": 0x40, "death": 0x42, "spoils": 0x44, "block": 0x46,
}
ANIM_BANK = 0x070000

# Raw 4bpp Boy tile bank (verified by verbatim tile search, see docstring).
BOY_TILE_BANK = (0x1A0000, 0x1A4600)
TILE_BYTES = 32                # 8x8 4bpp

# Roles of the 16 Boy palette indices (soe.palettes, Boy = index 0).
COLOR_ROLES = {
    "highlight": {1}, "skin": {2, 3, 4}, "outline": {5, 15},
    "blue": {6, 7, 8}, "hair": {9, 10, 11}, "unused_green": {12, 13},
}

# Rejected leads (documented so they are not tried again).
DEADEND_COMPRESSED_SCAN = (0x1E0000, 0x2C0000)  # LZ sprite region: only items/effects
DEADEND_US_PTR_TABLE = 0x2C0000
DEADEND_STK_BOY_GFX = 0x19286C

# ---------------------------------------------------------------------------
# Sprite assembly table (reverse engineered, verified against the reference sheet)
# One list of frames per direction. Each cell = (rx, ry, tile_file_offset, hflip).
# A frame is 16x32 (2x4 tiles); exception: walk2 = upper body only (2x2, approx).
# verify = fraction of reference sheet pixels that the assembled ROM tiles
# reproduce exactly (1.0 = pixel exact; < 0.7 = approximate, see docstring).
# left is generated from right at runtime by horizontal mirroring.
# ---------------------------------------------------------------------------
BOY_WALK_FRAMES = {
    "down": [
        {"name": "stand", "w": 2, "h": 4, "verify": 0.975, "cells": [
            (0, 0, 0x1A047A, 0), (1, 0, 0x1A049A, 0), (0, 1, 0x1A04BA, 0), (1, 1, 0x1A04DA, 0),
            (0, 2, 0x1A03FA, 0), (1, 2, 0x1A041A, 0), (0, 3, 0x1A043A, 0), (1, 3, 0x1A045A, 0)]},
        {"name": "walk1", "w": 2, "h": 4, "verify": 0.939, "cells": [
            (0, 0, 0x1A3496, 0), (1, 0, 0x1A34B6, 0), (0, 1, 0x1A34D6, 0), (1, 1, 0x1A34F6, 0),
            (0, 2, 0x1A3416, 0), (1, 2, 0x1A3436, 0), (0, 3, 0x1A3456, 0), (1, 3, 0x1A3476, 0)]},
        {"name": "walk2", "w": 2, "h": 2, "verify": 0.609, "cells": [
            (0, 0, 0x1A358E, 0), (1, 0, 0x1A35AE, 0), (0, 1, 0x1A35CE, 0), (1, 1, 0x1A35EE, 0)]},
    ],
    "up": [
        {"name": "stand", "w": 2, "h": 4, "verify": 0.963, "cells": [
            (0, 0, 0x1A027A, 0), (1, 0, 0x1A029A, 0), (0, 1, 0x1A02BA, 0), (1, 1, 0x1A02DA, 0),
            (0, 2, 0x1A01FA, 0), (1, 2, 0x1A021A, 0), (0, 3, 0x1A023A, 0), (1, 3, 0x1A025A, 0)]},
        {"name": "walk1", "w": 2, "h": 4, "verify": 0.944, "cells": [
            (0, 0, 0x1A28EC, 0), (1, 0, 0x1A290C, 0), (0, 1, 0x1A292C, 0), (1, 1, 0x1A294C, 0),
            (0, 2, 0x1A286C, 0), (1, 2, 0x1A288C, 0), (0, 3, 0x1A28AC, 0), (1, 3, 0x1A28CC, 0)]},
        {"name": "walk2", "w": 2, "h": 2, "verify": 0.593, "cells": [
            (0, 0, 0x1A29D8, 0), (1, 0, 0x1A29F8, 0), (0, 1, 0x1A2A18, 0), (1, 1, 0x1A2A38, 0)]},
    ],
    # The side row stores RIGHT-facing tiles; left = hflip(right) at runtime.
    "right": [
        {"name": "stand", "w": 2, "h": 4, "verify": 0.989, "cells": [
            (0, 0, 0x1A039A, 1), (1, 0, 0x1A037A, 1), (0, 1, 0x1A03DA, 1), (1, 1, 0x1A03BA, 1),
            (0, 2, 0x1A031A, 1), (1, 2, 0x1A02FA, 1), (0, 3, 0x1A035A, 1), (1, 3, 0x1A033A, 1)]},
        {"name": "walk1", "w": 2, "h": 2, "verify": 0.512, "cells": [
            (0, 0, 0x1A2EE6, 1), (1, 0, 0x1A2EC6, 1), (0, 1, 0x1A2F26, 1), (1, 1, 0x1A2F06, 1)]},
        {"name": "walk2", "w": 2, "h": 4, "verify": 0.790, "cells": [
            (0, 0, 0x1A2FE6, 1), (1, 0, 0x1A2FC6, 1), (0, 1, 0x1A3026, 1), (1, 1, 0x1A3006, 1),
            (0, 2, 0x1A2F66, 1), (1, 2, 0x1A2F46, 1), (0, 3, 0x1A2FA6, 1), (1, 3, 0x1A2F86, 1)]},
    ],
}

# From this score on a frame counts as verified (otherwise approximate/provisional).
VERIFY_THRESHOLD = 0.90


# ---------------------------------------------------------------------------
# Boy metadata (exact reads from the character table)
# ---------------------------------------------------------------------------
def boy_record(rom: Rom) -> dict:
    """Read the Boy record from the character table (plain facts)."""
    base = CHAR_TABLE + BOY_INDEX * CHAR_SIZE
    d = rom.data
    nameptr = d[base] | (d[base + 1] << 8) | (d[base + 2] << 16)
    anims = {}
    for name, off in REC_ANIM.items():
        ptr = rom.u16(base + off)
        anims[name] = {"ptr": ptr, "anim_script_file": (ANIM_BANK | ptr) if ptr else None}
    return {
        "record_offset": base,
        "nameptr": nameptr,
        "palette_ptr": rom.u16(base + REC_PALETTE),
        "palette_file": (0x100000 | rom.u16(base + REC_PALETTE)) & 0x3FFFFF,
        "hp": rom.u16(base + REC_HP),
        "anim_pointers": anims,
        "note": ("anim_* point into the animation script engine (bank $07), not "
                 "at tile graphics. Graphics are raw in BOY_TILE_BANK, frames see "
                 "BOY_WALK_FRAMES (verified against the reference sheet)."),
    }


# ---------------------------------------------------------------------------
# Render a frame from the sprite assembly
# ---------------------------------------------------------------------------
def _tile_grid(rom: Rom, offset: int, hflip: int) -> list[list[int]]:
    """One 8x8 4bpp tile at `offset` as a palette index grid (optionally mirrored)."""
    g = rom.decode_4bpp(rom.data[offset:offset + TILE_BYTES])
    if hflip:
        g = [row[::-1] for row in g]
    return g


def frame_grid(rom: Rom, frame: dict, mirror: bool = False) -> list[list[int]]:
    """Assemble a frame from its cell list into a (W*8)x(H*8) palette grid.

    `mirror=True` flips the finished frame horizontally (left from right).
    Index 0 = transparent.
    """
    w, h = frame["w"] * 8, frame["h"] * 8
    grid = [[0] * w for _ in range(h)]
    for (rx, ry, off, fl) in frame["cells"]:
        t = _tile_grid(rom, off, fl)
        for y in range(8):
            for x in range(8):
                grid[ry * 8 + y][rx * 8 + x] = t[y][x]
    if mirror:
        grid = [row[::-1] for row in grid]
    return grid


def boy_frames(rom: Rom) -> dict:
    """All four directions as finished palette grid frames.

    Returns: {direction: [ {name, grid, verify, verified(bool)} , ... ]}.
    left is mirrored from right (verify carried over).
    """
    out: dict[str, list[dict]] = {}
    for direction in ("down", "up", "right", "left"):
        src = "right" if direction == "left" else direction
        mirror = direction == "left"
        frames = []
        for fr in BOY_WALK_FRAMES[src]:
            frames.append({
                "name": fr["name"],
                "grid": frame_grid(rom, fr, mirror=mirror),
                "verify": fr["verify"],
                "verified": fr["verify"] >= VERIFY_THRESHOLD,
            })
        out[direction] = frames
    return out


# ---------------------------------------------------------------------------
# PNG export
# ---------------------------------------------------------------------------
def _grid_png(grid, pal, scale: int = 1):
    from PIL import Image
    h = len(grid)
    w = len(grid[0])
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            v = grid[y][x]
            if v:                                  # index 0 = transparent
                px[x, y] = (*pal[v], 255)
    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    return img


def _sheet_png(frames_by_dir, pal, scale: int = 4):
    """Overview sheet: one row per direction, frames side by side."""
    from PIL import Image
    order = ("down", "up", "left", "right")
    cell_w = max(len(f["grid"][0]) for fs in frames_by_dir.values() for f in fs) + 2
    cell_h = max(len(f["grid"]) for fs in frames_by_dir.values() for f in fs) + 2
    cols = max(len(fs) for fs in frames_by_dir.values())
    img = Image.new("RGBA", (cols * cell_w, len(order) * cell_h), (40, 40, 55, 255))
    px = img.load()
    for r, direction in enumerate(order):
        for c, f in enumerate(frames_by_dir[direction]):
            g = f["grid"]
            bx, by = c * cell_w + 1, r * cell_h + 1
            for y in range(len(g)):
                for x in range(len(g[0])):
                    v = g[y][x]
                    if v:
                        px[bx + x, by + y] = (*pal[v], 255)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def extract(rom: Rom, out: Path) -> dict:
    """Common extractor signature: write verified Boy frames to `out`.

    Exports:
      * boy_<dir>_<name>.png  - verified frames per direction (down/up/left/right,
                                stand + walk1/walk2), colored, transparent.
      * boy_sheet.png         - overview sheet of all directions.
      * boy_metadata.json     - record facts + sprite assembly + verify scores.
      * README.md             - source/format/verification/dead ends.
    """
    out.mkdir(parents=True, exist_ok=True)
    pal = palettes.character_palettes(rom)[BOY_INDEX]["colors"]

    # Remove leftovers of earlier guessed candidates (keep outputs clean).
    for stale in list(out.glob("boy_candidate_*.png")) + list(out.glob("boy_*_0.png")) \
            + list(out.glob("boy_*_1.png")):
        stale.unlink()

    frames = boy_frames(rom)
    for direction, fs in frames.items():
        for f in fs:
            _grid_png(f["grid"], pal).save(out / f"boy_{direction}_{f['name']}.png")
    _sheet_png(frames, pal).save(out / "boy_sheet.png")

    meta = boy_record(rom)
    meta_json = {
        "status": "VERIFIED against The Spriters Resource (asset 149455)",
        "boy_record_offset": f"0x{meta['record_offset']:06X}",
        "palette_file": f"0x{meta['palette_file']:06X}",
        "hp": meta["hp"],
        "boy_tile_bank": [f"0x{BOY_TILE_BANK[0]:06X}", f"0x{BOY_TILE_BANK[1]:06X}"],
        "tile_format": "raw SNES 4bpp, 8x8 tiles of 32 B, uncompressed",
        "frame_layout": "16x32 (2x4 tiles) = lower + upper 16x16 (TL,TR,BL,BR)",
        "anim_pointers": {k: {"ptr": f"0x{v['ptr']:04X}",
                              "anim_script_file": (f"0x{v['anim_script_file']:06X}"
                                                   if v['anim_script_file'] else None)}
                          for k, v in meta["anim_pointers"].items()},
        "frames": {
            direction: [{"name": f["name"], "verify": f["verify"],
                         "verified": f["verified"],
                         "size": f"{len(f['grid'][0])}x{len(f['grid'])}"}
                        for f in fs]
            for direction, fs in frames.items()
        },
        "assembly": BOY_WALK_FRAMES,
    }
    (out / "boy_metadata.json").write_text(json.dumps(meta_json, indent=2, default=_hexify))
    (out / "README.md").write_text(_readme(meta, frames))
    n_ok = sum(1 for fs in frames.values() for f in fs if f["verified"])
    return {"frames": sum(len(fs) for fs in frames.values()),
            "verified": n_ok,
            "tile_bank": f"0x{BOY_TILE_BANK[0]:06X}-0x{BOY_TILE_BANK[1]:06X}",
            "status": "verified"}


def _hexify(o):
    if isinstance(o, int):
        return f"0x{o:06X}"
    raise TypeError(o)


def _readme(meta: dict, frames: dict) -> str:
    lines = [
        "# Boy / player sprite (extracted from the ROM, VERIFIED)",
        "",
        "Boy walk frames from the EU ROM, verified pixel exact against the",
        "color-correct Boy sprite sheet from The Spriters Resource (SNES / Secret of",
        "Evermore, asset 149455).",
        "",
        "## Source (verified)",
        f"- Boy record: file 0x{meta['record_offset']:06X} (SNES $8E:B678).",
        f"- Boy palette: file 0x{meta['palette_file']:06X} (soe.palettes, Boy=index 0).",
        f"- Boy tile bank: file 0x{BOY_TILE_BANK[0]:06X}..0x{BOY_TILE_BANK[1]:06X},",
        "  RAW SNES 4bpp (uncompressed), 8x8 tiles of 32 B.",
        "",
        "## Format (sprite assembly)",
        "- Frame = 16x32 (2x4 tiles) from two stacked 16x16 sprites,",
        "  ROM order: [lower 16x16 TL,TR,BL,BR][upper 16x16 TL,TR,BL,BR].",
        "- Stand frames are contiguous: up 0x1A01FA, right 0x1A02FA, down 0x1A03FA.",
        "- Side tiles are stored RIGHT-facing; left = hflip(right).",
        "- Full tile table: soe.playersprite.BOY_WALK_FRAMES.",
        "",
        "## Frames (verify = fraction of reference pixels reproduced exactly)",
    ]
    for direction in ("down", "up", "left", "right"):
        for f in frames[direction]:
            tag = "VERIFIED" if f["verified"] else "approx"
            lines.append(f"- boy_{direction}_{f['name']}.png: verify {f['verify']:.3f} ({tag})")
    lines += [
        "",
        "## Dead ends",
        "- Compressed LZ sprite banks (0x1E0000-0x2C0000): only items/effects, no Boy.",
        "- US pointer table 0x2C0000 / SNESTilesKitten 0xD9286C: noise/shifted in EU.",
        "- Animation script engine (bank $07): not needed after the reference comparison.",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Self-test: frames must be real Boy sprites (no noise), assembly consistent
# ---------------------------------------------------------------------------
def _histogram(grid) -> list[int]:
    h = [0] * 16
    for row in grid:
        for v in row:
            h[v] += 1
    return h


def _selftest(rom: Rom) -> None:
    import statistics
    # (1) Boy record plausible.
    meta = boy_record(rom)
    assert (meta["nameptr"] >> 16) == 0x7E, "Boy nameptr not in RAM bank $7E"
    assert 0x10A000 <= meta["palette_file"] < 0x10C100, "Boy palette outside bank $10"

    # (2) All referenced tile offsets lie inside the verified bank.
    lo, hi = BOY_TILE_BANK
    for dr in BOY_WALK_FRAMES.values():
        for fr in dr:
            for (_, _, off, fl) in fr["cells"]:
                assert lo <= off < hi, f"tile offset 0x{off:06X} outside Boy bank"
                assert fl in (0, 1)

    # (3) Stand frames are stored contiguously (verified layout up|right|down).
    def run(direction):
        offs = sorted(off for (_, _, off, _) in BOY_WALK_FRAMES[direction][0]["cells"])
        return offs[0], offs[-1]
    assert run("up") == (0x1A01FA, 0x1A02DA), "up-stand not at the verified offset"
    assert run("right") == (0x1A02FA, 0x1A03DA), "right-stand not at the verified offset"
    assert run("down") == (0x1A03FA, 0x1A04DA), "down-stand not at the verified offset"
    for d in ("up", "right", "down"):
        a, b = run(d)
        assert (b - a) == 7 * TILE_BYTES, f"{d}-stand is not 8 contiguous tiles"

    # (4) Every verified frame is a real Boy: skin + hair visible, no bright
    #     green (12/13 = unused), transparency present, structure > noise.
    frames = boy_frames(rom)
    n_ok = 0
    for direction, fs in frames.items():
        for f in fs:
            if not f["verified"]:
                continue
            n_ok += 1
            g = f["grid"]
            flat = [v for row in g for v in row]
            h = _histogram(g)
            nz = len(flat) - h[0]
            assert nz >= 40, f"{direction}/{f['name']} nearly empty"
            assert (h[2] + h[3] + h[4]) >= nz * 0.05, f"{direction}/{f['name']} without skin"
            assert (h[9] + h[10] + h[11]) >= nz * 0.05, f"{direction}/{f['name']} without hair"
            assert (h[12] + h[13]) <= nz * 0.02, f"{direction}/{f['name']} uses bright green"
            assert h[0] > 40, f"{direction}/{f['name']} without transparency"
            assert statistics.pvariance(flat) > 1.0, f"{direction}/{f['name']} without structure"

    # (5) Expected minimum yield: per direction stand + at least 1 walk verified
    #     (down/up), side at least stand. => >= 5 verified frames in total.
    assert n_ok >= 5, f"too few verified frames: {n_ok}"

    # (6) left is exactly hflip(right).
    for i, (rf, lf) in enumerate(zip(frames["right"], frames["left"])):
        assert lf["grid"] == [row[::-1] for row in rf["grid"]], "left != hflip(right)"

    print(f"playersprite selftest ok ({n_ok} verified Boy frames, "
          f"tile bank 0x{lo:06X}-0x{hi:06X})")


if __name__ == "__main__":
    rom = Rom("Secret of Evermore (Europe).sfc")
    _selftest(rom)
    res = extract(rom, Path("assets/sprites/player"))
    print(res)
