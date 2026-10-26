"""Vision check for soe.maplayers: composite below + a player figure + above and
save it so a human can SEE whether canopy/foliage really lands in the `above`
overlay (occludes the player) while the ground stays in `below`.

Run: python3 tools/verify_maplayers.py [mapid ...]   (default 1 54 16)
Writes assets/maplayers/verify_map_XXXX.png (a cropped, zoomed region centered
on the densest overhead spot, player figure stamped between the two layers) plus
verify_map_XXXX_above.png (the above overlay on a checkerboard, to see its shape).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from soe.maplayers import render_layers  # noqa: E402
from soe.snescall import _CELL  # noqa: E402

_OUT = Path(__file__).resolve().parents[1] / "assets/maplayers"


def _densest_above_cell(above: Image.Image, w_cells: int, h_cells: int):
    """Return the (cx,cy) cell whose 16x16 block has the most opaque `above` pixels
    AND has some room around it -- a spot where a player would stand under canopy."""
    a = above.split()[3]  # alpha
    best, bc = -1, (w_cells // 2, h_cells // 2)
    px = a.load()
    for cy in range(1, h_cells - 1):
        for cx in range(1, w_cells - 1):
            n = 0
            for y in range(_CELL):
                for x in range(_CELL):
                    if px[cx * _CELL + x, cy * _CELL + y]:
                        n += 1
            if n > best:
                best, bc = n, (cx, cy)
    return bc


def _player_figure() -> Image.Image:
    """A small, unmistakable humanoid marker (16x24 RGBA). Not the real sprite --
    just enough to see clearly whether `above` pixels draw over its head/shoulders."""
    fig = Image.new("RGBA", (16, 24), (0, 0, 0, 0))
    p = fig.load()
    body = (255, 40, 220, 255)   # magenta body
    head = (255, 240, 120, 255)  # yellow head (easy to see occlusion on top)
    for y in range(24):
        for x in range(16):
            if y < 7 and 5 <= x <= 10:            # head
                p[x, y] = head
            elif 7 <= y < 20 and 3 <= x <= 12:    # torso
                p[x, y] = body
            elif 20 <= y and (4 <= x <= 6 or 9 <= x <= 11):  # legs
                p[x, y] = body
    return fig


def verify(mapid: int, zoom: int = 4, crop_cells: int = 9):
    r = render_layers(mapid, save=True)
    below, above, st = r["below"], r["above"], r["stats"]
    w_cells = int(st["grid"].split("x")[0])
    h_cells = int(st["grid"].split("x")[1])

    cx, cy = _densest_above_cell(above, w_cells, h_cells)
    fig = _player_figure()

    # Composite full map: below, player between, above on top.
    frame = below.convert("RGBA")
    # stand the figure so its feet sit at the bottom of the chosen cell
    fx = cx * _CELL
    fy = cy * _CELL + _CELL - fig.height + 4
    frame.alpha_composite(fig, (fx, fy))
    frame.alpha_composite(above)

    # Crop a window around the player and zoom.
    half = crop_cells // 2
    left = max(0, (cx - half) * _CELL)
    top = max(0, (cy - half) * _CELL)
    right = min(below.width, left + crop_cells * _CELL)
    bottom = min(below.height, top + crop_cells * _CELL)
    win = frame.crop((left, top, right, bottom))
    win = win.resize((win.width * zoom, win.height * zoom), Image.NEAREST)
    _OUT.mkdir(parents=True, exist_ok=True)
    win.convert("RGB").save(_OUT / f"verify_map_{mapid:04d}.png")

    # Above overlay on a checkerboard so its shape is visible.
    chk = Image.new("RGBA", above.size, (0, 0, 0, 255))
    cp = chk.load()
    for y in range(0, above.height, 8):
        for x in range(0, above.width, 8):
            if ((x // 8) + (y // 8)) & 1:
                for dy in range(min(8, above.height - y)):
                    for dx in range(min(8, above.width - x)):
                        cp[x + dx, y + dy] = (60, 60, 60, 255)
    chk.alpha_composite(above)
    chk.convert("RGB").save(_OUT / f"verify_map_{mapid:04d}_above.png")

    print(f"map{mapid}: {st['grid']} above_frac={st['above_frac']} "
          f"player@cell=({cx},{cy}) below_px={st['painted_below']} "
          f"above_px={st['painted_above']} missing={st['missing_tile_quadrants']}")


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or [1, 54, 16]
    for mid in ids:
        verify(mid)
