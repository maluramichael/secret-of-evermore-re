"""Assemble and animate large multi-tile sprites (bosses, enemies, NPCs).

Sibling of `soe.playersprite` (the Boy), but for ALL characters including the
large bosses made of many OAM tiles (32x32, 48x48, 64x64+). The Boy could be
assembled by pixel comparison against a reference sheet from a raw 4bpp bank.
That does not scale to 200+ actors and not to the bosses (no reference sheet per
boss, the metasprite assembly lives in the animation scripts run by the bank-$D0
animation VM, see docs/sprites.md). The
general approach used here:

    The console assembles the sprites for us. We only record them.

Same principle as for the Boy (real data from the ROM, visually verified), but
from live state instead of a hand-maintained tile table. Format details:
docs/sprites.md.

1. Where the sprite graphics + palette come from (verified, live)
-----------------------------------------------------------------
Reuses `soe.anim.capture_animation(mapid)` (high-level emulation through Mesen2,
same $908F68 hijack as the map caller): boots the ROM headless, pins a map and
records over N frames:
  * OAM   (544 B/frame)   -> the metasprite assembly of EVERY actor, live from the game
  * VRAM  (64 KB, once)   -> the OBJ tile sheet (the 4bpp sprite graphics)
  * CGRAM (512 B/frame)   -> the real, active palettes (including palette cycling)
Graphics (VRAM OBJ tiles), assembly (OAM) and palette (CGRAM) per actor come
synchronized, without decoding the animation scripts and without guessing the LZ codecs
(`soe.lz`) for sprites: the PPU already holds the unpacked tiles in VRAM after the
map load. For bosses, pick the boss map (e.g. map 24 Thraxx, 63 volcano boss,
29 Vigor arena). Boss maps are listed in `assets/scripts/names.json`; the actor
spawns at map load.

2. Metasprite assembly format (how many 8x8 tiles make one actor)  [verified]
-----------------------------------------------------------------------------
SNES OAM: up to 128 hardware sprites, each 8x8 or 16x16 (a 16x16 = four 8x8 tiles
n, n+1, n+16, n+17 in the 16-wide OBJ sheet). A LARGE sprite is simply a GROUP of
adjacent OAM entries (a boss = many 16x16 sprites packed together). The visible
OAM sprites of each frame are grouped spatially into ENTITIES (union-find with gap
tolerance). That group IS the actor's metasprite assembly:

    entity = { (dx, dy, tile, palette, size, hflip, vflip) , ... }

dx/dy are relative to the bounding box corner of the actor. This is the same
structure as for the Boy (`BOY_WALK_FRAMES[...]["cells"]`), but delivered live by
the game and therefore correct for arbitrarily large bosses.

3. Animation (real frames)  [verified]
--------------------------------------
Actors keep stable OAM slots across frames. Each frame is clustered and the
clusters are chained through the shared OAM slot indices into TRACKS (one track =
one actor over time). Per track each frame is rendered into a canvas of the
track's maximum size, anchored at its own bounding box corner (drift across the
screen is removed, the pose animation stays). Result: the actor's real animation
cycle as an APNG.

4. Character enumeration (static table)  [exact]
------------------------------------------------
The character records from SNES $8E:B678 (file 0x0EB678, 74-byte records) are
enumerated as well: palette pointer (+0x09, bank $10) and the 16-bit pointers at
+0x32..+0x46 per record -> `_character_table.json`. These pointers are written with
bank $07 (ANIM_BANK) for historical reasons; that bank is wrong. The boy record's
+0x32 value $457E resolves to $C8457E, a bank-$C8 animation script (opcode $23,
metasprite bank $CC, apparently another actor). What the fields select is open
(docs/sprites.md). This documents WHICH characters
exist and which palette/anim scripts they carry. Live entities are matched
best-effort to a record by palette comparison (CGRAM OBJ palette vs. the 25
character table palettes, field `char_palette_match` per entity).

5. Rejected approaches
----------------------
* Decoding the animation scripts (bank $C8 for the boy): unnecessary, the PPU/OAM delivers the
  finished assembly live.
* Guessing sprite graphics statically via `soe.lz` from the compressed banks: not
  uniquely locatable for individual actors, and the unpacked tiles sit in VRAM
  after the map load anyway.
* Raw 4bpp bank search as for the Boy: needs a reference sheet per actor, which
  does not exist for the bosses.

OUTPUT: assets/sprites/characters/<map>_<entity>/ with frames_*.png (transparent),
spritesheet.png, anim.apng (if more than 1 frame), meta.json (size, frame mapping,
offsets, palette). Plus assets/sprites/characters/_character_table.json and
_index.json (overview of all assembled actors + sizes).
"""
from __future__ import annotations

