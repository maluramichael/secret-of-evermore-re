"""Entry point: ``python -m viewer`` (interactive) or ``--selftest`` (headless)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import assets
from .game import Game

# Without these files the viewer does not start (the font is loaded first).
# They live in assets/ and are generated from the ROM; they are NOT part of the
# repository.
_REQUIRED = [
    assets.FONT_MAIN,
    assets.ASSETS / "maps" / "snescall" / "map_0056.png",
]


def _check_assets() -> bool:
    missing = [p for p in _REQUIRED if not p.exists()]
    if not missing:
        return True
    root = assets.ROOT
    print("ERROR: viewer assets are missing, cannot start.\n", file=sys.stderr)
    for p in missing:
        try:
            shown = p.relative_to(root)
        except ValueError:
            shown = p
        print(f"  missing: {shown}", file=sys.stderr)
    print(
        "\nassets/ is generated from your own ROM and is intentionally not part of\n"
        "the repository.\n\n"
        "To create it:\n"
        f"  1) Place the ROM 'Secret of Evermore (Europe).sfc' in {root}/\n"
        "  2) Run the extraction tools of the soe package (see docs/README.md).\n"
        "     Maps additionally need the emulator route; for map 56:\n"
        "       python -m soe.mapdata 56",
        file=sys.stderr)
    return False


def main() -> None:
    ap = argparse.ArgumentParser(prog="viewer", description="Secret of Evermore viewer")
    ap.add_argument("--selftest", action="store_true",
                    help="run headless, render frames, save a proof screenshot and exit")
    ap.add_argument("--ticks", type=int, default=60)
    args = ap.parse_args()

    if not _check_assets():
        sys.exit(2)

    if args.selftest:
        out = assets.ASSETS / "selftest_frame.png"
        Game(headless=True).selftest(str(out), ticks=args.ticks)
        print(f"selftest ok -> {out}")
    else:
        Game().run()


if __name__ == "__main__":
    main()
