"""Boy ACTION frames (run/attack/cast/hurt) from the SoE ROM (Europe/PAL).

Continues the method verified in `soe.playersprite` and tries to extract the
ACTION poses of the Boy (running, weapon swing, spell with raised arm, hit
knockback) in addition to STAND and WALK, verifying them against the
color-correct Boy sprite sheet from The Spriters Resource (asset 149455,
assets/screenshots/sprites/boy_spriters_resource.png, visual comparison only).

It reuses the building blocks from playersprite (Rom, Boy palette, frame_grid)
and the same matching: convert each sheet 8x8 tile to Boy palette indices, search
the raw 4bpp tile bank verbatim (normal + hflip), and determine the best tile
assembly per pose plus a verify score (fraction of opaque reference pixels
reproduced exactly).

Result (verified negative)
--------------------------
The method that yields STAND and WALK pixel exact (playersprite: down-stand
verify 0.975, reproduced here as positive control = 0.975) FAILS for the dynamic
action poses of the Boy:

  action / direction    best verify (ceiling) in the Boy tile range
  run   right (side)     ~0.51   (neutral end frame 0.97 = stand duplicate)
  run   down             ~0.74
  run   up               ~0.49   (neutral end frame 0.80)
  cast  down (arm up)    ~0.67   (neutral windup 0.99/1.00 = stand duplicate)
  cast  up   (arm up)    ~0.54
  attack/hurt            ~0.50..0.76 (neutral frames 0.98)

A ROM-wide single-tile ceiling test (best tile ANYWHERE in the whole 3 MB ROM per
8x8 cell) confirms this: distinctive action cells reach only 0.54..0.68, the
control cell (down-stand) reaches exactly 1.00 at the known offset. The
assembled action frames look visibly torn (diagnostic sheet, see extract()).

The action graphics of the Boy are therefore NOT stored as raw, verbatim
searchable 4bpp like stand/walk. The dynamic poses are OAM-composed (several
hardware sprites, each with its OWN (x,y) offset, not on a rigid 8px grid),
driven by the animation script engine (bank $07, documented in playersprite as
the anim_* pointers). Only the neutral first/last frames of an action (which
reuse the stand body) match >= 0.90, but those are visually the stand pose, not
distinctive action graphics.

Consequence: no invented action offsets are reported as verified.
Results are matched live per pose (build_action_frames) with their real verify
score and verified=False for everything below VERIFY_THRESHOLD. extract() writes
only verified frames as game frames, plus a DIAGNOSTIC sheet (sheet crop next to
the assembled candidate) so the discrepancy stays visible.

The way to the action frames is to decode the bank $07 animation script engine
(OAM lists per frame: tile index + relative x/y offset + flip per hardware
sprite). See docs/sprites.md. This module does not do that.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .rom import Rom
from . import palettes
from .playersprite import (
    BOY_INDEX, VERIFY_THRESHOLD, TILE_BYTES, frame_grid,
)

# Search bank: the raw Boy 4bpp bank verified in playersprite, extended up to
# 0x1B0000 because the action rows reference tiles just behind the stand/walk
# sub-bank. (Does not change the negative result: the distinctive poses do not
# match ROM-wide either.)
SEARCH_BANK = (0x1A0000, 0x1B0000)

SHEET_PNG = "assets/screenshots/sprites/boy_spriters_resource.png"

# Action rows in the sheet (y ranges from the row projection of the Boy pixels).
# direction/action labeled by eye on the sheet; `sure` marks how certain the label
# is (attack/hurt share rows and are less clear than run/cast).
# A frame is normally 16x32 (2x4), wider/taller when limbs are spread.
ACTION_ROWS = [
    # action, direction, y0, y1, sure
    ("run",    "right", 418, 460, True),   # side profile, facing right; left=hflip
    ("run",    "down",  464, 499, True),   # front view, running
    ("run",    "up",    510, 546, True),   # back view, running
    ("cast",   "up",    257, 301, True),   # back view, arm raised (+sparks)
    ("cast",   "down",  310, 355, True),   # front view, arm raised (+sparks)
    ("attack", "right", 576, 611, False),  # side weapon swing (mixed with knockback)
    ("hurt",   "down",  613, 648, False),  # hit/stagger, front view
]

# Positive control: down-stand is verified in playersprite at 0.975 and sits at
# fixed offsets. When the matcher is pointed at it, it MUST reproduce it exactly.
CONTROL_DOWN_STAND = {
    "sheet_xy": (2, 80), "wc": 2, "hc": 4, "verify": 0.975,
    "offsets": [0x1A047A, 0x1A049A, 0x1A04BA, 0x1A04DA,
                0x1A03FA, 0x1A041A, 0x1A043A, 0x1A045A],
}


# ---------------------------------------------------------------------------
# Sheet -> Boy palette index grid  (5-bit quantization, as in playersprite)
# ---------------------------------------------------------------------------
def _sheet_index_map(rom: Rom) -> np.ndarray:
    """Sheet as an HxW grid of Boy palette indices (0..15), -1 = background."""
    from PIL import Image
    pal = palettes.character_palettes(rom)[BOY_INDEX]["colors"]
    inv: dict[int, int] = {}
    for i, (r, g, b) in enumerate(pal):
        inv.setdefault((r >> 3) * 1024 + (g >> 3) * 32 + (b >> 3), i)
    img = np.array(Image.open(SHEET_PNG).convert("RGB"))
    q = (img >> 3).astype(np.int32)
    key = q[:, :, 0] * 1024 + q[:, :, 1] * 32 + q[:, :, 2]
    flat = np.full(key.size, -1, np.int16)
    fk = key.reshape(-1)
    for kk, i in inv.items():
        flat[fk == kk] = i
    return flat.reshape(img.shape[:2])


def _bank_tiles(rom: Rom, bank: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """All 8x8 4bpp tiles at every byte offset in `bank` as an (N,8,8) array + offset array."""
    lo, hi = bank
    offs = np.arange(lo, hi - (TILE_BYTES - 1))
    T = np.zeros((offs.size, 8, 8), np.int8)
    d = rom.data
    for j, off in enumerate(offs):
        T[j] = np.array(rom.decode_4bpp(d[off:off + TILE_BYTES]), np.int8)
    return T, offs


# ---------------------------------------------------------------------------
# Tile/frame matcher  (same logic as the playersprite comparison)
# ---------------------------------------------------------------------------
def _match_cell(T, offs, ref, op):
    """Best bank tile (normal/hflip) for an 8x8 cell. -> (off|None, fl, matched, opaque)."""
    oc = int(op.sum())
    if oc == 0:
        return (None, 0, 0, 0)
    mn = ((T == ref) & op).sum(axis=(1, 2))
    mf = ((T == ref[:, ::-1]) & op[:, ::-1]).sum(axis=(1, 2))
    jn = int(mn.argmax())
    jf = int(mf.argmax())
    if mn[jn] >= mf[jf]:
        return (int(offs[jn]), 0, int(mn[jn]), oc)
    return (int(offs[jf]), 1, int(mf[jf]), oc)


def _match_frame(idx, T, offs, px, py, wc, hc):
    """Match a wc x hc (cells) region at (px,py). -> (cells, matched, opaque)."""
    H, W = idx.shape
    cells = []
    m = o = 0
    for cy in range(hc):
        for cx in range(wc):
            y0, x0 = py + cy * 8, px + cx * 8
            sub = idx[y0:y0 + 8, x0:x0 + 8]
            ref = sub.astype(np.int8).copy()
            ref[ref < 0] = 0
            opq = sub >= 1
            off, fl, mm, oc = _match_cell(T, offs, ref, opq)
            cells.append((cx, cy, off, fl))
            m += mm
            o += oc
    return cells, m, o


def _best_placement(idx, T, offs, cx, cy, wc, hc, win=3):
    """Best phase/placement around (cx,cy). -> (verify, px, py, cells) or None."""
    H, W = idx.shape
    best = None
    for dy in range(-win, win + 1):
        for dx in range(-win, win + 1):
            px, py = cx + dx, cy + dy
            if px < 0 or py < 0 or px + wc * 8 > W or py + hc * 8 > H:
                continue
            cells, m, o = _match_frame(idx, T, offs, px, py, wc, hc)
            if o < wc * hc * 4:            # too little sprite in the region
                continue
            v = m / o
            if best is None or v > best[0]:
                best = (v, px, py, cells)
    return best


def _col_bands(idx, y0, y1, gap=2):
    """Column segments (single poses) of a sheet row, split by gaps in the projection."""
    sub = idx[y0:y1]
    cols = (sub >= 1).sum(axis=0)
    bands = []
    inb = False
    g = 0
    start = 0
    for x in range(idx.shape[1]):
        if cols[x] > 0:
            if not inb:
                start = x
                inb = True
            g = 0
        elif inb:
            g += 1
            if g > gap:
                bands.append((start, x - g + 1))
                inb = False
    if inb:
        bands.append((start, idx.shape[1]))
    return [(a, b) for a, b in bands if b - a >= 6]


def _pose_shape(idx, y0, y1, a, b):
    """(px, py, wc, hc) for a pose column (a..b) in row y0..y1."""
    sub = idx[y0:y1, a:b]
    ys = np.where((sub >= 1).any(axis=1))[0]
    top = y0 + int(ys[0])
    bot = y0 + int(ys[-1]) + 1
    wc = max(2, min(3, round((b - a) / 8 + 0.3)))
    hc = max(2, min(5, round((bot - top) / 8 + 0.3)))
    return a, top, wc, hc


# ---------------------------------------------------------------------------
# Match action frames live (NO hard-coded, invented offsets)
# ---------------------------------------------------------------------------
def build_action_frames(rom: Rom, frames_per_action: int = 3) -> dict:
    """Scan ACTION_ROWS, match the best tile assembly + verify per pose.

    Returns: {action: {direction: [frame,...]}}, frame =
      {name, w, h, verify, verified(bool), sure(bool), cells:[(rx,ry,off,fl)]}.
    left is NOT mirrored here (extract does that, as for walk).
    Per action/direction up to `frames_per_action` poses spread over the row are
    taken as the action frames (the animation phases).
    """
    idx = _sheet_index_map(rom)
    T, offs = _bank_tiles(rom, SEARCH_BANK)
    out: dict[str, dict[str, list]] = {}
    for action, direction, y0, y1, sure in ACTION_ROWS:
        bands = _col_bands(idx, y0, y1)
        if not bands:
            continue
        # pick phases evenly spread over the row
        n = len(bands)
        pick = sorted({int(round(i * (n - 1) / max(1, frames_per_action - 1)))
                       for i in range(frames_per_action)})
        frames = []
        for fi, bi in enumerate(pick):
            a, b = bands[bi]
            px0, py0, wc, hc = _pose_shape(idx, y0, y1, a, b)
            bp = _best_placement(idx, T, offs, px0, py0, wc, hc, win=3)
            if bp is None:
                continue
            v, px, py, cells = bp
            frames.append({
                "name": f"{action}{fi}",
                "w": wc, "h": hc,
                "verify": round(v, 3),
                "verified": v >= VERIFY_THRESHOLD,
                "sure": sure,
                "cells": [(cx, cy, off if off is not None else SEARCH_BANK[0], fl)
                          for (cx, cy, off, fl) in cells],
            })
        out.setdefault(action, {})[direction] = frames
    return out


# ---------------------------------------------------------------------------
# Positive control: does the matcher reproduce the verified down-stand exactly?
# ---------------------------------------------------------------------------
def control_down_stand(rom: Rom) -> dict:
    idx = _sheet_index_map(rom)
    T, offs = _bank_tiles(rom, SEARCH_BANK)
    c = CONTROL_DOWN_STAND
    v, px, py, cells = _best_placement(idx, T, offs, *c["sheet_xy"], c["wc"], c["hc"], win=6)
    got = [off for (_, _, off, _) in cells]
    return {"verify": round(v, 3), "offsets": got,
            "matches_playersprite": got == c["offsets"] and abs(v - c["verify"]) < 0.005}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _grid_png(grid, pal):
    from PIL import Image
    h, w = len(grid), len(grid[0])
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            v = grid[y][x]
            if v:
                px[x, y] = (*pal[v], 255)
    return img


def _histogram(grid):
    h = [0] * 16
    for row in grid:
        for v in row:
            h[v] += 1
    return h


def _is_usable(rom, f) -> bool:
    """Usable as a game frame: verify>=0.90 AND a clean Boy (skin + hair + transparency,
    NO bright-green artifact). The neutral 0.90+ stand duplicates drop out here,
    because the matcher puts spurious green tiles into nearly empty cells."""
    if not f["verified"]:
        return False
    h = _histogram(frame_grid(rom, f))
    nz = sum(h[1:])
    if nz < 40 or h[0] <= 20:
        return False
    return ((h[2] + h[3] + h[4]) >= nz * 0.05 and (h[9] + h[10] + h[11]) >= nz * 0.05
            and (h[12] + h[13]) <= nz * 0.02)


def _iter_frames(actions):
    """Flatten {action:{direction:[frame]}} into (action, direction, frame)."""
    for action, dirs in actions.items():
        for direction, frames in dirs.items():
            for f in frames:
                yield action, direction, f


def _write_verified(rom, out, actions, pal) -> list:
    """Only clean, verified frames as game frames; side actions (right) also get left=hflip."""
    written = []
    for action, direction, f in _iter_frames(actions):
        if not _is_usable(rom, f):
            continue
        _grid_png(frame_grid(rom, f, mirror=False), pal).save(
            out / f"boy_{direction}_{f['name']}.png")
        written.append(f"boy_{direction}_{f['name']}.png")
        if direction == "right":
            _grid_png(frame_grid(rom, f, mirror=True), pal).save(
                out / f"boy_left_{f['name']}.png")
            written.append(f"boy_left_{f['name']}.png")
    return written


def _write_diag_sheet(rom, out, actions, pal):
    """Diagnostic sheet: assembled candidate + verify label per pose."""
    from PIL import Image, ImageDraw
    rows = list(_iter_frames(actions))
    cw, ch, pad, labelw = 3 * 8 * 3, 5 * 8 * 3, 6, 150
    sheet = Image.new("RGB", (labelw + cw + 2 * pad, len(rows) * (ch + pad) + pad), (30, 30, 40))
    draw = ImageDraw.Draw(sheet)
    for r, (action, direction, f) in enumerate(rows):
        y = pad + r * (ch + pad)
        asm = _grid_png(frame_grid(rom, f), pal).resize(
            (f["w"] * 8 * 3, f["h"] * 8 * 3), Image.NEAREST)
        sheet.paste(asm.convert("RGB"), (labelw + pad, y))
        ok = _is_usable(rom, f)               # green = clean + exported, not just raw >= 0.90
        draw.text((4, y + 4), f"{'OK ' if ok else 'no '}{action}/{direction}", fill=(230, 230, 230))
        draw.text((4, y + 18), f"{f['name']} v={f['verify']:.2f}",
                  fill=(120, 230, 120) if ok else (230, 140, 120))
    sheet.save(out / "boy_actions_sheet.png")


def _meta_dict(rom, actions) -> dict:
    return {
        "status": ("NEGATIVE: distinctive Boy action poses (run/attack/cast/hurt) "
                   "cannot be found as verbatim 4bpp in the ROM; only neutral stand duplicates "
                   "match >=0.90. Action graphics are OAM/anim-script composed (bank $07)."),
        "positive_control_down_stand": control_down_stand(rom),
        "search_bank": [f"0x{SEARCH_BANK[0]:06X}", f"0x{SEARCH_BANK[1]:06X}"],
        "verify_threshold": VERIFY_THRESHOLD,
        "actions": {
            action: {direction: [
                {"name": f["name"], "verify": f["verify"], "verified": f["verified"],
                 "label_sure": f["sure"], "size": f"{f['w']*8}x{f['h']*8}",
                 "offsets": [f"0x{off:06X}" for (_, _, off, _) in f["cells"]]}
                for f in frames]
                for direction, frames in dirs.items()}
            for action, dirs in actions.items()
        },
    }


def extract(rom: Rom, out_path) -> dict:
    """Write verified action frames + a diagnostic sheet + meta.

    - boy_<dir>_<action><n>.png : ONLY for verified>=0.90 (game frames).
    - boy_actions_sheet.png     : diagnostic - per pose sheet crop | assembled,
                                  with verify label. Shows what matches and what does not.
    - boy_actions_meta.json     : every pose with verify score, verified flag, offsets.
    """
    out = Path(out_path)
    out.mkdir(parents=True, exist_ok=True)
    pal = palettes.character_palettes(rom)[BOY_INDEX]["colors"]
    actions = build_action_frames(rom)

    written = _write_verified(rom, out, actions, pal)
    _write_diag_sheet(rom, out, actions, pal)
    (out / "boy_actions_meta.json").write_text(json.dumps(_meta_dict(rom, actions), indent=2))

    frames_all = list(_iter_frames(actions))
    n_ok = sum(1 for _, _, f in frames_all if f["verified"])
    # "usable" = verify>=0.90 AND clean; all found are neutral stand-like
    # edge frames, NO distinctive dynamic action pose.
    n_usable = sum(1 for _, _, f in frames_all if _is_usable(rom, f))
    return {
        "poses_scored": len(frames_all),
        "verified_ge_090_raw": n_ok,        # incl. torn/stand-like frames
        "usable_clean_frames": n_usable,     # only neutral stand-like edge frames
        "usable_frames_written": written,
        "control_down_stand_reproduced": control_down_stand(rom)["matches_playersprite"],
        "status": "no_distinctive_dynamic_action_pose_extractable",
    }


# ---------------------------------------------------------------------------
# Self-test: matcher correct (positive control) + pin down the negative result
# ---------------------------------------------------------------------------
def _selftest(rom: Rom) -> None:
    # (1) POSITIVE CONTROL: the matcher reproduces the verified down-stand exactly.
    ctrl = control_down_stand(rom)
    assert ctrl["matches_playersprite"], f"matcher does NOT reproduce down-stand: {ctrl}"
    assert ctrl["verify"] >= 0.97, f"control verify too low: {ctrl['verify']}"

    actions = build_action_frames(rom)
    assert actions, "no action rows matched"
    lo, hi = SEARCH_BANK

    # (2) all referenced tile offsets lie inside the search bank.
    for _, _, f in _iter_frames(actions):
        for (_, _, off, fl) in f["cells"]:
            assert lo <= off < hi, f"offset 0x{off:06X} outside search bank"
            assert fl in (0, 1)

    # (3) NEGATIVE RESULT (the core claim): the DISTINCTIVE, dynamic middle phase
    #     of each action (run step, weapon swing, arm-up spell, knockback) is NOT
    #     extractable as a clean game frame. Only neutral edge frames (stand-like
    #     windup/recover) can reach 0.90+ and be clean; that is not action graphics.
    for action, dirs in actions.items():
        for direction, frames in dirs.items():
            if len(frames) >= 3:
                mid = frames[len(frames) // 2]
                assert not _is_usable(rom, mid), (
                    f"{action}/{direction} middle pose {mid['name']} matches "
                    f"unexpectedly clean {mid['verify']}: check the finding, update the docs")

    n_ok = sum(1 for _, _, f in _iter_frames(actions) if f["verified"])
    n_usable = sum(1 for _, _, f in _iter_frames(actions) if _is_usable(rom, f))
    print(f"playeractions selftest ok (control reproduces down-stand={ctrl['verify']}; "
          f"{n_ok} frames >=0.90 raw, of which {n_usable} clean and usable = only neutral "
          f"stand-like edge frames; distinctive action poses NOT verbatim in the ROM)")


if __name__ == "__main__":
    rom = Rom("Secret of Evermore (Europe).sfc")
    _selftest(rom)
    res = extract(rom, Path("assets/sprites/player"))
    print("\n=== extract ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
    print("\nrun/attack/cast/hurt cannot be verified with the verbatim tile comparison")
    print("(OAM/anim-script composed). Details: boy_actions_meta.json,")
    print("diagnostics: boy_actions_sheet.png. No invented offset is reported as done.")