import json
from pathlib import Path

from .rom import Rom
from . import palettes
from .anim import (capture_animation, _decode_obj_tile, _obj_tile_off,
                   _SCREEN_W, _SCREEN_H)

_ROOT = Path(__file__).resolve().parent.parent
_NAMES = _ROOT / "assets/scripts/names.json"
_OUT = _ROOT / "assets/sprites/characters"

# Character table (same as playersprite/palettes; read only).
CHAR_TABLE = 0x0EB678
CHAR_SIZE = 74
CHAR_PALETTE_OFF = 0x09
# Bank used to label the record pointers in the JSON output. Kept for output stability;
# the pointers do not point into bank $07 (see module docstring, section 4).
ANIM_BANK = 0x070000
# Anim script pointer offsets in the record (from playersprite.REC_ANIM).
ANIM_OFFS = {"stand": 0x32, "walk": 0x34, "run": 0x36, "atk0": 0x38, "atk1": 0x3A,
             "atk2": 0x3C, "atk3": 0x3E, "damage": 0x40, "death": 0x42,
             "spoils": 0x44, "block": 0x46}

# Records 0/1 are verified (palettes docstring: Boy=0, Dog=1); the rest is not
# named reliably. Only used as a rough palette match label.
KNOWN_CHAR_NAMES = {0: "Boy", 1: "Dog"}

# Curated map list: already captured (assets/dumps/anim, instant) + boss/NPC maps.
# Boss maps from assets/scripts/names.json. Order = processing order.
DEFAULT_MAPS = [8, 41, 1, 54, 60, 20, 24, 63, 29, 42, 88, 90]

_GAP = 6          # px tolerance when clustering an actor spatially
_PAD = 1          # px margin around each entity canvas
_MIN_SPRITES = 2  # an entity needs >=2 OAM sprites (large actors)
_MIN_DIM = 12     # or an edge length >= 12 px
_MAX_ENTITIES = 10  # at most this many per map (by size), against HUD/noise


# --- Character table (static, exact) ----------------------------------------
def character_table(rom: Rom) -> list[dict]:
    """Enumerate the character records (palette + anim script pointers)."""
    d = rom.data
    out = []
    for i in range(palettes.CHAR_COUNT):
        base = CHAR_TABLE + i * CHAR_SIZE
        nameptr = d[base] | (d[base + 1] << 8) | (d[base + 2] << 16)
        pal_ptr = rom.u16(base + CHAR_PALETTE_OFF)
        pal_off = (0x100000 | pal_ptr) & 0x3FFFFF
        anims = {k: rom.u16(base + o) for k, o in ANIM_OFFS.items()}
        out.append({
            "index": i, "record_offset": base, "nameptr": nameptr,
            "palette_ptr": pal_ptr, "palette_file": pal_off,
            "palette_rgb": rom.palette(pal_off, 16),
            "anim_ptrs": anims,
        })
    return out


# --- OAM clustering -> entities (metasprite assembly) -----------------------
def _bbox(spr: dict) -> tuple[int, int, int, int]:
    n = spr["size"]
    return (spr["x"], spr["y"], spr["x"] + n, spr["y"] + n)


def _near(a: dict, b: dict, gap: int) -> bool:
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    return (ax0 - gap < bx1 and bx0 - gap < ax1 and
            ay0 - gap < by1 and by0 - gap < ay1)


def _visible(s: dict) -> bool:
    return s["y"] < _SCREEN_H and -16 <= s["x"] < _SCREEN_W


def cluster_frame(oam: list[dict], gap: int = _GAP) -> list[list[dict]]:
    """Group the visible OAM sprites of a frame into actors.

    Joins two sprites only if they are spatially adjacent AND use the same
    OBJ palette. The palette condition separates spatially overlapping actors
    with their own palette (classic Boy=pal6 vs. dog=pal7). Limit: a boss that
    uses TWO OBJ palette rows is split into two parts this way.
    """
    sprites = [s for s in oam if _visible(s)]
    n = len(sprites)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if sprites[i]["pal"] == sprites[j]["pal"] and _near(sprites[i], sprites[j], gap):
                parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i, s in enumerate(sprites):
        groups.setdefault(find(i), []).append(s)
    return list(groups.values())


