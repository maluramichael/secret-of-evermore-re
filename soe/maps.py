"""Map/level data -> JSON.

Reverse-engineering findings (Europe ROM, verified). All offsets are file
offsets (== byte offset, HiROM without SMC header).

## Pointer table (VERIFIED)

At **0x20FDE4** sits the map arrangement pointer table: **127 records of 4
bytes** (= 508 bytes, ends exactly at 0x20FFE0 where filler `2c 30 c3 ...`
begins). 127 matches the 127 map names. Datacrystal gives 0x1FFDE7 for the US
ROM; Europe is shifted by +0x10000 (same shift as the map names, US 0x2C8000
-> EU 0x2D8000).

Record layout: `00 <lo> <hi> <bank>`. Byte 0 is always 0x00 (padding to 4
bytes), bytes 1..3 are a 24-bit LE SNES address. File offset = HiROM(snes):
bank 0xC0-0xFF -> snes-0xC00000, bank 0x80-0xBF -> snes-0x800000. All 127
pointers resolve cleanly into the map data area, banks 0x1D-0x2E
(0x1D8000..0x2EFFFF).

Evidence: all 127 resolved headers have `event_len % 6 == 0` (127/127) and a
tile graphics pointer in bank 0x16/0x17 (126/127 == 0x17). For 127
independent pointers this is no coincidence -> table + header layout are
correct.

## Map header layout (offsets relative to the map start)

    +0x00..0x01  field_00        (2 B, meaning open; maybe default music/palette)
    +0x02..0x04  gfx_ptr         3-byte pointer to tile graphics, bank 0x16/0x17 (VERIFIED)
    +0x05..0x07  field_05        (3 B, byte 0x07 mostly 0x02; maybe another pointer/flags)
    +0x08..0x0B  reserved        0x00000000 (118/127)
    +0x0C        0x00
    +0x0D..0x0E  event_len       length of the event script section in bytes (16-bit, %6==0)
    +0x0F        event entries   6 B each, event_len/6 of them  (VERIFIED, Datacrystal)
    +0x0F+n      btrig_len       length of the B-trigger section (16-bit), n = event_len
    +0x11+n      btrig entries   6 B each, btrig_len/6 of them

A 6-byte trigger entry is a rectangular trigger zone:
`[x1][y1][x2][y2][script_ptr_lo][script_ptr_hi]`. x/y are tile coordinates
(observed ~0x17..0x67), the pointer points into a script bytecode region
(3 B per script). The actual target map index of an exit/warp is IN the script
bytecode, not in the trigger entry -> exit targets need a script interpreter
(not handled here, left open instead of guessed).

## Pending soe.lz

The tile **graphics** (`gfx_ptr`, bank 0x16/0x17) are compressed, see
soe.lz. This module only extracts the pointer/index + metadata and marks it
`needs_lz`. The actual tilemap/arrangement data is not stored uncompressed in
the header either -> `tilemap` stays open until it is decoded via soe.lz.

## Name caveat

`assets/maps/map_names.json` is an **alphabetical debug index**, NOT the
map-ID order of this pointer table. `name_by_debug_index` is included as a
reference, but not claimed as verified per map ID (`name_unverified`).
"""
from __future__ import annotations
import json
from pathlib import Path

from .rom import Rom

# --- Verified offsets (Europe) ------------------------------------
MAP_PTR_TABLE = 0x20FDE4   # map arrangement pointers, 127 records of 4 B
MAP_COUNT = 127
_REC = 4

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "maps"


def _hifile(snes: int) -> int:
    """HiROM SNES address -> file offset."""
    if snes >= 0xC00000:
        return snes - 0xC00000
    if snes >= 0x800000:
        return snes - 0x800000
    return snes


def map_offset(rom: Rom, index: int) -> int:
    """File offset of the map data for map ID `index` (0..126)."""
    if not 0 <= index < MAP_COUNT:
        raise IndexError(f"map index {index} out of range 0..{MAP_COUNT-1}")
    rec = MAP_PTR_TABLE + index * _REC
    snes = rom.data[rec + 1] | rom.data[rec + 2] << 8 | rom.data[rec + 3] << 16
    return _hifile(snes)


def _debug_names() -> dict[int, str]:
    f = _ASSETS / "map_names.json"
    if f.exists():
        return {int(k): v for k, v in json.loads(f.read_text()).items()}
    return {}


def list_maps(rom: Rom) -> list[dict]:
    """All 127 maps: index + file offset + graphics pointer."""
    names = _debug_names()
    out = []
    for i in range(MAP_COUNT):
        off = map_offset(rom, i)
        h = rom.data[off:off + 5]
        gfx = h[2] | h[3] << 8 | h[4] << 16
        out.append({
            "index": i,
            "rom_offset": f"0x{off:06X}",
            "gfx_ptr": f"0x{gfx:06X}",
            "gfx_bank": f"0x{h[4]:02X}",
            "name_by_debug_index": names.get(i),
            "name_unverified": True,
        })
    return out


