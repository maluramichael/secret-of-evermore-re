"""Programmatic SNES "function caller" for Secret of Evermore map extraction.

The idea in one line: do not reverse every codec by hand. Boot the ROM in Mesen2,
let the game's own map-load routine decode a map into RAM/VRAM/CGRAM, read the
finished result out and composite it into a full, clean map image. This works for
any map id without per-map codec work, because the console does the decoding.

Pipeline details: docs/maps.md (map pipeline), docs/compression.md (codecs),
docs/emulator-techniques.md (emulator tracing techniques).

================================================================================
HOW THE CALLER DRIVES THE ROM ROUTINE  (verified against the ROM + live emulator)
================================================================================

The bank-$90 map loader begins at $908F68 with `LDA $0ADB` (ROM bytes AD DB 0A),
where WRAM $0ADB holds the *current map id*. From there it, entirely on its own:

  * computes a 3-byte map-data pointer from the table at file 0x20FDE4 (stride 4),
  * reads width/height at map offset +2/+3 into $08EE/$08F0,
  * LZSS-decompresses the arrangement (metatile index per cell) to $7FC300 (op3),
  * decompresses the op7 record-pointer table (offset per cell) to $7F0000,
  * decompresses the 8-byte metatile records (4 SNES tilemap words each),
  * DMAs the 4bpp tileset to VRAM char base $4000 (inline DMA at $9091C1),
  * loads the BG palette into CGRAM (palette queue drain $90D582 -> $7E6187).

CALLING CONVENTION USED (the "pending map" pattern, hijack variant):
  Put an EXEC memory callback on $908F68. Every time the game is about to run
  the loader, overwrite $0ADB (and the high byte $0ADC = 0) with the TARGET id
  *before* the `LDA` reads it. The loader then builds the target map through its
  complete, natural code path. $0ADB is pinned on every entry, so any follow-up
  reload during the intro rebuilds the same target and the decoded structures
  stay valid until the dump. See tools/mesen/map_hijack.lua.

  Why hijack rather than a manual JSL via emu.setState: setState can set
  PC/K/SP/A/X/Y/PS/D/DBR (field casing verified: cpu.a/x/y/sp/pc/k/dbr/d/ps/
  emulationMode), so a synthetic JSL is feasible. But the loader normally runs
  mid-warp and relies on surrounding setup. Reusing the natural entry inherits
  all of that and proved robust across indoor, outdoor and town maps.

Fallback options if a map's structures ever come out wrong (none needed so far):
  (a) one savestate per map (play/warp there, saveSavestateAsync, reload + dump);
  (b) synthetic JSL to $908F68 with $0ADB pre-set and a sentinel return address
      trapped by an exec callback.

MESEN2 NOTES (all verified live):
  * emu.getState() ERRORS inside a memory callback; only emu.read/write work there.
  * Headless run: `Mesen --testRunner --noAudio <rom> <lua>`; runs until emu.stop.
  * Single-address reads only: emu.read(addr, memType) in a loop. memTypes used:
    snesWorkRam (128KB 7E+7F), snesVideoRam (64KB), snesCgRam (512B),
    snesSpriteRam (OAM 544B).
  * WRAM dump offset map: 7E0000 -> 0x00000, 7F0000 -> 0x10000, so
    7FC300 -> 0x1C300.
  * emu.takeScreenshot() returns a PNG *string* (live PPU frame, 256x224). It is
    saved as shot.png as a ground-truth cross-check of one on-screen window.
  * The Mesen2 executable is taken from the environment variable MESEN.

================================================================================
HOW THE FULL MAP IS RENDERED  (metatile composite; the reliable general path)
================================================================================

Compositing the PPU BG1/BG2 tilemaps directly yields only ONE SCREEN: the SNES BG
tilemap in VRAM holds just the scroll window, while a full SoE map is far larger.
The general, full-map result comes from the loader's decoded WRAM structures plus
the VRAM tileset, and it matches the game pixel for pixel:

  for each cell (cx,cy) in the width*height grid:
      ptr  = u16 at 7F0000 + 2*cell                  # record offset (dedup'd)
      rec  = four u16 words at 7F0000 + ptr          # word0=BG1, word1=BG2,
                                                     # word2=attr/collision, word3=0
      draw BG2 (word1) then BG1 (word0) as 16x16 LARGE TILES, BG1 on top:
          a large-tile word `vhopppcc cccccccc` -> a 16x16 block of the FOUR
          consecutive 8x8 tiles base, base+1, base+16, base+17 (char base 0x4000,
          4bpp), sharing palette bits 10..12 and flip bits 14/15; skip index 0.

This is the SNES Mode-1 BG2-then-BG1 composite. Verified visually: it renders both
indoor (Black Castle Glass Hall: five stained-glass windows, stone walls,
candelabra) and outdoor (Jungle Clearing: dirt clearing ringed by green canopy)
maps cleanly, matching the live PPU frame. An earlier reading as four arbitrary
8x8 quadrants was wrong: it produced an orange checkerboard on overworld maps,
because word1/word2 are a BG2 large tile plus an attribute field.

Palette: CGRAM 512B -> 256 RGB colors (row*16 + c). Dims from the loaded WRAM
($08EE/$08F0), which equal the ROM header +2/+3.

KNOWN LIMIT: the VRAM tileset holds only the tiles resident at dump time. For
maps whose whole tileset the loader stages up front, the composite is complete;
for maps that stream tiles as the camera moves, off-screen cells can reference
tiles not yet in VRAM and render dark/wrong. This is the same "full tileset from
ROM" gap described in docs/maps.md. render_map() reports nonblack_frac and
missing-tile stats so you can tell which maps are clean.

================================================================================
ANIMATION / OAM (documented for later, not built here)
================================================================================

To extract sprite animation the same way: load the map, then do not pin/stop. Let
it run and, each frame, read emu.memType.snesSpriteRam (OAM, 544B = 512B sprite
table + 32B high table: X/Y, tile, attrs) plus the object CGRAM palette rows
(8..15). The BG palette-cycle queue ($90D582 -> $7E6187) already animates BG
palettes in place, so re-dumping CGRAM across frames captures palette animation
with no extra call. The object/animation update routine is driven from the main
loop; no direct call is needed: stepping frames is the "caller".
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# --- paths --------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
_ROM = _ROOT / "Secret of Evermore (Europe).sfc"
_LUA = _ROOT / "tools/mesen/map_hijack.lua"
_DUMP_ROOT = _ROOT / "assets/dumps/snescall"
_ASSET_ROOT = _ROOT / "assets/maps/snescall"

# --- decoded-memory layout constants (see module docstring) -------------------
_WRAM_TILEINFO = 0x10000   # 7F0000: per-cell u16 record pointers + 8-byte records
_WRAM_ARRANGE = 0x1C300    # 7FC300: per-cell metatile index (diagnostic only)
_DIM_W = 0x08EE            # 7E08EE width in tiles
_DIM_H = 0x08F0            # 7E08F0 height in tiles
_CHAR_BASE = 0x4000        # BG1 char base (byte), 4bpp
_CELL = 16                 # metatile edge in pixels


def snes_color(v: int) -> tuple[int, int, int]:
    """15-bit BGR555 -> 8-bit RGB (5-bit expanded to 8)."""
    r, g, b = (v & 31), (v >> 5) & 31, (v >> 10) & 31
    return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2)


def _mesen_path() -> Path:
    exe = os.environ.get("MESEN")
    if not exe:
        raise RuntimeError("MESEN is not set: set it to the path of the Mesen2 executable")
    return Path(exe)


def map_dir(mapid: int) -> Path:
    return _DUMP_ROOT / f"map_{mapid:04d}"


def load_map_state(mapid: int, *, wait: int = 180, force: bool = False,
                   timeout: int = 240) -> dict:
    """Boot the ROM headless, make the game load `mapid`, dump its decoded state.

    Runs Mesen2 (executable from the MESEN environment variable) with
    tools/mesen/map_hijack.lua, which pins $0ADB to `mapid` at the loader entry
    (see module docstring). Writes wram/vram/cgram/oam bins + shot.png
    + info.txt into assets/dumps/snescall/map_XXXX/. Returns the parsed info dict
    (target, mapnum, width, height, ...). Idempotent: skips the emulator run if the
    dump already exists unless force=True.
    """
    d = map_dir(mapid)
    info_path = d / "info.txt"
    if info_path.exists() and not force:
        return _read_info(info_path)
    if not _ROM.exists():
        raise FileNotFoundError(_ROM)
    mesen = _mesen_path()
    if not mesen.exists():
        raise FileNotFoundError(mesen)
    d.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SOE_MAPID=str(mapid), SOE_OUT=str(d) + os.sep,
               SOE_WAIT=str(wait))
    proc = subprocess.run([str(mesen), "--testRunner", "--noAudio",
                           str(_ROM), str(_LUA)],
                          env=env, capture_output=True, timeout=timeout)
    if not info_path.exists():
        raise RuntimeError(f"map {mapid}: no dump produced (exit {proc.returncode}). "
                           f"stderr: {proc.stderr.decode('utf-8', 'replace')[:400]}")
    info = _read_info(info_path)
    if "TIMEOUT" in info:
        raise RuntimeError(f"map {mapid}: loader never hijacked (timeout)")
    return info


def _read_info(path: Path) -> dict:
    text = path.read_text()
    if text.startswith("TIMEOUT"):
        return {"TIMEOUT": True}
    out: dict = {}
    for tok in text.split():
        k, _, v = tok.partition("=")
        if v:
            out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


def _decode_4bpp_tile(vram: bytes, tile_no: int):
    """Decode one 8x8 4bpp tile from VRAM at char base into an 8x8 index grid."""
    off = _CHAR_BASE + tile_no * 32
    px = [[0] * 8 for _ in range(8)]
    if off + 32 > len(vram):
        return px
    for y in range(8):
        b0, b1 = vram[off + y * 2], vram[off + y * 2 + 1]
        b2, b3 = vram[off + 16 + y * 2], vram[off + 16 + y * 2 + 1]
        for x in range(8):
            s = 7 - x
            px[y][x] = (((b0 >> s) & 1) | (((b1 >> s) & 1) << 1)
                        | (((b2 >> s) & 1) << 2) | (((b3 >> s) & 1) << 3))
    return px


# Each 16x16 map cell is described by an 8-byte record of four SNES tilemap words:
#   word0 = BG1 large-tile (foreground: walls, foliage, objects, detail)
#   word1 = BG2 large-tile (background/ground fill: floor, dirt, water)
#   word2 = (semi-constant) collision/attribute field, NOT a drawn tile
#   word3 = 0 padding
# A "large-tile" word `vhopppcc cccccccc` names a 16x16 block built from FOUR
# consecutive 8x8 tiles at char base 0x4000: base, base+1, base+16, base+17
# (top-left, top-right, bottom-left, bottom-right in the tile sheet), sharing the
# word's palette (bits 10..12) and flip bits (14/15). The final cell = BG2 drawn
# first, then BG1 composited on top skipping transparent (color index 0). This is
# the SNES Mode-1 BG2-then-BG1 composite; it renders both indoor (cathedral) and
# outdoor (jungle) maps cleanly and matches the live PPU output.
_LARGE_QUADS = ((0, 0, 0), (1, 8, 0), (16, 0, 8), (17, 8, 8))  # (tile+dt, ox, oy)


def _blit_large(px, word: int, cx: int, cy: int, vram: bytes, cgcol: list,
                ntiles: int, cache: dict) -> tuple[int, int]:
    """Composite one 16x16 large-tile `word` at cell origin (cx,cy).

    Applies proper 16x16 flip (quadrant swap + per-tile flip). Skips transparent
    index 0. Returns (painted_pixels, missing_quadrants)."""
    base = word & 0x3FF
    pbase = ((word >> 10) & 7) * 16
    hf, vf = (word >> 14) & 1, (word >> 15) & 1
    painted = missing = 0
    for qx in (0, 1):
        for qy in (0, 1):
            tile = base + (qx ^ hf) + 16 * (qy ^ vf)
            if tile >= ntiles:
                missing += 1
                continue
            tpx = cache.get(tile)
            if tpx is None:
                tpx = _decode_4bpp_tile(vram, tile)
                cache[tile] = tpx
            ox, oy = cx + qx * 8, cy + qy * 8
            for y in range(8):
                row = tpx[7 - y if vf else y]
                dy = oy + y
                for x in range(8):
                    c = row[7 - x if hf else x]
                    if c:
                        px[ox + x, dy] = cgcol[pbase + c]
                        painted += 1
    return painted, missing


def render_map(mapid: int, *, scale: int = 1, save: bool = True):
    """Composite the full map for `mapid` from its dumped state and return a PIL Image.

    Loads (or reuses) the dump via load_map_state, then walks the width*height cell
    grid: each cell -> its 8-byte record -> BG2 large-tile (word1) then BG1 large-tile
    (word0) composited, tiles from the VRAM tileset (char base 0x4000), palette from
    CGRAM. Saves assets/maps/snescall/map_XXXX.png when save=True.

    The returned object carries a `.stats` attribute (dict) with grid, painted_px,
    nonblack_frac and missing_tile counts so callers can judge cleanliness.
    """
    from PIL import Image

    load_map_state(mapid)
    d = map_dir(mapid)
    wram = (d / "wram.bin").read_bytes()
    vram = (d / "vram.bin").read_bytes()
    cg = (d / "cgram.bin").read_bytes()
    w = wram[_DIM_W] | wram[_DIM_W + 1] << 8
    h = wram[_DIM_H] | wram[_DIM_H + 1] << 8
    if not (0 < w <= 128 and 0 < h <= 128):
        raise RuntimeError(f"map {mapid}: implausible dims {w}x{h}")

    cgcol = [snes_color(cg[i] | cg[i + 1] << 8) for i in range(0, min(512, len(cg)), 2)]
    ntiles = (len(vram) - _CHAR_BASE) // 32
    img = Image.new("RGB", (w * _CELL, h * _CELL), (0, 0, 0))
    px = img.load()
    cache: dict[int, list] = {}
    painted = missing = 0
    for cell in range(w * h):
        ptr = wram[_WRAM_TILEINFO + 2 * cell] | wram[_WRAM_TILEINFO + 2 * cell + 1] << 8
        r0off = _WRAM_TILEINFO + ptr
        bg1 = wram[r0off] | wram[r0off + 1] << 8
        bg2 = wram[r0off + 2] | wram[r0off + 3] << 8
        cx, cy = (cell % w) * _CELL, (cell // w) * _CELL
        for layer in (bg2, bg1):  # BG2 first (ground), BG1 on top (foreground)
            p, m = _blit_large(px, layer, cx, cy, vram, cgcol, ntiles, cache)
            painted += p
            missing += m

    if scale != 1:
        img = img.resize((w * _CELL * scale, h * _CELL * scale), Image.NEAREST)
    nonblack = sum(1 for p in img.getdata() if p != (0, 0, 0))
    img.stats = {  # type: ignore[attr-defined]
        "mapid": mapid, "grid": f"{w}x{h}", "painted_px": painted,
        "missing_tile_quadrants": missing,
        "nonblack_frac": round(nonblack / (img.width * img.height), 3),
    }
    if save:
        _ASSET_ROOT.mkdir(parents=True, exist_ok=True)
        out = _ASSET_ROOT / f"map_{mapid:04d}.png"
        img.save(out)
        img.stats["png"] = str(out)  # type: ignore[attr-defined]
    return img


def _selftest():
    """Render map 16 (Black Castle Glass Hall) and assert it is a real, populated map."""
    img = render_map(16, scale=1, save=False)
    st = img.stats  # type: ignore[attr-defined]
    assert st["grid"] == "24x15", st
    # cathedral hall: substantial painted content, tiles resident in VRAM
    assert st["nonblack_frac"] > 0.4, st
    assert st["missing_tile_quadrants"] == 0, st
    print("selftest OK", st)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        ids = [int(a) for a in sys.argv[1:]] or [16]
        for mid in ids:
            im = render_map(mid, scale=1)
            print(im.stats)  # type: ignore[attr-defined]