def _significant(cluster: list[dict]) -> bool:
    if len(cluster) >= _MIN_SPRITES:
        return True
    xs = [b for s in cluster for b in (_bbox(s)[0], _bbox(s)[2])]
    ys = [b for s in cluster for b in (_bbox(s)[1], _bbox(s)[3])]
    return (max(xs) - min(xs) >= _MIN_DIM) and (max(ys) - min(ys) >= _MIN_DIM)


# --- Tracks: chain clusters across frames (animation) -----------------------
def build_tracks(cap: dict) -> list[dict]:
    """Actors as FIXED OAM slot sets from the best-separated reference frame.

    SNES objects occupy stable OAM slots. The frame with the MOST separated actors
    is taken as the reference and clustered (palette aware); each cluster slot set
    IS an actor. This fixed set follows the actor across all frames (frames[fi] =
    its visible sprites in fi). Two different actors have disjoint slot sets and
    can NEVER merge, even if two roaming enemies cross spatially for one frame (an
    index union track merge cascaded exactly there).

    Track = {indices:set, frames:{fi:[sprites]}}; frames[fi] = metasprite assembly.
    """
    ref_clusters: list[list[dict]] = []
    for oam in cap["oam_seq"]:
        cls = [c for c in cluster_frame(oam) if _significant(c)]
        if len(cls) > len(ref_clusters):
            ref_clusters = cls

    tracks: list[dict] = []
    for cl in ref_clusters:
        idx = {s["i"] for s in cl}
        frames = {}
        for fi, oam in enumerate(cap["oam_seq"]):
            sub = [s for s in oam if s["i"] in idx and _visible(s)]
            if sub:
                frames[fi] = sub
        tracks.append({"indices": idx, "frames": frames})
    return tracks


# --- Rendering --------------------------------------------------------------
def _draw_into(cv, spr: dict, ox: int, oy: int, vram: bytes, colors: list,
               base: int, off: int) -> int:
    """Draw a sprite into canvas `cv`, shifted by (-ox,-oy). Returns the pixel count."""
    n = 2 if spr["size"] == 16 else 1
    pbase = 128 + spr["pal"] * 16
    hf, vf = spr["hflip"], spr["vflip"]
    px, W, H = cv.pix, cv.width, cv.height
    painted = 0
    for qy in range(n):
        for qx in range(n):
            sub = (qx ^ hf) + 16 * (qy ^ vf) if n == 2 else 0
            grid = _decode_obj_tile(vram, _obj_tile_off(spr["tile"] + sub, base, off))
            bx, by = spr["x"] + qx * 8 - ox, spr["y"] + qy * 8 - oy
            for y in range(8):
                dy = by + y
                if not (0 <= dy < H):
                    continue
                row = grid[7 - y if vf else y]
                for x in range(8):
                    dx = bx + x
                    c = row[7 - x if hf else x]
                    if c and 0 <= dx < W:
                        px[dx, dy] = (*colors[pbase + c], 255)
                        painted += 1
    return painted


class _Canvas:
    def __init__(self, w, h):
        from PIL import Image
        self.img = Image.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0))
        self.pix = self.img.load()
        self.width, self.height = self.img.size


def _cluster_bbox(cl: list[dict]) -> tuple[int, int, int, int]:
    xs0 = min(_bbox(s)[0] for s in cl); ys0 = min(_bbox(s)[1] for s in cl)
    xs1 = max(_bbox(s)[2] for s in cl); ys1 = max(_bbox(s)[3] for s in cl)
    return xs0, ys0, xs1, ys1


def _track_frame_clusters(track: dict) -> dict:
    """Per frame only the connected sprite group around the actor's anchor slot.

    The fixed slot set can contain an outlier in single frames (a slot the engine
    briefly assigned to another, distant object). The frame sprites are re-clustered
    spatially and the group with the lowest OAM index (the stable anchor of the
    actor) is kept; this drops such outliers and keeps the canvas compact.
    """
    anchor = min(track["indices"])
    out = {}
    for fi, sprites in track["frames"].items():
        groups = cluster_frame(sprites)
        pick = next((g for g in groups if any(s["i"] == anchor for s in g)), None)
        if pick is None:
            pick = max(groups, key=len) if groups else []
        if pick:
            out[fi] = pick
    return out


def _track_canvas_size(track: dict) -> tuple[int, int]:
    w = h = 0
    for cl in _track_frame_clusters(track).values():
        x0, y0, x1, y1 = _cluster_bbox(cl)
        w = max(w, x1 - x0); h = max(h, y1 - y0)
    return w + 2 * _PAD, h + 2 * _PAD


