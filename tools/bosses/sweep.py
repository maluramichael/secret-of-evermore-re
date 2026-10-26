"""Single combined ROM sweep for ALL boss sheets -> cache of structural tile hits.

Decompresses one sprite block (soe.lz.decompress_sprite) at every byte offset of the
compressed sprite region and matches each resulting 8x8 tile's palette-independent
canonical signature against sliding 8x8 windows of every boss sheet. One pass over the
ROM covers all bosses. Result cached to tools/bosses/hits.json for fast iteration.
"""
import sys, os, json, glob
from collections import Counter, defaultdict
from PIL import Image
from soe.rom import Rom
from soe import lz

ROM = Rom('Secret of Evermore (Europe).sfc')
DATA = ROM.data
REGION = (0x1E0000, 0x2C0000)
MIN_COLORS = 7          # a needle/rom tile must have >=7 distinct nonzero colors (discriminative)


def canon(grid):
    m = {0: 0}; nxt = 1; out = bytearray(64); k = 0
    for row in grid:
        for v in row:
            c = m.get(v)
            if c is None:
                c = nxt; m[v] = c; nxt += 1
            out[k] = c; k += 1
    return bytes(out), nxt - 1


def sheet_ids(path):
    im = Image.open(path).convert('RGBA')
    W, H = im.size
    cnt = Counter(im.getdata())
    bg = cnt.most_common(1)[0][0]
    order = [c for c, _ in cnt.most_common() if c != bg and c[3] > 0]
    cid = {bg: 0}
    for i, c in enumerate(order):
        cid[c] = i + 1
    px = im.load()
    grid = [[0]*W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            grid[y][x] = 0 if p[3] == 0 else cid.get(p, 0)
    return grid, W, H, bg, im


def build_needles(names):
    """sig -> list of (boss, x, y). Only rich windows."""
    needles = defaultdict(list)
    meta = {}
    for name in names:
        grid, W, H, bg, im = sheet_ids(f'assets/bosses/{name}.png')
        meta[name] = {'size': [W, H], 'bg': list(bg)}
        cnt = 0
        for y in range(H-7):
            row0 = grid[y]
            for x in range(W-7):
                tile = [grid[y+j][x:x+8] for j in range(8)]
                sig, nd = canon(tile)
                if nd >= MIN_COLORS:
                    needles[sig].append((name, x, y)); cnt += 1
        print(f'  {name}: {W}x{H} rich-windows={cnt}', flush=True)
    return needles, meta


def sweep(needles, lo, hi):
    hits = []
    off = lo
    while off < hi - 8:
        try:
            block, _ = lz.decompress_sprite(DATA, off)
        except Exception:
            off += 1; continue
        for t in range(4):
            grid = ROM.decode_4bpp(block[t*32:t*32+32])
            sig, nd = canon(grid)
            if nd >= MIN_COLORS:
                m = needles.get(sig)
                if m:
                    for (name, x, y) in m:
                        hits.append([off, t, name, x, y, nd])
        off += 1
    return hits


if __name__ == '__main__':
    names = [os.path.basename(f)[:-4] for f in sorted(glob.glob('assets/bosses/*.png'))]
    names = [n for n in names if n != 'overview']
    print(f'building needles for {len(names)} sheets...', flush=True)
    needles, meta = build_needles(names)
    print(f'total needle sigs={len(needles)}; sweeping ROM 0x{REGION[0]:X}-0x{REGION[1]:X}...', flush=True)
    hits = sweep(needles, *REGION)
    print(f'total hits={len(hits)}', flush=True)
    json.dump({'region': list(REGION), 'min_colors': MIN_COLORS, 'sheet_meta': meta,
               'hits': hits}, open('tools/bosses/hits.json', 'w'))
    # quick per-boss summary
    byb = defaultdict(list)
    for h in hits:
        byb[h[2]].append(h)
    for name in names:
        hs = byb[name]
        offs = sorted(set(h[0] for h in hs))
        print(f'{name:20s} hits={len(hs):5d} rom_offsets={len(offs)} '
              f'range={f"0x{offs[0]:06X}-0x{offs[-1]:06X}" if offs else "-"}')
