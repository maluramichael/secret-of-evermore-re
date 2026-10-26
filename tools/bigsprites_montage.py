"""Contact sheet of all assembled big sprites -> assets/bigsprites/overview.png.

Pure proof helper: tiles the first frame (frame_00.png) of each entity with a
short label, grouped by size. Not part of the extraction.
"""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CHARS = ROOT / "assets/sprites/characters"
OUT = ROOT / "assets/bigsprites/overview.png"


def main() -> None:
    idx = json.loads((CHARS / "_index.json").read_text())
    rows = sorted((r for r in idx if "name" in r),
                  key=lambda r: max(r["canvas_tiles"]), reverse=True)
    cell_w, cell_h, cols = 120, 130, 8
    n = len(rows)
    grid_rows = (n + cols - 1) // cols
    img = Image.new("RGBA", (cols * cell_w, grid_rows * cell_h), (30, 30, 42, 255))
    dr = ImageDraw.Draw(img)
    for k, r in enumerate(rows):
        d = CHARS / r["name"]
        frames = sorted(d.glob("frame_*.png"))
        if not frames:
            continue
        sp = Image.open(frames[0]).convert("RGBA")
        sp.thumbnail((cell_w - 8, cell_h - 34), Image.NEAREST)
        gx, gy = (k % cols) * cell_w, (k // cols) * cell_h
        img.paste(sp, (gx + (cell_w - sp.width) // 2, gy + 4), sp)
        t = max(r["canvas_tiles"])
        short = r["name"].split("_", 1)[0] + f" e{r['name'].rsplit('_e',1)[1]}"
        dr.text((gx + 3, gy + cell_h - 28), short, fill=(210, 210, 220, 255))
        dr.text((gx + 3, gy + cell_h - 16),
                f"{t:.1f}t p{r['unique_poses']} m{r['char_match']}",
                fill=(150, 200, 150, 255))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"{n} entities -> {OUT}")


if __name__ == "__main__":
    main()
