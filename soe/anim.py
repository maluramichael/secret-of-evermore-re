"""Extract SoE *animation* by high-level emulation, same trick as the map caller.

One line: don't reverse the object/palette engines by hand -- boot the ROM in
Mesen2, make the game load a map, then let it KEEP RUNNING and record OAM + CGRAM
(and the live PPU frame) over N successive frames. Motion and palette rotation
fall out on their own, because the console is animating for us.

This is the moving-picture sibling of `soe.snescall` (which dumps ONE settled
frame to composite a full still map). Everything about the hijack is identical;
the only change is that after the map settles we do NOT stop -- we step frames and
snapshot the volatile state each one. See tools/mesen/anim_capture.lua.

================================================================================
HOW THE FRAMES ARE CAPTURED  (tools/mesen/anim_capture.lua, verified live on map 8)
================================================================================

Same EXEC callback on $908F68 as the map caller: pin WRAM $0ADB (map id) to our
TARGET before `LDA $0ADB` runs, so the loader decodes OUR map through its natural
path. Mash START/A/B only until the loader first fires (~frame 389 in the attract
sequence); then the controller goes IDLE so the scene animates in place instead of
transitioning away, while the pin keeps rebuilding the same map if a reload occurs.

After WAIT frames (default 200) let VRAM/CGRAM/OAM settle, then for FRAMES frames
we dump, per frame:
  * oam_%03d.bin   -- snesSpriteRam, 544 bytes  (motion source, see OAM below)
  * cgram_%03d.bin -- snesCgRam, 512 bytes = 256 BGR555 colors (palette-cycle source)
  * shot_%03d.png  -- the live 256x224 PPU frame (GROUND TRUTH for verification)
and once at capture start: vram.bin (64 KB, holds the OBJ tile sheet) + info.txt
(map dims from WRAM $08EE/$08F0, plus OBJ char base/offset/size read from the PPU
state via emu.getState -- safe outside a memory callback).

Mesen memType values used: snesSpriteRam (OAM), snesCgRam, snesVideoRam,
snesWorkRam. Single-address emu.read only inside the memory callback.

================================================================================
OAM PER FRAME  -> sprite motion  (SNES sprite format, wiki.superfamicom.org)
================================================================================

OAM is 544 bytes: a 512-byte primary table (4 bytes x 128 sprites) + a 32-byte
high table (2 bits per sprite).

  primary[4*i + 0] = X low 8 bits
  primary[4*i + 1] = Y (8 bits)
  primary[4*i + 2] = tile number low 8 bits
  primary[4*i + 3] = attr byte  vhoopppN :
        bit0 (N)      = tile number bit 8   -> 9-bit tile index 0..511
        bits1..3 (ppp)= OBJ palette 0..7    -> CGRAM row 128 + pal*16
        bits4..5 (oo) = priority
        bit6 (h)      = h-flip
        bit7 (v)      = v-flip
  high[512 + i//4], shift (i%4)*2 :
        bit0 = X 9th bit (X is a signed 9-bit value: 256..511 -> off the left)
        bit1 = size select (oamMode 0: 0 -> 8x8, 1 -> 16x16)

A 16x16 sprite is four consecutive 8x8 tiles n, n+1, n+16, n+17 (the OBJ tile
sheet is 16 tiles wide). OBJ tile n lives in VRAM at
  objBaseByte + n*32                      for n < 256
  objBaseByte + objOffsetByte + (n-256)*32 for n >= 256
where objBaseByte/objOffsetByte = the PPU oamBaseAddress/oamAddressOffset WORD
values x2 (on map 8: base word 0x6000 -> byte 0xC000, offset 0x1000 words).

We reconstruct the whole sprite layer per frame (transparent background, 256x224):
draw sprites index 127..0 (so sprite 0 lands on top -- lower index = higher SNES
priority), each 8x8/16x16 tile decoded 4bpp from VRAM, flipped per attr, colored
from the sprite's CGRAM OBJ palette, color index 0 transparent. The sequence of
these layers, saved as an APNG, is the sprite animation; a sprite whose X/Y varies
across frames is a moving actor (reported in frames.json -> moving_sprites).

Scope: the sprites present are whatever entities the engine has live while
our map is pinned. During the attract/intro that is the demo's actors (Boy, dog,
NPCs) walking on our map's tiles -- which is exactly what proves the OAM-motion
capture works. The palette cycle below is unambiguously OUR loaded map's.

================================================================================
CGRAM PER FRAME  -> palette-cycle animation  ($90D582 -> $7E6187 -> CGRAM)
================================================================================

SoE animates water, torches/candles and glows not by swapping tiles but by
rotating a few palette entries in place: the per-frame palette-cycle routine at
$90D582 rewrites the active palette ($7E6187), which reaches CGRAM. So simply
re-dumping CGRAM each frame captures the animation with no extra call. We diff the
64 CGRAM snapshots to find the entries that actually change (the cycling colors)
and render:
  * palette.gif      -- the full 16x16 CGRAM color grid over N frames (cells flicker
                        exactly on the cycling entries)
  * the changing indices + distinct-state count go into frames.json

CGRAM color decode reuses soe.snescall.snes_color (15-bit BGR555 -> 8-bit RGB).

================================================================================
OUTPUTS  (assets/anim/map_XXXX/)
================================================================================
  screen.apng      -- the 64 live PPU frames (ground-truth motion proof)
  sprites.apng     -- reconstructed sprite layer per frame, transparent bg
  palette.gif      -- CGRAM color grid per frame (palette-cycle proof)
  spritesheet.png  -- the OBJ tile sheet from VRAM, colored with a live OBJ palette
  frames.json      -- dims, OBJ base, palette-cycle stats, per-frame OAM sprite list,
                      moving-sprite + palette-change summary
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .snescall import snes_color

_ROOT = Path(__file__).resolve().parent.parent
_ROM = _ROOT / "Secret of Evermore (Europe).sfc"
_LUA = _ROOT / "tools/mesen/anim_capture.lua"
_DUMP_ROOT = _ROOT / "assets/dumps/anim"
_ASSET_ROOT = _ROOT / "assets/anim"

_SCREEN_W, _SCREEN_H = 256, 224


# --- capture ------------------------------------------------------------------

def _dump_dir(mapid: int) -> Path:
    return _DUMP_ROOT / f"map_{mapid:04d}"


def _read_info(path: Path) -> dict:
    out: dict = {}
    for tok in path.read_text().split():
        k, _, v = tok.partition("=")
        if v:
            out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


def _mesen_path() -> Path:
    """Mesen2 executable from the MESEN environment variable."""
    exe = os.environ.get("MESEN")
    if not exe:
        raise RuntimeError("MESEN is not set: point it at the Mesen2 executable "
                           "(e.g. export MESEN=/path/to/Mesen)")
    return Path(exe)


def _run_capture(mapid: int, frames: int, wait: int, timeout: int) -> None:
    _MESEN = _mesen_path()
    for p in (_ROM, _MESEN, _LUA):
        if not p.exists():
            raise FileNotFoundError(p)
    d = _dump_dir(mapid)
    d.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SOE_MAPID=str(mapid), SOE_OUT=str(d) + os.sep,
               SOE_WAIT=str(wait), SOE_FRAMES=str(frames))
    proc = subprocess.run([str(_MESEN), "--testRunner", "--noAudio",
                           str(_ROM), str(_LUA)],
                          env=env, capture_output=True, timeout=timeout)
    info = d / "info.txt"
    if not info.exists() or "TIMEOUT" in info.read_text():
        raise RuntimeError(f"map {mapid}: capture failed (exit {proc.returncode}). "
                           f"stderr: {proc.stderr.decode('utf-8', 'replace')[:400]}")


def _decode_obj_tile(vram: bytes, off: int) -> list[list[int]]:
    """One 8x8 4bpp OBJ tile at byte offset `off` -> 8x8 palette-index grid."""
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


def _parse_oam(oam: bytes, oam_mode: int) -> list[dict]:
    """544-byte OAM -> list of 128 sprite dicts (x may be negative, off-screen)."""
    out = []
    for i in range(128):
        b0, b1, b2, b3 = oam[4 * i:4 * i + 4]
        hb = oam[512 + i // 4]
        sh = (i % 4) * 2
        xmsb = (hb >> sh) & 1
        size = (hb >> (sh + 1)) & 1
        x = b0 | (xmsb << 8)
        if x >= 256:
            x -= 512
        out.append({
            "i": i, "x": x, "y": b1,
            "tile": b2 | ((b3 & 1) << 8),
            "pal": (b3 >> 1) & 7, "prio": (b3 >> 4) & 3,
            "hflip": (b3 >> 6) & 1, "vflip": (b3 >> 7) & 1,
            "size": 16 if size else 8,  # oam_mode 0: small 8x8 / large 16x16
        })
    return out


def capture_animation(mapid: int, frames: int = 64, *, wait: int = 200,
                      force: bool = False, timeout: int = 240) -> dict:
    """Boot the ROM headless, load `mapid`, and record `frames` animation frames.

    Runs tools/mesen/anim_capture.lua (idempotent: reuses assets/dumps/anim/map_XXXX unless
    force=True). Returns a dict with the parsed sequences:
      dims=(w,h), frames, obj_base, obj_offset, oam_mode,
      oam_seq   : list[frame] of list[sprite dict]   (see module docstring)
      cgram_seq : list[frame] of bytes (512)         (raw CGRAM per frame)
      colors_seq: list[frame] of list[(r,g,b)]       (256 decoded colors)
      vram      : bytes (64 KB, OBJ tile sheet)
      pal_changes: sorted list of CGRAM indices that change across the run
    """
    d = _dump_dir(mapid)
    info_path = d / "info.txt"
    need = force or not info_path.exists() or not (d / f"shot_{frames - 1:03d}.png").exists()
    if need:
        _run_capture(mapid, frames, wait, timeout)
    info = _read_info(info_path)
    w, h = info["width"], info["height"]
    obj_base = int(info.get("objBaseWord", 0x6000)) * 2
    obj_off = int(info.get("objOffsetWord", 0x1000)) * 2
    oam_mode = int(info.get("oamMode", 0))

    oam_seq, cgram_seq, colors_seq = [], [], []
    for i in range(frames):
        oam = (d / f"oam_{i:03d}.bin").read_bytes()
        cg = (d / f"cgram_{i:03d}.bin").read_bytes()
        oam_seq.append(_parse_oam(oam, oam_mode))
        cgram_seq.append(cg)
        colors_seq.append([snes_color(cg[2 * c] | cg[2 * c + 1] << 8) for c in range(256)])

    c0 = cgram_seq[0]
    pal_changes = sorted(c for c in range(256)
                         if any(cg[2 * c:2 * c + 2] != c0[2 * c:2 * c + 2]
                                for cg in cgram_seq))
    return {
        "mapid": mapid, "dims": (w, h), "frames": frames,
        "obj_base": obj_base, "obj_offset": obj_off, "oam_mode": oam_mode,
        "oam_seq": oam_seq, "cgram_seq": cgram_seq, "colors_seq": colors_seq,
        "vram": (d / "vram.bin").read_bytes(), "pal_changes": pal_changes,
    }


# --- rendering ----------------------------------------------------------------

def _obj_tile_off(tile: int, base: int, off: int) -> int:
    return base + tile * 32 if tile < 256 else base + off + (tile - 256) * 32


def _draw_sprite(px, spr: dict, vram: bytes, colors: list, base: int, off: int) -> int:
    """Blit one sprite onto RGBA pixel-access `px`; return painted pixel count."""
    n = 2 if spr["size"] == 16 else 1  # tiles per edge
    pbase = 128 + spr["pal"] * 16      # OBJ palettes are CGRAM rows 8..15
    hf, vf = spr["hflip"], spr["vflip"]
    painted = 0
    for qy in range(n):
        for qx in range(n):
            # 16x16 = tiles t, t+1, t+16, t+17; flip swaps quadrant order too
            sub = (qx ^ hf) + 16 * (qy ^ vf) if n == 2 else 0
            grid = _decode_obj_tile(vram, _obj_tile_off(spr["tile"] + sub, base, off))
            ox, oy = spr["x"] + qx * 8, spr["y"] + qy * 8
            for y in range(8):
                dy = oy + y
                if not (0 <= dy < _SCREEN_H):
                    continue
                row = grid[7 - y if vf else y]
                for x in range(8):
                    dx = ox + x
                    if not (0 <= dx < _SCREEN_W):
                        continue
                    c = row[7 - x if hf else x]
                    if c:
                        px[dx, dy] = (*colors[pbase + c], 255)
                        painted += 1
    return painted


def _render_sprite_layer(cap: dict, fi: int):
    """Reconstruct the transparent sprite layer for frame `fi` as an RGBA image."""
    from PIL import Image
    img = Image.new("RGBA", (_SCREEN_W, _SCREEN_H), (0, 0, 0, 0))
    px = img.load()
    colors = cap["colors_seq"][fi]
    base, off, vram = cap["obj_base"], cap["obj_offset"], cap["vram"]
    for spr in reversed(cap["oam_seq"][fi]):  # 127..0 so sprite 0 ends on top
        if spr["y"] >= _SCREEN_H:             # SNES parks hidden sprites off-screen
            continue
        _draw_sprite(px, spr, vram, colors, base, off)
    return img


def _palette_grid(colors: list, cell: int = 12):
    """256 colors -> a 16x16 swatch grid image (row-major, OBJ rows in lower half)."""
    from PIL import Image
    img = Image.new("RGB", (16 * cell, 16 * cell), (0, 0, 0))
    px = img.load()
    for idx, col in enumerate(colors):
        gx, gy = (idx % 16) * cell, (idx // 16) * cell
        for y in range(cell):
            for x in range(cell):
                px[gx + x, gy + y] = col
    return img


def _spritesheet(cap: dict, pal_row: int = 0):
    """Full 512-tile OBJ sheet (16 wide) colored with OBJ palette `pal_row` (0..7)."""
    from PIL import Image
    colors = cap["colors_seq"][0]
    pbase = 128 + pal_row * 16
    base, off, vram = cap["obj_base"], cap["obj_offset"], cap["vram"]
    cols, ntiles = 16, 512
    rows = ntiles // cols
    img = Image.new("RGBA", (cols * 8, rows * 8), (0, 0, 0, 0))
    px = img.load()
    for t in range(ntiles):
        grid = _decode_obj_tile(vram, _obj_tile_off(t, base, off))
        ox, oy = (t % cols) * 8, (t // cols) * 8
        for y in range(8):
            for x in range(8):
                c = grid[y][x]
                if c:
                    px[ox + x, oy + y] = (*colors[pbase + c], 255)
    return img


def _save_apng(frames: list, path: Path, duration: int = 66) -> None:
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, disposal=1)


def _visible(spr: dict) -> bool:
    return spr["y"] < _SCREEN_H and -16 <= spr["x"] < _SCREEN_W


_OAM_KEYS = ("i", "x", "y", "tile", "pal", "hflip", "vflip", "size")


def _oam_json(cap: dict) -> list:
    return [[{k: s[k] for k in _OAM_KEYS} for s in filter(_visible, fr)]
            for fr in cap["oam_seq"]]


def _palette_stats(cap: dict) -> dict:
    changes = cap["pal_changes"]
    return {
        "changing_cgram_indices": changes,
        "distinct_cgram_states": len({bytes(cg) for cg in cap["cgram_seq"]}),
        "bg_indices": [c for c in changes if c < 128],
        "obj_indices": [c for c in changes if c >= 128],
    }


def _analyze(cap: dict, painted: list, out: Path) -> dict:
    """Build the frames.json stats: palette-cycle, moving sprites, per-frame OAM."""
    from collections import Counter
    onscreen: dict = {}
    for fr in cap["oam_seq"]:
        for s in filter(_visible, fr):
            onscreen.setdefault(s["i"], set()).add((s["x"], s["y"]))
    moving = sorted(i for i, pts in onscreen.items() if len(pts) > 1)
    used = Counter(s["pal"] for fr in cap["oam_seq"] for s in filter(_visible, fr))
    pal_row = used.most_common(1)[0][0] if used else 0
    _spritesheet(cap, pal_row).save(out / "spritesheet.png")
    return {
        "mapid": cap["mapid"], "dims": list(cap["dims"]), "frames": cap["frames"],
        "obj_base_byte": cap["obj_base"], "obj_offset_byte": cap["obj_offset"],
        "palette_cycle": _palette_stats(cap),
        "sprites": {
            "onscreen_ids": sorted(onscreen), "moving_ids": moving,
            "spritesheet_pal_row": pal_row, "painted_px_per_frame": painted,
        },
        "outputs": {"screen": "screen.apng", "sprites": "sprites.apng",
                    "palette": "palette.gif", "spritesheet": "spritesheet.png"},
        "oam_per_frame": _oam_json(cap),
    }


def render_animation(mapid: int, frames: int = 64, *, scale: int = 2,
                     wait: int = 200, force: bool = False) -> dict:
    """Capture `mapid` and write the animation assets to assets/anim/map_XXXX/.

    Produces screen.apng (ground-truth PPU frames), sprites.apng (reconstructed
    sprite layer), palette.gif (CGRAM color grid, palette-cycle), spritesheet.png,
    and frames.json. Returns a stats dict (also the JSON content).
    """
    from PIL import Image

    cap = capture_animation(mapid, frames, wait=wait, force=force)
    d = _dump_dir(mapid)
    out = _ASSET_ROOT / f"map_{mapid:04d}"
    out.mkdir(parents=True, exist_ok=True)

    def up(im):
        return im.resize((im.width * scale, im.height * scale), Image.NEAREST) if scale != 1 else im

    # 1) ground-truth screen APNG from the live PPU shots
    shots = [Image.open(d / f"shot_{i:03d}.png").convert("RGBA") for i in range(frames)]
    _save_apng([up(s) for s in shots], out / "screen.apng")

    # 2) reconstructed sprite-layer APNG (transparent bg)
    sprite_imgs = [_render_sprite_layer(cap, i) for i in range(frames)]
    painted = [sum(1 for p in im.getdata() if p[3]) for im in sprite_imgs]
    _save_apng([up(im) for im in sprite_imgs], out / "sprites.apng")

    # 3) palette-cycle GIF (only meaningful if something cycles, but always written)
    pal_imgs = [_palette_grid(cap["colors_seq"][i]) for i in range(frames)]
    pal_imgs[0].save(out / "palette.gif", save_all=True, append_images=pal_imgs[1:],
                     duration=66, loop=0)

    # 4) OBJ spritesheet + 5) frame data / motion / palette-cycle analysis
    stats = _analyze(cap, painted, out)
    (out / "frames.json").write_text(json.dumps(stats, indent=1))
    return stats


def _selftest():
    """Map 8 (Podunk plaza): assert something actually animates (palette + sprites)."""
    st = render_animation(8, frames=64)
    pc = st["palette_cycle"]
    assert pc["distinct_cgram_states"] > 1, "no palette cycling detected"
    assert pc["changing_cgram_indices"], "no CGRAM entries changed"
    assert st["sprites"]["moving_ids"], "no moving sprites detected"
    assert any(st["sprites"]["painted_px_per_frame"]), "sprite layer is empty"
    print("selftest OK:",
          f"cgram_states={pc['distinct_cgram_states']}",
          f"changing={len(pc['changing_cgram_indices'])}",
          f"moving_sprites={len(st['sprites']['moving_ids'])}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        ids = [int(a) for a in sys.argv[1:]] or [8]
        for mid in ids:
            s = render_animation(mid)
            print(f"map {mid}:", {
                "moving_sprites": len(s["sprites"]["moving_ids"]),
                "cgram_states": s["palette_cycle"]["distinct_cgram_states"],
                "pal_changes": len(s["palette_cycle"]["changing_cgram_indices"]),
            })
