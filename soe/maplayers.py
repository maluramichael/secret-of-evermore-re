"""Multilayer map rendering for Secret of Evermore: split every map into a
`below` (behind the player) and an `above` (in front of the player) image so the
game engine's walk-behind effect (e.g. a jungle canopy that draws OVER the boy
as he walks under it) can be reproduced by drawing the player sprite between the
two layers.

This module only READS the decoded map state that `soe.snescall` produces (the
game's own bank-$90 loader, driven headless in Mesen2, decodes each map into WRAM
$7F0000 as per-cell 8-byte records). It reuses snescall's decoders
(`snes_color`, `_decode_4bpp_tile`, `load_map_state`) rather than duplicating them.

================================================================================
HOW ABOVE / BELOW IS DETERMINED  (the SNES BG priority bit)
================================================================================

Per cell (see soe.snescall docstring), `ptr = u16 @ 7F0000 + 2*cell` and the
record is four 16-bit words at `7F0000 + ptr`:
    word0 = BG1 large-tile   word1 = BG2 large-tile   word2 = attr   word3 = 0
Each large-tile word has the SNES tilemap bit layout `vhopppcc cccccccc`
(docs/emulator-techniques.md): bit15=vflip, bit14=hflip,
**bit13 = BG priority (`o`)**, bits12..10 = palette row, bits9..0 = tile index.

CLASSIFICATION RULE (what this module does):
    a drawn sub-tile goes into `above` iff its priority bit (bit13) is set,
    otherwise into `below`. BG2 is drawn before BG1 within each target so the
    normal ground-under-detail order is preserved.

WHY bit13, and the evidence (measured from the assets/dumps/snescall dumps):

 1. BG2 is the ground layer and is ALWAYS below. Measured priority-bit count on
    *drawn* BG2 words: map1 0/1572, map54 3/624, map16 18/342 -> effectively never.
    So word1 (floor / dirt / water) never claims foreground priority. Confirmed.

 2. BG1 (word0) is where the priority bit actually varies and marks the overhead
    layer. Measured on *drawn* BG1 words: map1 528 prio / 138 not, map54 315 / 46,
    map16 106 / 4. The prio-set BG1 sub-tiles are the canopy / tree-crown / overhead
    foliage that the ROM wants in front of things; the prio-clear ones are
    ground-level detail. This is the ROM's own per-tile marker of "may occlude".

 3. The player sprite is OBJ priority 3 (measured directly from the dumped OAM:
    every boy+dog sprite in map1/map54 has attribute priority == 3), and the map
    enables BG1+BG2+BG3+OBJ (TM shadow $0F82 == 0x17). Under strict SNES Mode-1
    ordering OBJ.3 sits above BG1.1, so a static reading would put NOTHING above the
    player. SoE gets its walk-behind effect the classic way: the field engine
    lowers the player's effective OBJ priority where it overlaps a priority-marked
    (BG1.1) cell. So the exact sub-tiles that may draw over the player are the
    priority-bit-set ones. That is the set this module routes into `above`.
    (Limit: the *dynamic* priority drop itself was not traced; the classification
    rests on the measured priority-bit signal + BG2-always-ground, and is checked
    visually by tools/verify_maplayers.py.)

Palette / tileset / dims all come from the same dump as snescall.render_map, and
the same VRAM-tileset ceiling applies (off-screen cells can reference tiles not yet
staged in VRAM -> they render dark; render_layers reports missing-tile stats).
"""
from __future__ import annotations

from pathlib import Path

from . import snescall
from .snescall import (
    _CELL,
    _CHAR_BASE,
    _DIM_H,
    _DIM_W,
    _WRAM_TILEINFO,
    _decode_4bpp_tile,
    load_map_state,
    map_dir,
    snes_color,
)

_ROOT = Path(__file__).resolve().parent.parent
_LAYER_ROOT = _ROOT / "assets/maps/layers"

# bit13 of a `vhopppcc cccccccc` tilemap word = BG priority (see module docstring).
_PRIO_BIT = 1 << 13


