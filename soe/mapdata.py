"""Map collision and metadata from the real format -> JSON manifest.

Goal: for a map, derive the walkable area, the trigger zones and the dimensions
the way the game itself holds them, instead of guessing from image brightness.

## Where collision comes from (verified, Europe ROM, map 56)

The bank-$90 map loader stores one 8-byte record per 16x16 cell at `$7F0000`
(WRAM dump offset 0x10000): four SNES words.

    word0 = BG1 large tile (foreground)
    word1 = BG2 large tile (ground)
    word2 = attribute/collision field  (not a drawn tile)
    word3 = 0

The **low nibble of word2 holds the blocking bits** of the cell:

    (word2 & 0x0F) == 0x0  ->  fully walkable   (paths, clearings)
    (word2 & 0x0F) == 0xF  ->  fully solid      (foliage, rock, void edge)
    in between (0x1..0xE)  ->  edge/transition cells (partially blocked)

Evidence (map 56, "Prehistoria - South jungle / Start", 83x91 = 7553 cells):
the distribution of the low nibble is {0: 1393, 15: 5709, rest 1..14: 451}.
Overlaid on the rendered map PNG, nibble 0 covers exactly the brown jungle paths
and clearings, nibble 15 the dense foliage and the dark void edge. This is the
field the real loader uses for collision, not an image threshold.

For 16x16 tile collision this module uses: **solid := (word2 & 0x0F) != 0**
(conservative; the partial nibbles are the foliage/path edges and block
direction-dependent in game, sub-cell resolution is an open item, see below).

## Trigger zones / exits

They come from the map header (`soe.maps.read_map`): rectangular zones
[x1 y1 x2 y2] plus a script pointer. The actual warp destination is in the
script bytecode (`soe.script`); the zones are taken over unchanged together
with the script pointer so that a later step can resolve the destinations.

## Reproducibility

Collision needs the WRAM dump from `soe.snescall` (the same dump the map PNG is
rendered from). `collision_grid(mapid)` calls `snescall.load_map_state` when
needed (boots the ROM headless in Mesen2). The triggers come purely from ROM
bytes.

Open items:
- Map the sub-cell/direction semantics of the partial nibbles (0x1..0xE) exactly.
- Resolve warp destinations from the script (CHANGE_MAP 0x22 / TELEPORT_BOTH 0x20).
- NPC/object placement from the script (LOAD_NPC 0x3C / LOAD_NPC_B 0xBA) with
  resolved coordinates and sprites.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import snescall
from .maps import read_map
from .rom import Rom

_ROOT = Path(__file__).resolve().parent.parent
_ROM_PATH = _ROOT / "Secret of Evermore (Europe).sfc"

# WRAM layout (see soe.snescall): 7F0000 -> dump offset 0x10000.
_WRAM_TILEINFO = 0x10000
_DIM_W = 0x08EE
_DIM_H = 0x08F0


def _u16(buf: bytes, off: int) -> int:
    return buf[off] | buf[off + 1] << 8


def collision_grid(mapid: int) -> tuple[list[list[int]], list[list[int]], int, int]:
    """(solid, attr, w, h) from the snescall WRAM dump.

    solid[y][x] = 1 if (word2 & 0x0F) != 0, else 0.
    attr[y][x]  = the full word2 (for later sub-cell analysis).
    """
    snescall.load_map_state(mapid)  # idempotent: reuses an existing dump
    wram = (snescall.map_dir(mapid) / "wram.bin").read_bytes()
    w = _u16(wram, _DIM_W)
    h = _u16(wram, _DIM_H)
    if not (0 < w <= 128 and 0 < h <= 128):
        raise RuntimeError(f"map {mapid}: implausible dims {w}x{h}")
    solid = [[0] * w for _ in range(h)]
    attr = [[0] * w for _ in range(h)]
    for cell in range(w * h):
        ptr = _u16(wram, _WRAM_TILEINFO + 2 * cell)
        word2 = _u16(wram, _WRAM_TILEINFO + ptr + 4)
        x, y = cell % w, cell // w
        attr[y][x] = word2
        solid[y][x] = 1 if (word2 & 0x0F) != 0 else 0
    return solid, attr, w, h


def _nibble_histogram(attr: list[list[int]]) -> dict[int, int]:
    hist: dict[int, int] = {}
    for row in attr:
        for v in row:
            n = v & 0x0F
            hist[n] = hist.get(n, 0) + 1
    return dict(sorted(hist.items()))


def build(mapid: int) -> dict:
    """Full manifest for a map: dimensions, collision grid, trigger zones."""
    solid, attr, w, h = collision_grid(mapid)
    rom = Rom(str(_ROM_PATH))
    hdr = read_map(rom, mapid)
    walkable = sum(row.count(0) for row in solid)
    return {
        "index": mapid,
        "name": hdr.get("name_by_debug_index"),
        "width": w,
        "height": h,
        "tile": 16,
        "collision": {
            "source": "snescall word2 low-nibble (verified map 56)",
            "rule": "solid := (word2 & 0x0F) != 0",
            "walkable_cells": walkable,
            "solid_cells": w * h - walkable,
            "nibble_histogram": _nibble_histogram(attr),
            "grid": solid,  # solid[y][x] in {0,1}
        },
        "event_triggers": hdr["event_triggers"],
        "b_triggers": hdr["b_triggers"],
        "exits_note": hdr["exits_note"],
    }


def overlay_png(mapid: int, out: Path | None = None) -> Path:
    """Debug overlay: walkable green, solid red, over the rendered map PNG."""
    from PIL import Image

    solid, _attr, w, h = collision_grid(mapid)
    src = _ROOT / "assets" / "maps" / "snescall" / f"map_{mapid:04d}.png"
    base = Image.open(src).convert("RGB")
    ov = base.copy()
    px = ov.load()
    TILE = 16
    for y in range(h):
        for x in range(w):
            tint = (255, 0, 0) if solid[y][x] else (0, 255, 0)
            for yy in range(2, TILE, 5):
                for xx in range(2, TILE, 5):
                    px0, py0 = x * TILE + xx, y * TILE + yy
                    r, g, b = px[px0, py0]
                    px[px0, py0] = ((r + tint[0]) // 2, (g + tint[1]) // 2, (b + tint[2]) // 2)
    out = out or (_ROOT / "assets" / "maps" / "data" / f"map_{mapid:04d}_collision.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    ov.save(out)
    return out


def extract(rom: Rom, out: Path) -> dict:
    """Standard soe extract hook. Writes the manifest for the first jungle map (56).

    Only map 56, because collision needs the (slow) emulator dump; pass other
    ids on the command line. Returns a summary for the caller.
    """
    data_dir = out / "maps" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    mapid = 56
    manifest = build(mapid)
    path = data_dir / f"map_{mapid:04d}.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "map": mapid,
        "grid": f"{manifest['width']}x{manifest['height']}",
        "walkable_cells": manifest["collision"]["walkable_cells"],
        "solid_cells": manifest["collision"]["solid_cells"],
        "json": str(path),
    }


if __name__ == "__main__":
    import sys

    ids = [int(a) for a in sys.argv[1:]] or [56]
    for mid in ids:
        m = build(mid)
        outp = _ROOT / "assets" / "maps" / "data" / f"map_{mid:04d}.json"
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(m, indent=2, ensure_ascii=False))
        ov = overlay_png(mid)
        print(f"map {mid}: {m['width']}x{m['height']}  "
              f"walkable={m['collision']['walkable_cells']} "
              f"solid={m['collision']['solid_cells']}  "
              f"nibbles={m['collision']['nibble_histogram']}")
        print(f"  -> {outp}")
        print(f"  -> {ov}")
