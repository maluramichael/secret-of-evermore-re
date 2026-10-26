"""Text -> JSON/TXT.

Europe layout (verified): item/weapon/armor/alchemy/monster names, all
descriptions and menu/UI text are stored as **plain null-terminated ASCII** in
one block (0x50700-0x52260). No dictionary needed. Map names are in a separate
table at 0x2D8000.

NOT included: the compressed story dialogue (tokenized, own codec plus
2 dictionaries). It is not handled here, to avoid emitting garbage.
"""
from __future__ import annotations
import json
from pathlib import Path

from .rom import Rom

_MIN_LEN = 2                       # 1-character "strings" are mostly random
_PRINTABLE = set(range(0x20, 0x7F))


def _ascii_strings(block: bytes, base: int) -> dict[int, str]:
    """All null-terminated printable ASCII strings in the block, key = file offset."""
    result = {}
    i = 0
    n = len(block)
    while i < n:
        if block[i] in _PRINTABLE:
            j = i
            while j < n and block[j] in _PRINTABLE:
                j += 1
            if j < n and block[j] == 0 and (j - i) >= _MIN_LEN:
                result[base + i] = block[i:j].decode("ascii")
            i = j + 1
        else:
            i += 1
    return result


def _map_names(rom: Rom) -> list[str]:
    """Records [flag 'M'/'m'][0x2E][name\\0], until the table ends."""
    start, _ = rom.span("map_names")
    names = []
    pos = start
    data = rom.data
    while pos + 2 < len(data) and data[pos] in (0x4D, 0x6D) and data[pos + 1] == 0x2E:
        j = pos + 2
        while j < len(data) and data[j] != 0:
            j += 1
        name = data[pos + 2:j].decode("ascii", "replace")
        if not name:
            break
        names.append(name)
        pos = j + 1
    return names


def extract(rom: Rom, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    start, end = rom.span("text_plain")
    strings = _ascii_strings(rom.read(start, end - start), start)
    (out / "strings.json").write_text(
        json.dumps({f"0x{k:X}": v for k, v in sorted(strings.items())},
                   indent=2, ensure_ascii=False))
    (out / "strings.txt").write_text(
        "\n".join(f"0x{k:X}\t{v}" for k, v in sorted(strings.items())))

    names = _map_names(rom)
    maps_dir = out.parent / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    (maps_dir / "map_names.txt").write_text("\n".join(names))
    (maps_dir / "map_names.json").write_text(
        json.dumps({i: n for i, n in enumerate(names)}, indent=2, ensure_ascii=False))

    # Verification: known strings must appear.
    joined = "\n".join(strings.values())
    for known in ("Bone Crusher", "Neutron Blade"):
        assert known in joined, f"Expected string missing: {known!r} (wrong offset?)"

    return {"strings": len(strings), "map_names": len(names)}