def render_track_frames(track: dict, cap: dict) -> list[dict]:
    """Render every frame of a track (own bbox anchoring). Returns a list of frames."""
    cw, ch = _track_canvas_size(track)
    base, off, vram = cap["obj_base"], cap["obj_offset"], cap["vram"]
    fclusters = _track_frame_clusters(track)
    out = []
    for fi in sorted(fclusters):
        cl = fclusters[fi]
        x0, y0, x1, y1 = _cluster_bbox(cl)
        cv = _Canvas(cw, ch)
        cells = []
        painted = 0
        for s in reversed(cl):   # lower OAM index last = on top
            painted += _draw_into(cv, s, x0 - _PAD, y0 - _PAD, vram,
                                  cap["colors_seq"][fi], base, off)
            cells.append({"dx": s["x"] - x0 + _PAD, "dy": s["y"] - y0 + _PAD,
                          "tile": s["tile"], "pal": s["pal"], "size": s["size"],
                          "hflip": s["hflip"], "vflip": s["vflip"], "oam": s["i"]})
        out.append({"fi": fi, "img": cv.img, "cells": cells, "painted": painted,
                    "bbox_px": [x1 - x0, y1 - y0]})
    return out


# --- Palette matching live entity -> character record -----------------------
def _dominant_pal_row(cl: list[dict]) -> int:
    from collections import Counter
    return Counter(s["pal"] for s in cl).most_common(1)[0][0]


def _match_char_palette(cgram_colors: list, pal_row: int, char_tab: list[dict]):
    """Compare the 16 CGRAM OBJ colors with the character table palettes."""
    live = cgram_colors[128 + pal_row * 16: 128 + pal_row * 16 + 16]
    best_i, best_d = None, 1 << 30
    for c in char_tab:
        d = sum((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
                for a, b in zip(live, c["palette_rgb"]))
        if d < best_d:
            best_i, best_d = c["index"], d
    return best_i, best_d


# --- Names ------------------------------------------------------------------
def _map_name(mapid: int) -> str:
    try:
        return json.loads(_NAMES.read_text())["maps"].get(str(mapid), f"map{mapid}")
    except Exception:
        return f"map{mapid}"


def _slug(s: str) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in s.lower())
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_")[:40]


# --- Export per map ---------------------------------------------------------
def _save_apng(frames, path: Path, duration: int = 100) -> None:
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, disposal=2)


def _spritesheet(frame_imgs, cols: int = 8):
    from PIL import Image
    w = frame_imgs[0].width; h = frame_imgs[0].height
    n = len(frame_imgs); cols = min(cols, n); rows = (n + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * (w + 2) + 2, rows * (h + 2) + 2), (40, 40, 55, 255))
    for k, im in enumerate(frame_imgs):
        r, c = divmod(k, cols)
        sheet.paste(im, (2 + c * (w + 2), 2 + r * (h + 2)), im)
    return sheet