def _triggers(data: bytes, base: int, length: int) -> list[dict]:
    """6-byte trigger zones: [x1 y1 x2 y2 script_ptr:2]."""
    out = []
    for k in range(length // 6):
        e = data[base + k * 6: base + k * 6 + 6]
        if len(e) < 6:
            break
        out.append({
            "x1": e[0], "y1": e[1], "x2": e[2], "y2": e[3],
            "script_ptr": f"0x{e[4] | e[5] << 8:04X}",
        })
    return out


def read_map(rom: Rom, index: int) -> dict:
    """Extract a map as far as can be verified (see module docstring).

    Contains header fields, graphics pointer (needs_lz), event and B-trigger zones.
    The tilemap data stays open until it is decoded via soe.lz.
    """
    data = rom.data
    off = map_offset(rom, index)
    h = data[off:off + 16]

    gfx = h[2] | h[3] << 8 | h[4] << 16
    event_len = h[0x0D] | h[0x0E] << 8
    ev_base = off + 0x0F
    events = _triggers(data, ev_base, event_len)

    bt_len_off = ev_base + event_len
    btrig_len = data[bt_len_off] | data[bt_len_off + 1] << 8
    bt_base = bt_len_off + 2
    btriggers = _triggers(data, bt_base, btrig_len)

    header_end = bt_base + btrig_len  # end of the (uncompressed) trigger section
    names = _debug_names()

    return {
        "index": index,
        "rom_offset": f"0x{off:06X}",
        "snes_addr": f"0x{off + 0xC00000:06X}",
        "name_by_debug_index": names.get(index),
        "name_unverified": True,
        "header_hex": h.hex(),
        "fields": {
            "field_00": f"0x{h[0] | h[1] << 8:04X}",
            "field_05": h[5:8].hex(),
            "reserved_08": h[8:12].hex(),
        },
        "gfx_ptr": {
            "snes": f"0x{gfx:06X}",
            "file": f"0x{_hifile(gfx):06X}",
            "bank": f"0x{h[4]:02X}",
            "needs_lz": True,
            "note": "Tile graphics are compressed; decode via soe.lz.",
        },
        "event_triggers": {
            "length": event_len,
            "count": len(events),
            "base": f"0x{ev_base:06X}",
            "entries": events,
        },
        "b_triggers": {
            "length": btrig_len,
            "count": len(btriggers),
            "base": f"0x{bt_base:06X}",
            "entries": btriggers,
        },
        "trigger_section_end": f"0x{header_end:06X}",
        "tilemap": None,
        "tilemap_note": "Arrangement/tilemap data is compressed -> needs soe.lz.",
        "exits_note": (
            "Trigger zones define rectangles + script pointers; the target of an "
            "exit is in the script bytecode (not decoded here)."
        ),
    }


def extract(rom: Rom, out: Path) -> dict:
    """Write index.json + map_XXXX.json for example maps."""
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    maps = list_maps(rom)
    (data_dir / "index.json").write_text(
        json.dumps({"pointer_table": f"0x{MAP_PTR_TABLE:06X}", "count": MAP_COUNT,
                    "maps": maps}, indent=2, ensure_ascii=False))

    # Examples: map 0 (first) + map 6 (bank-aligned 0x1D8000, fully verified).
    for idx in (0, 6):
        m = read_map(rom, idx)
        (data_dir / f"map_{idx:04d}.json").write_text(
            json.dumps(m, indent=2, ensure_ascii=False))

    # --- Verification (evidence, see docstring) ---
    ev_ok = sum(1 for i in range(MAP_COUNT)
                if (rom.data[map_offset(rom, i) + 0x0D]
                    | rom.data[map_offset(rom, i) + 0x0E] << 8) % 6 == 0)
    gfx_ok = sum(1 for i in range(MAP_COUNT)
                 if rom.data[map_offset(rom, i) + 4] in (0x16, 0x17))
    assert ev_ok == MAP_COUNT, f"event_len%6 only {ev_ok}/{MAP_COUNT}"
    assert gfx_ok >= 126, f"gfx bank only {gfx_ok}/{MAP_COUNT}"
    # all pointers inside the map data area
    offs = [map_offset(rom, i) for i in range(MAP_COUNT)]
    assert all(0x1D0000 <= o < 0x2F0000 for o in offs), "pointer outside map area"

    return {
        "maps": MAP_COUNT,
        "extracted": ["map_0000.json", "map_0006.json"],
        "event_len_mod6_ok": f"{ev_ok}/{MAP_COUNT}",
        "gfx_bank_ok": f"{gfx_ok}/{MAP_COUNT}",
    }


def _demo() -> None:
    import sys
    rom_path = sys.argv[1] if len(sys.argv) > 1 else "Secret of Evermore (Europe).sfc"
    rom = Rom(rom_path)
    print(f"Pointer table 0x{MAP_PTR_TABLE:06X}, {MAP_COUNT} maps")
    for m in list_maps(rom)[:8]:
        print(f"  #{m['index']:3} {m['rom_offset']}  gfx {m['gfx_ptr']} "
              f"({m['name_by_debug_index']})")
    print("...")
    m0 = read_map(rom, 6)
    print(f"\nMap 6 @ {m0['rom_offset']}: "
          f"{m0['event_triggers']['count']} event, "
          f"{m0['b_triggers']['count']} b-trigger zones; "
          f"gfx {m0['gfx_ptr']['file']} needs_lz={m0['gfx_ptr']['needs_lz']}")
    summary = extract(rom, _ASSETS)
    print("\nextract:", summary)


if __name__ == "__main__":
    _demo()
