"""Data tables -> JSON.

The Europe values are already available as CSV in the third-party reference
tool `soerominfo` (verified byte for byte against the ROM). They are converted
to typed JSON, and the weapon count is cross-checked directly against the ROM.

The CSVs are located via the `SOEROMINFO` environment variable, else
`third_party/soerominfo` relative to the repo root. Clone it with:

    git clone https://github.com/millanzarreta/soerominfo third_party/soerominfo
"""
from __future__ import annotations
import csv
import json
import os
import re
from pathlib import Path

from .rom import Rom

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PREFIX = "rominforesult_Secret_of_Evermore_(Europe)_(Original)_"
TABLES = ["weapon", "armor", "alchemy", "npc", "ingredients", "callbead", "boydog"]

# The boydog CSV contains hundreds of [FUNC] disassembly columns (noise from the RE tool).
_NOISE = re.compile(r"\[FUNC|Disasm|Raw Byte", re.I)


def _typed(v: str):
    """String -> int/float/str. Hex (0x..) stays a string."""
    if v == "" or v.lower().startswith("0x"):
        return v
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _csv_to_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        keep = [i for i, col in enumerate(header) if not _NOISE.search(col)]
        return [{header[i]: _typed(row[i]) for i in keep if i < len(row)} for row in reader]


def _ref_dir() -> Path:
    """Locate the soerominfo CSV directory (SOEROMINFO env var, else third_party/)."""
    env = os.environ.get("SOEROMINFO")
    root = Path(env) if env else _REPO_ROOT / "third_party" / "soerominfo"
    ref = root / "res_originalroms"
    if not ref.is_dir():
        raise FileNotFoundError(
            f"soerominfo CSV directory not found: {ref}\n"
            "soerominfo is a third-party project that is not shipped with this repo. "
            "Clone it with:\n"
            "    git clone https://github.com/millanzarreta/soerominfo third_party/soerominfo\n"
            "or point the SOEROMINFO environment variable at an existing checkout.")
    return ref


def extract(rom: Rom, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    ref = _ref_dir()
    summary = {}
    index = {}
    for name in TABLES:
        src = ref / f"{_PREFIX}{name}info.csv"
        if not src.exists():
            summary[name] = "MISSING"
            continue
        rows = _csv_to_rows(src)
        (out / f"{name}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        summary[name] = len(rows)
        index[name] = {"file": f"{name}.json", "count": len(rows)}

    # ROM cross-check: count the weapon pointer table (up to a null pointer).
    start, end = rom.span("weapon_ptr")
    n_ptr = 0
    off = start
    while off <= end and rom.u16(off) != 0:
        n_ptr += 1
        off += 2
    index["_rom_check"] = {"weapon_pointers": n_ptr, "csv_weapons": summary.get("weapon")}
    (out / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))
    summary["_weapon_rom_check"] = f"{n_ptr} ptrs vs {summary.get('weapon')} csv"
    return summary