def _dedup_poses(rframes: list[dict]) -> list[dict]:
    """Keep only real poses (drops identical frames, e.g. a long stand)."""
    seen, uniq = set(), []
    for f in rframes:
        key = f["img"].tobytes()
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def _export_entity(track, cap, char_tab, mapid, mname, rank, cw, ch, peak,
                   scale) -> dict | None:
    """Render + write one entity. None if empty (transparency only)."""
    from PIL import Image
    rframes = [f for f in render_track_frames(track, cap) if f["painted"] >= 8]
    if not rframes:
        return None
    uniq = _dedup_poses(rframes)
    f0 = sorted(track["frames"])[0]
    pal_row = _dominant_pal_row(track["frames"][f0])
    mi, md = _match_char_palette(cap["colors_seq"][0], pal_row, char_tab)

    name = f"map{mapid:03d}_{_slug(mname)}_e{rank}"
    d = _OUT / name
    d.mkdir(parents=True, exist_ok=True)
    for old in list(d.glob("*.png")) + list(d.glob("*.apng")):
        old.unlink()

    def up(im):
        return im.resize((im.width * scale, im.height * scale), Image.NEAREST)

    for k, f in enumerate(uniq):
        up(f["img"]).save(d / f"frame_{k:02d}.png")
    up(_spritesheet([f["img"] for f in uniq])).save(d / "spritesheet.png")
    if len(uniq) > 1:
        _save_apng([up(f["img"]) for f in uniq], d / "anim.apng")

    meta = {
        "source_map": mapid, "map_name": mname, "entity_rank": rank,
        "canvas_px": [cw, ch], "canvas_tiles": [round(cw / 8, 1), round(ch / 8, 1)],
        "peak_oam_sprites": peak, "unique_poses": len(uniq),
        "captured_frames": len(rframes), "obj_pal_row": pal_row,
        "palette_source": "live CGRAM (per frame, incl. cycling)",
        "char_palette_match": {"char_index": mi, "distance": md,
                               "name_hint": KNOWN_CHAR_NAMES.get(mi)},
        "assembly_note": ("cells dx/dy relative to the bbox corner; a 16x16 = four "
                          "8x8 OBJ tiles n,n+1,n+16,n+17"),
        "poses": [{"pose": k, "capture_frame": f["fi"], "bbox_px": f["bbox_px"],
                   "n_sprites": len(f["cells"]), "cells": f["cells"]}
                  for k, f in enumerate(uniq)],
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return {"name": name, "canvas_tiles": meta["canvas_tiles"],
            "peak_oam_sprites": peak, "unique_poses": len(uniq), "char_match": mi}


def extract_map(rom: Rom, mapid: int, char_tab: list[dict], *,
                frames: int = 48, scale: int = 3, force: bool = False) -> list[dict]:
    """Capture `mapid` and export all large entities as assembled sprites."""
    cap = capture_animation(mapid, frames, force=force)
    scored = []
    for t in build_tracks(cap):
        cw, ch = _track_canvas_size(t)
        peak = max(len(cl) for cl in t["frames"].values())
        scored.append((cw * ch, peak, t, cw, ch))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)

    mname = _map_name(mapid)
    results = []
    for rank, (area, peak, track, cw, ch) in enumerate(scored[:_MAX_ENTITIES]):
        r = _export_entity(track, cap, char_tab, mapid, mname, rank, cw, ch,
                           peak, scale)
        if r:
            results.append(r)
    return results


def extract(rom: Rom, out: Path, *, maps: list[int] | None = None,
            frames: int = 48) -> dict:
    """Common signature: assemble large sprites from a list of maps.

    Writes each entity to assets/sprites/characters/<name>/ and the overviews
    _character_table.json + _index.json.
    """
    global _OUT
    _OUT = out
    out.mkdir(parents=True, exist_ok=True)
    char_tab = character_table(rom)
    (out / "_character_table.json").write_text(json.dumps([
        {"index": c["index"], "record_offset": f"0x{c['record_offset']:06X}",
         "nameptr": f"0x{c['nameptr']:06X}",
         "palette_file": f"0x{c['palette_file']:06X}",
         "anim_ptrs": {k: (f"0x{ANIM_BANK | v:06X}" if v else None)
                       for k, v in c["anim_ptrs"].items()}}
        for c in char_tab], indent=1))

    maps = maps if maps is not None else DEFAULT_MAPS
    index = []
    for mid in maps:
        try:
            res = extract_map(rom, mid, char_tab, frames=frames)
        except Exception as e:  # one map fails (Mesen timeout) -> continue
            index.append({"map": mid, "error": str(e)[:200]})
            continue
        index.extend(res)
    (out / "_index.json").write_text(json.dumps(index, indent=1))
    n_ok = [r for r in index if "name" in r]
    return {"maps": len(maps), "entities": len(n_ok),
            "large_actors_ge4tiles": len([r for r in n_ok
                                          if max(r["canvas_tiles"]) >= 4.0])}


# --- Self-test --------------------------------------------------------------
def _selftest(rom: Rom) -> None:
    """Map 8 (already captured): clustering + assembly + render must work."""
    cap = capture_animation(8)
    tracks = build_tracks(cap)
    assert tracks, "no tracks clustered"
    # at least one track with >=2 OAM sprites (real multi-tile actor)
    multi = [t for t in tracks
             if max(len(cl) for cl in t["frames"].values()) >= 2]
    assert multi, "no multi-tile actor found"
    # a rendered frame has real pixels (not an empty sprite)
    painted_any = False
    for t in multi[:3]:
        for f in render_track_frames(t, cap):
            if f["painted"] >= 8:
                painted_any = True
                break
        if painted_any:
            break
    assert painted_any, "rendered actor frames are empty"
    ct = character_table(rom)
    assert len(ct) == palettes.CHAR_COUNT
    print(f"bigsprites selftest ok ({len(tracks)} tracks, {len(multi)} multi-tile actors)")


if __name__ == "__main__":
    import sys
    rom = Rom(str(_ROOT / "Secret of Evermore (Europe).sfc"))
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest(rom)
    else:
        ids = [int(a) for a in sys.argv[1:]] or None
        res = extract(rom, _OUT, maps=ids)
        print(res)
