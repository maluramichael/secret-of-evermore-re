"""Assemble boss and large sprites of Secret of Evermore STATICALLY from the ROM.

Sibling of `soe.playersprite` (Boy) and `soe.bigsprites` (live capture through the
emulator). This module needs NO emulator: the bosses never spawn in the live
caller (their spawn script does not run), so, exactly like the Boy, they are
located purely statically by comparison with color-correct sprite sheets from
The Spriters Resource (user-supplied, visual reference only, nothing is copied
from them) and assembled from the ROM graphics data. Format details:
docs/sprites.md.

Method (sheet -> ROM byte match -> assembly -> palette)
-------------------------------------------------------
Addressing: HiROM, headerless, so file offset == SNES address & 0x3FFFFF.

1. REFERENCE (sheet). The color-correct sprite sheets from the "Bosses" and
   "Enemies" sections of spriters-resource.com/snes/secretevermore/ are placed in
   assets/bosses/ by the user (boss = site asset ID, see BOSS_SHEETS). The sheets
   use the real SNES game colors. They are the per-boss reference sheet that the
   Boy approach needed.

2. ROM BYTE MATCH (localization). Unlike the Boy, the boss tiles are NOT raw but
   LZ compressed (soe.lz.decompress_sprite, zero-word RLE, 16x16 blocks of 128 B).
   The trick to avoid the block pointer table (shifted in the EU ROM): decompress
   ONE block at EVERY byte offset of the sprite region (0x1E0000..0x2C0000) and
   match its four 8x8 tiles against the sheet pixels. At a real block start
   decompress_sprite yields the real tiles; at wrong offsets it yields noise that
   does not match.

   Matching is PALETTE INDEPENDENT (the boss palette is unknown a priori): an 8x8
   tile is reduced to its canonical form (canon(): index 0 stays transparent, the
   non-zero colors are renumbered by first appearance in raster order). Two tiles
   match if their canonical forms are equal, i.e. the same pixel STRUCTURE
   regardless of the concrete palette. On the sheet side all sliding 8x8 windows
   with >= MIN_COLORS colors are indexed as "needles". Hits cluster tightly in a
   narrow ROM offset span per boss (evidence of real, contiguously stored boss
   graphics, not chance).

3. ASSEMBLY. Each hit (block offset, subtile t, sheet position x,y) anchors the
   WHOLE 16x16 block at the sheet position it implies
   (origin = (x-8*(t%2), y-8*(t//2))). Blocks are painted at their REAL sheet
   coordinates, so the assembly follows the sheet layout (multi-tile bosses
   32x32..64x64+). Overlaps (structure collisions of simple tiles) are filtered by
   pixel AGREEMENT against the sheet: a block is kept only if its pixels, colored
   with the recovered palette, agree with the sheet to >= MIN_AGREE (same verify
   principle as for the Boy). Holes (uncolored edge tiles that were too poor as a
   needle) are filled by a LOCAL tile pool search in the located ROM range (all
   sheet cells, including h/v flip).

4. PALETTE. The boss palette is not in the 25-entry character table (which only
   holds player/party/main NPCs), so it is reconstructed FROM THE MATCH: per ROM
   index the sheet color that lies over it most often (majority vote over all
   hits). This yields the real 16-color boss palette (index -> RGB) used to color
   the exported ROM tiles.

VERIFICATION per boss: median pixel agreement of the kept blocks ("match score",
1.0 = pixel exact) + coverage (fraction of filled content cells of the main pose)
+ the narrow ROM offset span. A boss counts as verified at median agreement
>= 0.90 and >= 6 verified blocks.

Dead ends
---------
* Character table palettes (soe.palettes, 25 entries) for bosses: they cover only
  1-5 of 16 boss sheet colors, so bosses are NOT in this table. The palette is
  reconstructed from the sheet match instead.
* Chain walk (sequential by consumed bytes through the sprite chain): loses sync
  after a few blocks and is unusable. Blocks are matched individually per offset.
* Live capture (soe.bigsprites): needs the emulator and a spawning map load, which
  is exactly what is missing for the bosses. Hence this static approach.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from pathlib import Path

from .rom import Rom
from . import lz

# --- Verified constants -----------------------------------------------------
REGION = (0x1E0000, 0x2C0000)   # compressed sprite region (see the playersprite dead end note)
MIN_COLORS = 7                  # needle/ROM tile: >= this many non-zero colors (discriminative)
MIN_AGREE = 0.75                # pixel agreement threshold per block against the sheet
MIN_PX = 12                     # a scored block needs >= this many opaque pixels
VERIFY_AGREE = 0.90             # from here on a boss counts as verified
VERIFY_BLOCKS = 6

# Boss/large sprite sheets: name -> Spriters Resource asset ID (provenance).
BOSS_SHEETS = {
    "thraxx": 10182, "aegis": 147966, "aquagoth": 147965, "carltrons_robot": 31133,
    "foot_knight": 35770, "magmar": 31134, "megataur": 148754, "metal_magmar": 31136,
    "mungola": 35771, "rimsala_antiqua": 241553, "salabog": 10180, "sterling": 35741,
    "timberdrake": 35772, "verminator": 35773, "son_of_set_anhur": 150294,
    "rimsala_omnitopia": 31140, "stone_cobra": 31141, "carniflower": 31219,
    "flowering_death": 31220, "tar_skull": 150741, "mad_monk": 150201,
    "guardbot": 150204, "mummy_cat": 31137, "bone_buzzard_group": 151346,
    "raptors": 229687,
}

_ROOT = Path(__file__).resolve().parent.parent
_REF = _ROOT / "assets/bosses"


# ---------------------------------------------------------------------------
# Low level: canonical tile signature + block decode
# ---------------------------------------------------------------------------
def canon(grid) -> bytes:
    """8x8 palette index grid -> palette independent canonical bytes.

    Index 0 stays 0 (transparent); non-zero values are renumbered by first
    appearance in raster order. Equal bytes <=> equal pixel structure.
    """
    m = {0: 0}
    nxt = 1
    out = bytearray(64)
    k = 0
    for row in grid:
        for v in row:
            c = m.get(v)
            if c is None:
                c = nxt
                m[v] = c
                nxt += 1
            out[k] = c
            k += 1
    return bytes(out)


def _block_tiles(rom: Rom, off: int):
    """Decompress a 16x16 block at off -> [4x 8x8 grid] (subtiles 0..3)."""
    b, _ = lz.decompress_sprite(rom.data, off)
    return [rom.decode_4bpp(b[t * 32:t * 32 + 32]) for t in range(4)]


def _flip(grid, mode):
    if mode == 1:
        return [r[::-1] for r in grid]
    if mode == 2:
        return grid[::-1]
    return grid


# ---------------------------------------------------------------------------
# Sheet -> palette index grid (bg -> 0, rest by frequency)
# ---------------------------------------------------------------------------
def load_sheet(name: str):
    from PIL import Image
    im = Image.open(_REF / f"{name}.png").convert("RGBA")
    W, H = im.size
    px = im.load()
    cnt = Counter(im.getdata())
    bg = cnt.most_common(1)[0][0][:3]
    order = [c for c, _ in cnt.most_common() if c[:3] != bg and c[3] > 0]
    cid = {c: i + 1 for i, c in enumerate(order)}
    grid = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            grid[y][x] = 0 if (p[3] == 0 or p[:3] == bg) else cid.get(p, 0)
    return grid, im, W, H, bg


def sheet_needles(name, grid, W, H):
    """sig -> [(name, x, y)] for all sliding 8x8 windows with >= MIN_COLORS colors."""
    out = defaultdict(list)
    for y in range(H - 7):
        for x in range(W - 7):
            tile = [grid[y + j][x:x + 8] for j in range(8)]
            sig = canon(tile)
            nd = len(set(v for row in tile for v in row) - {0})
            if nd >= MIN_COLORS:
                out[sig].append((name, x, y))
    return out


# ---------------------------------------------------------------------------
# ROM sweep: 1 block per offset, match tiles against all needles
# ---------------------------------------------------------------------------
def sweep(rom: Rom, needles: dict, region=REGION):
    """[(off, t, name, x, y, nd)] for every tile hit in the region."""
    data = rom.data
    lo, hi = region
    hits = []
    off = lo
    while off < hi - 8:
        try:
            block, _ = lz.decompress_sprite(data, off)
        except Exception:
            off += 1
            continue
        for t in range(4):
            grid = rom.decode_4bpp(block[t * 32:t * 32 + 32])
            nd = len(set(v for row in grid for v in row) - {0})
            if nd >= MIN_COLORS:
                m = needles.get(canon(grid))
                if m:
                    for (name, x, y) in m:
                        hits.append((off, t, name, x, y, nd))
        off += 1
    return hits


# ---------------------------------------------------------------------------
# Assembly per boss
# ---------------------------------------------------------------------------
def _placements(hits_b):
    """One block per 16x16 sheet origin (highest nd) -> [(ox, oy, off, nd)]."""
    best = {}
    for (off, t, name, x, y, nd) in hits_b:
        ox, oy = x - 8 * (t % 2), y - 8 * (t // 2)
        k = (ox, oy)
        if k not in best or nd > best[k][1]:
            best[k] = (off, nd)
    return [(ox, oy, off, nd) for (ox, oy), (off, nd) in best.items()]


def _dominant_run(offs, gap=0x400):
    offs = sorted(offs)
    runs, cur = [], [offs[0]]
    for o in offs[1:]:
        if o - cur[-1] <= gap:
            cur.append(o)
        else:
            runs.append(cur)
            cur = [o]
    runs.append(cur)
    return set(max(runs, key=len))


def _recover_palette(rom, placements, spx, W, H, bg):
    votes = [Counter() for _ in range(16)]
    for (ox, oy, off, nd) in placements:
        for t, g in enumerate(_block_tiles(rom, off)):
            gx, gy = ox + 8 * (t % 2), oy + 8 * (t // 2)
            for j in range(8):
                for i in range(8):
                    idx = g[j][i]
                    x, y = gx + i, gy + j
                    if not idx or not (0 <= x < W and 0 <= y < H):
                        continue
                    p = spx[x, y]
                    if p[3] > 0 and p[:3] != bg:        # do not vote for the sheet background
                        votes[idx][p[:3]] += 1
    return [None] + [votes[i].most_common(1)[0][0] if votes[i] else None for i in range(1, 16)]


def _agreement(rom, off, ox, oy, pal, spx, W, H, bg):
    """(fraction of opaque non-bg block pixels that agree with the sheet, their count)."""
    ok = tot = 0
    for t, g in enumerate(_block_tiles(rom, off)):
        gx, gy = ox + 8 * (t % 2), oy + 8 * (t // 2)
        for j in range(8):
            for i in range(8):
                col = pal[g[j][i]]
                x, y = gx + i, gy + j
                if not col or not (0 <= x < W and 0 <= y < H):
                    continue
                p = spx[x, y]
                if p[3] == 0 or p[:3] == bg:
                    continue
                tot += 1
                if p[:3] == col:
                    ok += 1
    return (ok / tot if tot else 0.0), tot


def _filter_good(rom, placements, pal, spx, W, H, bg):
    good = []
    for (ox, oy, off, nd) in placements:
        ag, tot = _agreement(rom, off, ox, oy, pal, spx, W, H, bg)
        if ag >= MIN_AGREE and tot >= MIN_PX:
            good.append((ox, oy, off, nd, ag))
    return good


def _local_pool(rom, lo, hi):
    """sig -> (off, t, flip) for every decompressed subtile in [lo, hi] (+ h/v flip)."""
    data = rom.data
    pool = {}
    off = lo
    while off < hi:
        try:
            b, _ = lz.decompress_sprite(data, off)
        except Exception:
            off += 1
            continue
        for t in range(4):
            g = rom.decode_4bpp(b[t * 32:t * 32 + 32])
            for flip in (0, 1, 2):
                pool.setdefault(canon(_flip(g, flip)), (off, t, flip))
        off += 1
    return pool


def _cell_nz(grid, cx, cy, W, H):
    return sum(1 for j in range(8) for i in range(8)
               if 0 <= cx + i < W and 0 <= cy + j < H and grid[cy + j][cx + i])


def _paint_tile(rom, cpx, gx, gy, off, t, flip, pal, bounds=None):
    g = _flip(rom.decode_4bpp(lz.decompress_sprite(rom.data, off)[0][t * 32:t * 32 + 32]), flip)
    W, H = bounds if bounds else (1 << 30, 1 << 30)
    for j in range(8):
        for i in range(8):
            col = pal[g[j][i]]
            if col and 0 <= gx + i < W and 0 <= gy + j < H:
                cpx[gx + i, gy + j] = (*col, 255)


def _paint_verified(rom, good, pal, cpx, W, H):
    """Paint all agreement-verified blocks; overlaps are prioritized by agreement."""
    agbuf = [[-1.0] * W for _ in range(H)]
    for (ox, oy, off, nd, ag) in sorted(good, key=lambda p: p[4]):
        for t, g in enumerate(_block_tiles(rom, off)):
            gx, gy = ox + 8 * (t % 2), oy + 8 * (t // 2)
            for j in range(8):
                for i in range(8):
                    col = pal[g[j][i]]
                    x, y = gx + i, gy + j
                    if col and 0 <= x < W and 0 <= y < H and ag > agbuf[y][x]:
                        cpx[x, y] = (*col, 255)
                        agbuf[y][x] = ag


def reproduce_full(rom, good, pool, grid, pal, W, H):
    """Full sheet reproduction: all agreement-verified blocks at their real sheet
    coordinates (overlaps prioritized by agreement), then remaining content cells
    filled from the local ROM pool. Returns (canvas, matched, content).
    """
    from PIL import Image
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cpx = canvas.load()
    _paint_verified(rom, good, pal, cpx, W, H)
    matched = content = 0
    xs = [p[0] for p in good]
    ys = [p[1] for p in good]
    x0, y0, x1, y1 = min(xs) - 8, min(ys) - 8, max(xs) + 24, max(ys) + 24
    for cy in range(max(0, y0), min(H - 7, y1), 8):
        for cx in range(max(0, x0), min(W - 7, x1), 8):
            if _cell_nz(grid, cx, cy, W, H) < 4:
                continue
            content += 1
            if cpx[cx, cy][3] or cpx[min(W - 1, cx + 4), min(H - 1, cy + 4)][3]:
                matched += 1
                continue
            hit = pool.get(canon([grid[cy + j][cx:cx + 8] for j in range(8)]))
            if hit:
                matched += 1
                _paint_tile(rom, cpx, cx, cy, *hit, pal, (W, H))
    return canvas, matched, content


def crop_frames(canvas, min_area=100):
    """Connected components of opaque pixels -> [(area, x0, y0, x1, y1)]."""
    from PIL import Image, ImageFilter
    W, H = canvas.size
    a = canvas.load()
    mask = Image.new("L", (W, H), 0)
    mp = mask.load()
    for y in range(H):
        for x in range(W):
            if a[x, y][3]:
                mp[x, y] = 255
    md = mask.filter(ImageFilter.MaxFilter(5)).load()
    seen = bytearray(W * H)
    boxes = []
    for sy in range(H):
        for sx in range(W):
            if md[sx, sy] and not seen[sy * W + sx]:
                boxes.append(_flood(md, seen, sx, sy, W, H))
    return sorted((b for b in boxes if b[0] >= min_area), reverse=True)


def _flood(md, seen, sx, sy, W, H):
    q = deque([(sx, sy)])
    seen[sy * W + sx] = 1
    x0 = x1 = sx
    y0 = y1 = sy
    area = 0
    while q:
        x, y = q.popleft()
        area += 1
        x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and md[nx, ny] and not seen[ny * W + nx]:
                seen[ny * W + nx] = 1
                q.append((nx, ny))
    return area, x0, y0, x1, y1


def assemble_boss(rom: Rom, name: str, hits):
    """Complete assembly of one boss. None if there are no hits."""
    hits_b = [h for h in hits if h[2] == name]
    if not hits_b:
        return None
    placements = _placements(hits_b)
    keep = _dominant_run({p[2] for p in placements})
    placements = [p for p in placements if p[2] in keep]
    grid, im, W, H, bg = load_sheet(name)
    spx = im.load()
    pal = _recover_palette(rom, placements, spx, W, H, bg)
    good = _filter_good(rom, placements, pal, spx, W, H, bg)
    if len(good) < 3:
        return {"name": name, "verified": False, "n_blocks": len(good),
                "reason": "too few verified blocks", "poses": []}
    pal = _recover_palette(rom, [g[:4] for g in good], spx, W, H, bg)
    alloffs = sorted(p[2] for p in good)
    pool = _local_pool(rom, min(alloffs) - 0x80, max(alloffs) + 0x80)
    agrees = sorted(g[4] for g in good)
    med_ag = agrees[len(agrees) // 2]
    poses = _build_poses(rom, good, pool, grid, pal, W, H)
    return {"name": name, "verified": med_ag >= VERIFY_AGREE and len(good) >= VERIFY_BLOCKS,
            "n_blocks": len(good), "median_agreement": round(med_ag, 3),
            "palette": pal, "rom_range": [min(alloffs), max(alloffs)],
            "asset_id": BOSS_SHEETS.get(name), "poses": poses}


def _build_poses(rom, good, pool, grid, pal, W, H):
    """Full sheet reproduction, then crop to connected painted sprites."""
    full, matched, content = reproduce_full(rom, good, pool, grid, pal, W, H)
    cov = round(matched / max(1, content), 3)
    poses = []
    for ci, (area, x0, y0, x1, y1) in enumerate(crop_frames(full)[:8]):
        crop = full.crop((x0, y0, x1 + 1, y1 + 1))
        poses.append({"image": crop, "index": ci, "painted_px": area,
                      "size": list(crop.size), "matched_cells": matched,
                      "content_cells": content, "coverage": cov})
    return poses


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _upscale(im, s=3):
    from PIL import Image
    return im.resize((im.width * s, im.height * s), Image.NEAREST)


def _write_boss(res, out: Path) -> dict:
    d = out / res["name"]
    d.mkdir(parents=True, exist_ok=True)
    for old in list(d.glob("*.png")):
        old.unlink()
    for pi, pose in enumerate(res["poses"]):
        _upscale(pose["image"]).save(d / f"pose_{pi:02d}.png")
    primary = res["poses"][0]["image"] if res["poses"] else None
    if primary is not None:
        _upscale(primary, 4).save(d / "primary.png")
    meta = {k: res[k] for k in ("name", "verified", "n_blocks", "median_agreement",
                                "asset_id") if k in res}
    meta["rom_range"] = [f"0x{res['rom_range'][0]:06X}", f"0x{res['rom_range'][1]:06X}"] \
        if res.get("rom_range") else None
    meta["source_sheet"] = f"assets/bosses/{res['name']}.png (TSR asset {res.get('asset_id')})"
    meta["palette_rgb"] = [list(c) if c else None for c in res.get("palette", [])]
    meta["poses"] = [{"index": p["index"], "size": p["size"], "painted_px": p["painted_px"],
                      "coverage": p["coverage"], "matched_cells": p["matched_cells"],
                      "content_cells": p["content_cells"]}
                     for p in res["poses"]]
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return {"name": res["name"], "verified": res.get("verified", False),
            "poses": len(res["poses"]),
            "primary_size": res["poses"][0]["size"] if res["poses"] else None,
            "median_agreement": res.get("median_agreement"),
            "rom_range": meta["rom_range"]}


def _overview(results, out: Path):
    from PIL import Image
    tiles = []
    for r in results:
        if not r.get("poses"):
            continue
        tiles.append((r["name"], r["poses"][0]["image"]))
    if not tiles:
        return
    cols = 5
    cw = max(t[1].width for t in tiles) + 8
    ch = max(t[1].height for t in tiles) + 16
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cw, rows * ch), (30, 30, 40, 255))
    from PIL import ImageDraw
    dr = ImageDraw.Draw(sheet)
    for k, (nm, im) in enumerate(tiles):
        r, c = divmod(k, cols)
        bx, by = c * cw + 4, r * ch + 12
        sheet.alpha_composite(im, (bx, by))
        dr.text((c * cw + 4, r * ch + 2), nm[:18], fill=(230, 230, 230, 255))
    sheet.save(out)


def extract(rom: Rom, out: Path, *, names=None) -> dict:
    """Common extractor signature: assemble all boss sheets from assets/bosses.

    A single ROM sweep covers all sheets; then assembly + export per boss.
    """
    out.mkdir(parents=True, exist_ok=True)
    names = names or [n for n in BOSS_SHEETS if (_REF / f"{n}.png").exists()]
    needles = {}
    for name in names:
        grid, im, W, H, bg = load_sheet(name)
        for sig, lst in sheet_needles(name, grid, W, H).items():
            needles.setdefault(sig, []).extend(lst)
    hits = sweep(rom, needles)
    index = []
    results = []
    for name in names:
        res = assemble_boss(rom, name, hits)
        if res is None:
            index.append({"name": name, "status": "no_hits"})
            continue
        results.append(res)
        index.append(_write_boss(res, out))
    _overview(results, _REF / "overview.png")
    (out / "_index.json").write_text(json.dumps(index, indent=2))
    verified = [r for r in index if r.get("verified")]
    return {"sheets": len(names), "assembled": len(results),
            "verified": len(verified),
            "verified_names": [r["name"] for r in verified]}


# ---------------------------------------------------------------------------
# Self-test (fast: only a small ROM window + one known boss)
# ---------------------------------------------------------------------------
def _selftest(rom: Rom) -> None:
    # canon is palette independent + flip correct.
    g = [[0, 1, 2, 0, 0, 0, 0, 0]] + [[0] * 8 for _ in range(7)]
    g2 = [[0, 5, 9, 0, 0, 0, 0, 0]] + [[0] * 8 for _ in range(7)]
    assert canon(g) == canon(g2), "canon is not palette independent"
    assert canon(g) != canon(_flip(g, 1)), "hflip should change the structure"
    # Magmar is verified at ~0x264A40: a narrow sweep must find hits there.
    grid, im, W, H, bg = load_sheet("magmar")
    needles = sheet_needles("magmar", grid, W, H)
    hits = sweep(rom, needles, region=(0x264800, 0x266C00))
    assert hits, "no Magmar hit in the verified ROM window 0x264800-0x266C00"
    offs = [h[0] for h in hits]
    assert 0x264A00 <= min(offs) <= 0x266C00, f"Magmar hit outside the window: 0x{min(offs):06X}"
    res = assemble_boss(rom, "magmar", hits)
    assert res and res["poses"], "Magmar assembly empty"
    assert res["median_agreement"] >= 0.75, f"Magmar agreement too low: {res['median_agreement']}"
    print(f"bosses selftest ok (magmar: {len(hits)} hits, "
          f"agreement={res['median_agreement']}, poses={len(res['poses'])})")


if __name__ == "__main__":
    import sys
    rom = Rom(str(_ROOT / "Secret of Evermore (Europe).sfc"))
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest(rom)
    else:
        print(extract(rom, _ROOT / "assets/sprites/bosses"))
