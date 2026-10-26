#!/usr/bin/env python3
"""Pixel comparison: boy atlas (built from the ROM) against emulator ground truth.

Ground truth = TRUTH_SOURCES (assets/dumps/trace/boy_truth/ + boy_truth_ring/,
OAM+VRAM+CGRAM per frame, recorded from a running boy in the emulator;
index.txt lists the active boy metasprite pointers per frame). There are several
sources because running was only recorded separately afterwards (boy_truth_ring).
For every atlas frame (assets/sprites/player/boy_atlas.*) all truth frames with
the same pointer set are looked up, the boy cluster is reconstructed from them
via OAM/VRAM/CGRAM (format + helpers from soe.anim/soe.bigsprites, reused
instead of rewritten) and compared pixel by pixel with the atlas crop.

OBJ char base/offset (PPU $2101) were not recorded during the capture, so they
are calibrated empirically once here: the combination that best hits the boy
cluster in truth frame 1 (down_stand) is used for the whole report.

Output:
  assets/dumps/trace/boy_truth/verify/report.json
  assets/dumps/trace/boy_truth/verify/boy_verify_sheet.png
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from soe.anim import _parse_oam, _draw_sprite  # noqa: E402
from soe.bigsprites import cluster_frame  # noqa: E402
from soe.rom import Rom  # noqa: E402
from soe.snescall import snes_color  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ATLAS_JSON = ROOT / "assets/sprites/player/boy_atlas.json"
TRUTH_DIR = ROOT / "assets/dumps/trace/boy_truth"
TRUTH_SOURCES = [TRUTH_DIR, ROOT / "assets/dumps/trace/boy_truth_ring"]  # run was only captured via the ring capture
OUT_DIR = TRUTH_DIR / "verify"
SHEET = OUT_DIR / "boy_verify_sheet.png"
ROM_FILE = ROOT / "Secret of Evermore (Europe).sfc"
BOY_PALETTE_ROM = 0x10AD70  # boy palette 3

SCREEN_W, SCREEN_H = 256, 224
TOL = 8              # color tolerance per channel (bit replication/shift)
SHIFT = 16           # +-16 px alignment search
BOY_PAL = 6
CENTER = (SCREEN_W / 2, SCREEN_H / 2)


def ref_boy_palette() -> list[tuple[int, int, int]]:
    """Boy palette 3 straight from the ROM, as a reference against tinted frames."""
    return Rom(ROM_FILE).palette(BOY_PALETTE_ROM, 16)


def frame_colors(src: Path, frame_no: int) -> list[tuple[int, int, int]]:
    cgram = (src / f"cgram_{frame_no:04d}.bin").read_bytes()
    return [snes_color(cgram[2 * c] | cgram[2 * c + 1] << 8) for c in range(256)]


def is_untinted(colors: list[tuple[int, int, int]], ref: list[tuple[int, int, int]]) -> bool:
    """Some truth frames carry an ambient tint on palette 6 (see report: not a
    linear fade, more of an on/off flicker from frame ~230). An exact comparison
    is enough: either byte equality or a clearly different color is observed,
    no tolerance case. Index 0 is the transparent OBJ slot (never rendered) and
    is often (0,0,0) in live CGRAM instead of the ROM value -- excluded from the
    comparison."""
    base = 128 + BOY_PAL * 16
    return colors[base + 1:base + 16] == ref[1:16]


# --- Truth index --------------------------------------------------------------

def parse_index(src: Path) -> list[dict]:
    """Read one truth directory (boy_truth/ or boy_truth_ring/).

    Every entry carries `src` so that oam/cgram/vram are loaded from the right
    directory -- frame numbers are only unique WITHIN one directory (several
    captures each start at 0)."""
    frames = []
    last_vram = None
    for line in (src / "index.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        fi = int(line.split()[0])
        ptrs_raw = re.search(r"boy_ptrs=(\S+)", line).group(1)
        vram_tok = re.search(r"vram=(\S+)", line).group(1)
        ptrs = frozenset(ptrs_raw.split(",")) if ptrs_raw != "-" else frozenset()
        if vram_tok != "same":
            last_vram = vram_tok
        frames.append({"src": src, "frame": fi, "ptrs": ptrs, "vram_file": last_vram})
    return frames


def parse_all_sources() -> list[dict]:
    return [e for src in TRUTH_SOURCES for e in parse_index(src)]


def frame_key(entry: dict) -> str:
    """Unique ID suitable for the report, across all truth sources."""
    return f"{entry['src'].name}:{entry['frame']}"


def boy_cluster(sprites: list[dict]) -> list[dict]:
    """The boy cluster: palette-6 group (>=2 sprites) closest to the screen center.

    Excludes the fixed party/HUD icon (its own 1-sprite cluster), because
    cluster_frame() groups spatially and palette-aware.
    """
    cands = [c for c in cluster_frame(sprites) if len(c) >= 2 and c[0]["pal"] == BOY_PAL]
    if not cands:
        return []
    def dist(c):
        cx = sum(s["x"] for s in c) / len(c)
        cy = sum(s["y"] for s in c) / len(c)
        return (cx - CENTER[0]) ** 2 + (cy - CENTER[1]) ** 2
    return min(cands, key=dist)


def sprite_bbox(sprites: list[dict]) -> tuple[int, int, int, int]:
    x0 = min(s["x"] for s in sprites)
    y0 = min(s["y"] for s in sprites)
    x1 = max(s["x"] + s["size"] for s in sprites)
    y1 = max(s["y"] + s["size"] for s in sprites)
    return x0, y0, x1, y1


def render_cluster(sprites: list[dict], vram: bytes, colors: list, base: int, off: int) -> Image.Image:
    img = Image.new("RGBA", (SCREEN_W, SCREEN_H), (0, 0, 0, 0))
    px = img.load()
    for s in reversed(sprites):  # lower index = on top, as in anim._render_sprite_layer
        _draw_sprite(px, s, vram, colors, base, off)
    return img.crop(sprite_bbox(sprites))


def load_truth_render(entry: dict, base: int, off: int) -> Image.Image | None:
    src = entry["src"]
    sprites = boy_cluster(_parse_oam((src / f"oam_{entry['frame']:04d}.bin").read_bytes(), 0))
    if not sprites:
        return None
    cgram = (src / f"cgram_{entry['frame']:04d}.bin").read_bytes()
    colors = [snes_color(cgram[2 * c] | cgram[2 * c + 1] << 8) for c in range(256)]
    vram = (src / entry["vram_file"]).read_bytes()
    return render_cluster(sprites, vram, colors, base, off)


# --- Score ----------------------------------------------------------------

def match_fraction(src, src_size, dst, dst_size, dx: int, dy: int, color: bool = True) -> float:
    """Fraction of opaque src pixels that hit the same color in dst (shifted by dx,dy).

    color=False compares transparency only (silhouette) -- for tinted truth
    frames where the color comparison is suspended (see is_untinted).
    """
    sw, sh = src_size
    dw, dh = dst_size
    opaque = match = 0
    for y in range(sh):
        ty = y + dy
        if not (0 <= ty < dh):
            continue
        for x in range(sw):
            r, g, b, a = src[y * sw + x]
            if not a:
                continue
            opaque += 1
            tx = x + dx
            if 0 <= tx < dw:
                dr, dg, db, da = dst[ty * dw + tx]
                if da and (not color or (abs(dr - r) <= TOL and abs(dg - g) <= TOL and abs(db - b) <= TOL)):
                    match += 1
    return match / opaque if opaque else 0.0


def best_alignment(atlas_img: Image.Image, truth_img: Image.Image, color: bool = True):
    """Best shift (truth relative to atlas) + score_atlas_in_truth there.

    Try shift (0,0) first (atlas rect and truth bbox are both tight around the
    sprite, so they should usually already match) -- only run the full +-16px
    search on a miss instead of blindly doing it for every frame.
    """
    a_data, a_size = list(atlas_img.getdata()), atlas_img.size
    t_data, t_size = list(truth_img.getdata()), truth_img.size
    sc0 = match_fraction(a_data, a_size, t_data, t_size, 0, 0, color)
    if sc0 >= 0.999:
        return (0, 0), sc0
    best_shift, best_sc = (0, 0), sc0
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            if dx == 0 and dy == 0:
                continue
            sc = match_fraction(a_data, a_size, t_data, t_size, dx, dy, color)
            if sc > best_sc:
                best_sc, best_shift = sc, (dx, dy)
                if best_sc >= 0.999:
                    return best_shift, best_sc
    return best_shift, best_sc


def score_reverse(atlas_img: Image.Image, truth_img: Image.Image, shift, color: bool = True) -> float:
    dx, dy = shift
    t_data, t_size = list(truth_img.getdata()), truth_img.size
    a_data, a_size = list(atlas_img.getdata()), atlas_img.size
    return match_fraction(t_data, t_size, a_data, a_size, -dx, -dy, color)


# --- OBJ base/offset calibration --------------------------------------------

def match_atlas_frame(af: dict, truth_frames: list[int], idx_by_frame: dict,
                       obj_base: int, obj_off: int, color: bool = True):
    """Best (score_atlas_in_truth, score_truth_in_atlas, truth_frame, shift, img)
    over all matching truth frames; None if none yields a boy cluster.

    color=False: silhouette only (for tinted truth frames, see is_untinted)."""
    best = None
    for tf in truth_frames:
        timg = load_truth_render(idx_by_frame[tf], obj_base, obj_off)
        if timg is None:
            continue
        shift, sa = best_alignment(af["img"], timg, color)
        st = score_reverse(af["img"], timg, shift, color)
        if best is None or sa > best[0]:
            best = (sa, st, tf, shift, timg)
        if sa >= 0.999 and st >= 0.999:
            break
    return best


def calibrate(index: list[dict], atlas_frames: dict) -> tuple[int, int, float]:
    target = next(f for f in index if f["src"] == TRUTH_DIR and f["frame"] == 1)
    sprites = boy_cluster(_parse_oam((TRUTH_DIR / "oam_0001.bin").read_bytes(), 0))
    cgram = (TRUTH_DIR / "cgram_0001.bin").read_bytes()
    colors = [snes_color(cgram[2 * c] | cgram[2 * c + 1] << 8) for c in range(256)]
    vram = (TRUTH_DIR / target["vram_file"]).read_bytes()
    atlas_crop = atlas_frames["down_stand"]["img"]

    best = (-1.0, None, None)
    for base in range(0x0000, 0x10000, 0x2000):        # 8 candidates
        for k in range(1, 9):                          # offset 0x1000..0x8000
            off = 0x1000 * k
            truth_crop = render_cluster(sprites, vram, colors, base, off)
            _, sc = best_alignment(atlas_crop, truth_crop)
            if sc > best[0]:
                best = (sc, base, off)
    return best[1], best[2], best[0]


# --- Main run ----------------------------------------------------------------

def main():
    atlas = json.loads(ATLAS_JSON.read_text())
    atlas_img = Image.open(ROOT / "assets/sprites/player" / atlas["atlas"]["file"]).convert("RGBA")
    atlas_frames = {}
    for f in atlas["frames"]:
        x, y, w, h = f["rect"]
        atlas_frames[f["id"]] = {"frame": f, "img": atlas_img.crop((x, y, x + w, y + h)),
                                  "ptrs": frozenset(l for l in f["layers"] if l)}

    index = parse_all_sources()  # boy_truth/ + boy_truth_ring/, each over the full file (vram "same")
    ref = ref_boy_palette()
    for e in index:
        e["tint_ok"] = bool(e["ptrs"]) and is_untinted(frame_colors(e["src"], e["frame"]), ref)

    by_ptrs: dict[frozenset, list[str]] = {}       # tint-free frames -> color comparison
    by_ptrs_tinted: dict[frozenset, list[str]] = {}  # tinted frames only -> silhouette fallback
    for e in index:
        if not e["ptrs"]:
            continue
        (by_ptrs if e["tint_ok"] else by_ptrs_tinted).setdefault(e["ptrs"], []).append(frame_key(e))

    obj_base, obj_off, calib_score = calibrate(index, atlas_frames)
    print(f"Calibration: obj_base=0x{obj_base:04X} obj_offset=0x{obj_off:04X} "
          f"(down_stand/frame1 score={calib_score:.4f})")

    idx_by_frame = {frame_key(e): e for e in index}
    report = {"obj_base": obj_base, "obj_offset": obj_off, "oam_size_mode": "8x8/16x16",
              "calibration_frame": 1, "calibration_score": round(calib_score, 4), "frames": {}}
    sheet_rows = []  # (id, atlas_img, truth_img, shift, score_a_in_t, score_t_in_a)

    for fid, af in atlas_frames.items():
        truth_frames = by_ptrs.get(af["ptrs"], [])
        best = match_atlas_frame(af, truth_frames, idx_by_frame, obj_base, obj_off) if truth_frames else None
        if best is not None:
            sa, st, tf, shift, timg = best
            report["frames"][fid] = {
                "score_atlas_in_truth": round(sa, 4), "score_truth_in_atlas": round(st, 4),
                "truth_frame": tf, "shift": list(shift), "n_truth_frames": len(truth_frames),
            }
            sheet_rows.append((fid, af["img"], timg, shift, sa, st, True))
            continue

        tinted_frames = by_ptrs_tinted.get(af["ptrs"], [])
        best_t = (match_atlas_frame(af, tinted_frames, idx_by_frame, obj_base, obj_off, color=False)
                  if tinted_frames else None)
        if best_t is not None:
            sa, st, tf, shift, timg = best_t
            report["frames"][fid] = {
                "status": "tint-only", "shape_match": round(sa, 4), "truth_frame": tf,
                "shift": list(shift), "n_truth_frames_tinted": len(tinted_frames),
                "note": "Only tinted truth frames available, color comparison suspended",
            }
            sheet_rows.append((fid, af["img"], timg, shift, sa, st, False))
        else:
            report["frames"][fid] = {"status": "no truth", "n_truth_frames": 0}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=1))
    print(f"Report: {OUT_DIR / 'report.json'}")

    build_sheet(sheet_rows)
    print(f"Sheet: {SHEET}")
    print_summary(report, len(atlas_frames))


def print_summary(report: dict, n_frames: int) -> None:
    frames = report["frames"]
    matched = {k: v for k, v in frames.items() if "score_atlas_in_truth" in v}
    tint_only = {k: v for k, v in frames.items() if v.get("status") == "tint-only"}
    no_truth = [k for k, v in frames.items() if v.get("status") == "no truth"]
    low = sorted(((k, v) for k, v in matched.items() if v["score_atlas_in_truth"] < 0.98),
                 key=lambda kv: kv[1]["score_atlas_in_truth"])
    print(f"{len(matched)}/{n_frames} frames color-compared, {len(tint_only)} silhouette only "
          f"(tinted truth), {len(no_truth)} without truth match.")
    if low:
        print("Frames < 0.98:")
        for k, v in low:
            print(f"  {k}: atlas_in_truth={v['score_atlas_in_truth']} "
                  f"truth_in_atlas={v['score_truth_in_atlas']} shift={v['shift']} truth_frame={v['truth_frame']}")
    if tint_only:
        print("Silhouette only (tinted):")
        for k, v in tint_only.items():
            print(f"  {k}: shape_match={v['shape_match']} truth_frame={v['truth_frame']}")
    if no_truth:
        print("No truth:", ", ".join(no_truth))


def build_sheet(rows, scale: int = 3):
    if not rows:
        return
    font = ImageDraw.ImageDraw(Image.new("RGB", (1, 1))).getfont()
    cell_h = max(r[1].height for r in rows) * scale + 20
    col_w = max(max(r[1].width, r[2].width) for r in rows) * scale + 10
    pad = 6
    W = col_w * 3 + pad * 4
    H = cell_h * len(rows)
    sheet = Image.new("RGBA", (W, H), (32, 32, 32, 255))
    draw = ImageDraw.Draw(sheet)
    for i, (fid, aimg, timg, shift, sa, st, color) in enumerate(rows):
        y0 = i * cell_h
        dimg = diff_image(aimg, timg, shift, color)
        for j, im in enumerate((aimg, timg, dimg)):
            up = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
            x0 = pad + j * col_w
            sheet.paste(up, (x0, y0 + 18), up)
        label = (f"{fid}  a_in_t={sa:.3f} t_in_a={st:.3f} shift={shift}" if color
                 else f"{fid} [tint-only]  shape={sa:.3f} shift={shift}")
        draw.text((pad, y0 + 1), label, fill=(255, 255, 255, 255), font=font)
    sheet.convert("RGB").save(SHEET)


def diff_image(atlas_img: Image.Image, truth_img: Image.Image, shift, color: bool = True) -> Image.Image:
    dx, dy = shift
    aw, ah = atlas_img.size
    a = list(atlas_img.getdata())
    t = list(truth_img.getdata())
    tw, th = truth_img.size
    out = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
    op = out.load()
    for y in range(ah):
        for x in range(aw):
            r, g, b, al = a[y * aw + x]
            if not al:
                continue
            tx, ty = x + dx, y + dy
            if 0 <= tx < tw and 0 <= ty < th:
                tr, tg, tb, ta = t[ty * tw + tx]
                if ta and (not color or (abs(tr - r) <= TOL and abs(tg - g) <= TOL and abs(tb - b) <= TOL)):
                    op[x, y] = (0, 220, 0, 255)
                    continue
            op[x, y] = (255, 0, 220, 255)
    return out


if __name__ == "__main__":
    main()
