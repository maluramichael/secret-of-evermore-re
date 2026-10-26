"""Extract assets from your own Secret of Evermore ROM.

Runs the domain modules of the `soe` package and writes to assets/<domain>/.

    python -m soe                    # all domains
    python -m soe data text          # selected domains
    python -m soe --rom ROM.sfc --out assets

data, text and audio need no Pillow; fonts, palettes, gfx and sprites do.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from soe import DOMAINS, Rom

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = os.environ.get("SOE_ROM", str(ROOT / "Secret of Evermore (Europe).sfc"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m soe",
                                 description="Secret of Evermore asset extraction")
    ap.add_argument("domains", nargs="*", choices=list(DOMAINS),
                    help="domains to extract (default: all): " + ", ".join(DOMAINS))
    ap.add_argument("--rom", default=DEFAULT_ROM, help="ROM path (default: $SOE_ROM or repo root)")
    ap.add_argument("--out", default=str(ROOT / "assets"))
    args = ap.parse_args(argv)

    rom = Rom(args.rom)
    out_base = Path(args.out)
    chosen = args.domains or list(DOMAINS)

    print(f"ROM: {rom.path.name}  region={rom.region}  sha1={rom.sha1[:12]}")
    print(f"Output: {out_base}/\n")

    failed = []
    for name in chosen:
        module, _needs_pillow = DOMAINS[name]
        try:
            summary = module.extract(rom, out_base / name)
            print(f"ok    {name:8s} {summary}")
        except ModuleNotFoundError as e:
            print(f"skip  {name:8s} missing module {e.name} (install pillow)")
        except Exception as e:  # one failing domain must not stop the others
            failed.append(name)
            print(f"error {name:8s} {e}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