def _blit_word(px, word: int, cx: int, cy: int, vram: bytes, cgcol: list,
               ntiles: int, cache: dict, alpha: bool) -> tuple[int, int]:
    """Composite one 16x16 large-tile `word` at cell origin (cx,cy) into `px`.

    Same large-tile expansion as snescall._blit_large (four consecutive 8x8 tiles
    base, base+1, base+16, base+17 at char base 0x4000, 4bpp, with 16x16 flip and
    palette bits 10..12). Transparent index-0 pixels are skipped; when `alpha` the
    written pixels carry a full-opacity alpha channel (for the RGBA `above` image).
    Returns (painted_pixels, missing_quadrants)."""
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
                        col = cgcol[pbase + c]
                        px[ox + x, dy] = (col + (255,)) if alpha else col
                        painted += 1
    return painted, missing


def render_layers(mapid: int, *, save: bool = True) -> dict:
    """Split map `mapid` into a `below` (opaque background+midground) and an
    `above` (transparent over-the-player overlay) image.

    Loads (or reuses) the decoded dump via snescall.load_map_state, then walks the
    width*height cell grid. For each cell's record: BG2 (word1) then BG1 (word0) are
    drawn, each routed by its priority bit (bit13): set -> `above`, clear ->
    `below` (see module docstring for why). Saves
    assets/maps/layers/map_XXXX/below.png (RGB) + above.png (RGBA) when save=True.

    Returns {"below": Image(RGB), "above": Image(RGBA), "stats": {...}}.
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

    cgcol = [snes_color(cg[i] | cg[i + 1] << 8)
             for i in range(0, min(512, len(cg)), 2)]
    ntiles = (len(vram) - _CHAR_BASE) // 32

    below = Image.new("RGB", (w * _CELL, h * _CELL), (0, 0, 0))
    above = Image.new("RGBA", (w * _CELL, h * _CELL), (0, 0, 0, 0))
    bpx, apx = below.load(), above.load()
    cache: dict[int, list] = {}
    painted_below = painted_above = missing = 0

    for cell in range(w * h):
        ptr = wram[_WRAM_TILEINFO + 2 * cell] | wram[_WRAM_TILEINFO + 2 * cell + 1] << 8
        r0 = _WRAM_TILEINFO + ptr
        bg1 = wram[r0] | wram[r0 + 1] << 8
        bg2 = wram[r0 + 2] | wram[r0 + 3] << 8
        cx, cy = (cell % w) * _CELL, (cell // w) * _CELL
        for word in (bg2, bg1):  # ground first, detail on top, within each target
            to_above = bool(word & _PRIO_BIT)
            p, m = _blit_word(apx if to_above else bpx, word, cx, cy,
                              vram, cgcol, ntiles, cache, alpha=to_above)
            missing += m
            if to_above:
                painted_above += p
            else:
                painted_below += p

    stats = {
        "mapid": mapid, "grid": f"{w}x{h}",
        "painted_below": painted_below, "painted_above": painted_above,
        "above_frac": round(painted_above / max(1, painted_below + painted_above), 3),
        "missing_tile_quadrants": missing,
    }
    if save:
        out = _LAYER_ROOT / f"map_{mapid:04d}"
        out.mkdir(parents=True, exist_ok=True)
        below.save(out / "below.png")
        above.save(out / "above.png")
        stats["dir"] = str(out)
    return {"below": below, "above": above, "stats": stats}


def _selftest():
    """Split map 16 and assert the layers are sane: below carries the bulk of the
    room (walls/floor), above is the sparse overhead detail, nothing empty."""
    r = render_layers(16, save=False)
    st = r["stats"]
    assert st["grid"] == "24x15", st
    assert st["painted_below"] > st["painted_above"] > 0, st  # below dominates indoors
    assert st["missing_tile_quadrants"] == 0, st
    # RGBA above must actually be transparent somewhere (an overlay, not a full frame)
    assert r["above"].getextrema()[3][0] == 0, "above has no transparent pixels"
    print("selftest OK", st)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        ids = [int(a) for a in sys.argv[1:]] or [1, 54, 16]
        for mid in ids:
            print(render_layers(mid)["stats"])
