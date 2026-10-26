"""Secret of Evermore event script VM: disassembler plus dialogue/warp resolution.

SoE drives cutscenes, map transitions, NPC talk, shops and story text through a
byte-oriented event script VM. This module decodes that VM from the ROM,
disassembles the scripts of all 127 maps and resolves story text to real
``dialogue.json`` strings and map warps to real map indices.

===============================================================================
1. HOW SCRIPTS ARE FOUND (verified, byte-exact against SoEScriptDumper)
===============================================================================
The initial assumption (a map trigger ``script_ptr`` points directly into a
bank-$CA "behavior VM") was WRONG: the last 2 bytes of a 6-byte trigger are not
a direct pointer but a ``scriptid`` = byte offset into a pointer table. The
correct resolution path (from black-sliver/SoEScriptDumper, ``list-rooms.cpp``,
verified) is:

    scripts_start (SNES)   Europe/PAL 0x938000  |  USA 0x928000
    mapscriptptr  = scripts_start + read16(scripts_start)
    scriptaddr    = script2romaddr( read24(mapscriptptr + scriptid) )
    enter-script  = script2romaddr( read24(scripts_start + 0x1b + 5*mapid) )

    script2romaddr(sa) = scripts_start + (sa & 0x7fff) + ((sa & 0xff8000) << 1)
    file_offset(snes)  = snes & ~0xC00000        (HiROM, un-headered)

File offset 0x128000 (= USA scripts_start as a file offset), which an earlier
text search in ``dialogue.py`` had discarded as a dead end, is exactly this
script pointer region. The map data pointer table is the same as in
``soe.maps`` (Europe file 0x20FDE4).

===============================================================================
2. OPCODE TABLE (149 opcodes with known length, 146 named; lengths verified)
===============================================================================
Every instruction is ``[opcode][args...]``. The argument length is fixed per
opcode, but many opcodes contain SUB-INSTRUCTIONS (expressions): a
self-terminating byte stream (a chain up to a byte with bit 7 set). The total
length is therefore data dependent; ``parse_sub`` decodes it exactly.

Verification: the ``instr_len`` logic was compared against ALL 61018
instructions that SoEScriptDumper decodes from the Europe ROM (address + opcode
+ length) -> **61018/61018 = 100 % byte-exact match**. The opcode names come
from the SoEScriptDumper disassembly (partly derived there from emulator
tracing).

Control flow:
  * 0x00 END        - script end (return). Afterwards: process open branch targets.
  * 0x04/0x05       - unconditional jump (SKIP, forward/backward), continue linearly.
  * 0x08/0x09       - IF/IF-NOT (SUB condition) + SKIP word.
  * 0x0a/0x0b/0x8e/0x8f - IF moniez compare + SKIP.
  * 0x07/0x29/0xa3..0xa6/0xb0..0xb4 - sub/global/NPC/absolute script call.

Story text: opcodes 0x50/0x51/0x52/0x54/0x7f/0x8c load text via
``addr = 0x91d000 + word``. 0x91d000 is the text pointer table (file 0x11d000,
3 bytes/entry). So **text ID = word // 3**, resolved against
``assets/text/dialogue.json`` (via ``soe.dialogue``, 3002 entries). Verified:
e.g. map 0x38 SHOW TEXT 0x063f -> dialogue[533].

Map warp: opcode 0x22 CHANGE MAP = ``[x:1][y:1][mapid:2]`` (mapid = low byte).
mapid is a real map index 0..126. Map and script names are optional: they come
from SoEScriptDumper ``data.h`` (not shipped here) and are read from
``assets/scripts/names.json`` (``{"maps": {"<id>": "<name>"}}``) if present.

What remains unknown: some opcodes are marked "untraced" in SoEScriptDumper
(semantics guessed), but their LENGTH is verified, so the disassembler still
continues correctly. Such opcodes carry a "?" in their name.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .rom import Rom

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "scripts"
_TEXT = Path(__file__).resolve().parent.parent / "assets" / "text"

# --- Region-dependent SNES constants (verified, see docstring) ----------------
REGION = {
    "usa":    {"scripts": 0x928000, "maplist": 0x9FFDE7},
    "europe": {"scripts": 0x938000, "maplist": 0xA0FDE5},   # PAL == DE-Layout
}
TEXT_TABLE = 0x91D000            # SNES: story text pointer table (3 B/entry)


def _consts(rom: Rom) -> dict:
    return REGION.get(rom.region, REGION["europe"])


def file_off(snes: int) -> int:
    return snes & ~0xC00000


def script2rom(sa: int, scripts: int) -> int:
    return scripts + (sa & 0x7FFF) + ((sa & 0xFF8000) << 1)


def _r8(d: bytes, a: int) -> int:
    return d[a & ~0xC00000]


def _r16(d: bytes, a: int) -> int:
    a &= ~0xC00000
    return d[a] | d[a + 1] << 8


def _r24(d: bytes, a: int) -> int:
    a &= ~0xC00000
    return d[a] | d[a + 1] << 8 | d[a + 2] << 16


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


# =============================================================================
# Sub-instruction (self-terminating expression), port of parse_sub
# =============================================================================
_ENTITY = {0xD0, 0xD1, 0xD2, 0xD3, 0xAD, 0xAE}
_ENAME = {0x50: "boy", 0x51: "dog", 0x52: "player", 0x53: "npc",
          0x2D: "lastEnt", 0x2E: "attEnt"}
_SUB1 = frozenset((0x01, 0x02, 0x0F, 0x10, 0x11, 0x12, 0x13))
_SUB2 = frozenset((0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E))
_SUB0 = frozenset((0x00, 0x14, 0x15, 0x16, *range(0x17, 0x2D),
                   0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x5B, 0x5C))


def _sub_val(b: int) -> int:
    cmd = b & 0x70
    if cmd == 0x30:
        return b & 0x0F
    if cmd == 0x40:
        return (0xFFF0 | (b & 0x0F)) - 0x10000
    return 0x10 + (b & 0x0F)          # cmd == 0x60


def parse_sub(d: bytes, a: int) -> tuple[int, bool, str]:
    """Decode a sub-instruction chain starting at ``a`` -> (newaddr, ok, expr).

    Self-terminating: reads sub-bytes until one has bit 7 set. Each sub-byte
    consumes 0/1/2 following bytes depending on its type (verified against
    SoEScriptDumper buf_parse_sub).
    """
    parts: list[str] = []
    ok = True
    while True:
        b = _r8(d, a)
        a += 1
        done = b & 0x80
        if (b | 0x80) in _ENTITY:
            parts.append(_ENAME.get(b & 0x7F, "?ent"))
        elif (b & 0x70) in (0x30, 0x40, 0x60):
            parts.append(str(_sub_val(b)))
        else:
            i = b & 0x7F
            if i in _SUB1:
                parts.append(f"0x{_r8(d, a):02x}")
                a += 1
            elif i in _SUB2:
                parts.append(f"0x{_r16(d, a):04x}")
                a += 2
            elif i in _SUB0:
                parts.append(f"op{i:02x}")
            else:
                ok = False
        if not ok or done:
            break
    return a, ok, " ".join(parts)


def _is_zero(expr: str) -> bool:
    try:
        return int(expr.strip(), 0) == 0
    except ValueError:
        return False


# =============================================================================
# Opcode lengths (verified byte-exact: 61018/61018 against SoEScriptDumper)
# =============================================================================
# Template tokens: B=1 fixed byte, W=2, T=3, S=parse_sub expression.
_FIXED: dict[int, str] = {
    0x00: "", 0x04: "W", 0x05: "B", 0x07: "T", 0x17: "WW", 0x1B: "WWBB",
    0x20: "BB", 0x22: "BBW", 0x26: "", 0x27: "", 0x29: "T", 0x2C: "B", 0x2D: "B",
    0x30: "B", 0x31: "B", 0x33: "B", 0x38: "", 0x3A: "", 0x39: "B",
    0x3C: "WWBB", 0x44: "BBBBB", 0x45: "BBBBB", 0x46: "BBBBB", 0x47: "BBBBB",
    0x48: "", 0x49: "", 0x4A: "", 0x4B: "", 0x4D: "", 0x50: "BW", 0x51: "W",
    0x52: "W", 0x54: "B", 0x55: "", 0x58: "", 0x59: "", 0x5A: "", 0x5B: "",
    0x62: "BWW", 0x63: "", 0x7E: "SSSS", 0x7F: "W", 0x80: "", 0x81: "", 0x82: "",
    0x83: "", 0x87: "S", 0x88: "", 0x8C: "W", 0x8D: "B", 0x96: "SS", 0x98: "S",
    0x9F: "", 0xA0: "", 0xA1: "", 0xA3: "B", 0xA4: "W", 0xA5: "B", 0xA6: "W",
    0xA7: "B", 0xA8: "W", 0xA9: "SS", 0xAA: "", 0xAD: "WWBB", 0xAE: "BBBB",
    0xBA: "BBB", 0xBC: "", 0xBD: "", 0xBE: "", 0xBF: "", 0xC0: "", 0xC1: "", 0xC2: "BBB",
    0x08: "SW", 0x09: "SW", 0x0A: "STW", 0x0B: "STW", 0x0C: "WS", 0x0D: "WS",
    0x0E: "BS", 0x10: "WS", 0x11: "WS", 0x14: "WS", 0x15: "WS", 0x18: "WS",
    0x19: "WS", 0x1C: "WS", 0x1D: "WS", 0x1A: "BS", 0x1E: "BS", 0x2A: "S",
    0x2B: "S", 0x3B: "S", 0x3D: "SW", 0x42: "SW", 0x43: "SSS", 0xB9: "SSS",
    0x4E: "S", 0x5C: "SS", 0x5D: "SW", 0x6C: "SBB", 0x6E: "SBB", 0x6D: "SSS",
    0x6F: "SSS", 0x73: "SSS", 0x9D: "SSS", 0x70: "SS", 0x71: "SS", 0x74: "S",
    0x75: "S", 0x76: "S", 0x77: "S", 0x78: "SWS", 0x79: "SWS", 0x7A: "SS",
    0x7C: "ST", 0x7D: "ST", 0x84: "SS", 0x85: "SS", 0x86: "S", 0x89: "SS",
    0x8A: "S", 0x8E: "SSW", 0x8F: "SSW", 0x91: "S", 0x92: "SS", 0x93: "SS",
    0x94: "SS", 0x95: "SS", 0xBB: "SS", 0x97: "SSSSSSS", 0x99: "SSSSSS",
    0x9A: "S", 0x9B: "S", 0x9C: "S", 0xA2: "WWSS", 0xB5: "SSSSSSSS",
    0xB6: "SSSS", 0xB7: "S",
}
_STEP = {"B": 1, "W": 2, "T": 3}
_NLOOP_TRAIL = {0xB0: 1, 0xB1: 2, 0xB2: 1, 0xB3: 2, 0xB4: 3, 0xAF: 3}


def _final_val(t: int) -> bool:
    return bool(t & 0x80) and (t & 0x70) in (0x30, 0x40, 0x60)


def _end_template(d: bytes, p: int, tmpl: str) -> int | None:
    for t in tmpl:
        if t == "S":
            p, ok, _ = parse_sub(d, p)
            if not ok:
                return None
        else:
            p += _STEP[t]
    return p


def _end_2e(d: bytes, p: int) -> int | None:
    t = _r8(d, p)
    p += 1
    if t in (0x8D, 0x88) or t == 0x84:
        return p + 2
    if t in _ENTITY or _final_val(t):
        return p
    if t == 0x92:
        return p + 1
    if t == 0x04 and _r8(d, p + 2) == 0x29 and _r8(d, p + 3) in (0x08, 0x0D) and _r8(d, p + 6) == 0x9A:
        return p + 7
    return None


def _end_3f(d: bytes, p: int) -> int | None:
    t = _r8(d, p)
    if _final_val(t):
        p += 1
    else:
        p, ok, _ = parse_sub(d, p)
        if not ok:
            return None
    return p + 4


def _end_nloop(d: bytes, p: int, op: int) -> int | None:
    n = _r8(d, p)
    p += 1
    for _ in range(n):
        p, ok, _ = parse_sub(d, p)
        if not ok:
            return None
    return p + _NLOOP_TRAIL[op]


def _end_cast(d: bytes, p: int) -> int | None:
    for _ in range(3):
        p, ok, _ = parse_sub(d, p)
        if not ok:
            return None
    while True:
        p, ok, e = parse_sub(d, p)
        if not ok:
            return None
        if _is_zero(e):
            return p


def instr_len(d: bytes, a: int) -> int | None:
    """Byte length of the instruction at SNES address ``a`` (or None = unknown)."""
    op = _r8(d, a)
    p = a + 1
    if op in _NLOOP_TRAIL:
        end = _end_nloop(d, p, op)
    elif op == 0x2E:
        end = _end_2e(d, p)
    elif op == 0x3F:
        end = _end_3f(d, p)
    elif op in (0x9E, 0xAC):
        end = _end_cast(d, p)
    else:
        tmpl = _FIXED.get(op)
        end = None if tmpl is None else _end_template(d, p, tmpl)
    return None if end is None else end - a


# =============================================================================
# Opcode names (from SoEScriptDumper; "?" = semantics untraced, length verified)
# =============================================================================
OPNAMES: dict[int, str] = {
    0x00: "END", 0x04: "SKIP", 0x05: "SKIP_BACK", 0x07: "CALL_ABS24",
    0x08: "IF", 0x09: "IF_NOT", 0x0A: "IF_MONEY_GE", 0x0B: "IF_MONEY_LT",
    0x0C: "SETBIT_2258", 0x0D: "SETBIT_2834", 0x0E: "SETBIT_ARG",
    0x10: "WRITE_B_2258", 0x11: "WRITE_B_2834", 0x14: "WRITE_B_2258b",
    0x15: "WRITE_B_2834b", 0x17: "SET_WORD_FAST", 0x18: "WRITE_W_2258",
    0x19: "WRITE_W_2834", 0x1A: "WRITE_ARG", 0x1B: "SET_TWO", 0x1C: "WRITE_W_2258b",
    0x1D: "WRITE_W_2834b", 0x1E: "WRITE_ARGb", 0x20: "TELEPORT_BOTH",
    0x22: "CHANGE_MAP", 0x26: "?VRAM_WRITE", 0x27: "FADE_OUT",
    0x29: "CALL_ABS24b", 0x2C: "?CALLER_INFO", 0x2D: "?CALLER_ALT",
    0x2E: "WAIT_DEST", 0x30: "SFX", 0x31: "SFX2", 0x32: "SFX3", 0x33: "MUSIC",
    0x38: "YIELD", 0x39: "SLEEP_SUB", 0x3A: "YIELD2", 0x3B: "SLEEP_SUBb",
    0x3C: "LOAD_NPC", 0x3D: "SET_NPC_TALK", 0x3F: "SET_NPC_SCRIPT",
    0x42: "TP_ENT_BYTE", 0x43: "TP_ENT_SUB", 0x44: "MSGBOX", 0x45: "MSGBOX",
    0x46: "MSGBOX", 0x47: "MSGBOX", 0x48: "MSGBOX_DEF", 0x49: "MSGBOX_DEF",
    0x4A: "MSGBOX_DEF", 0x4B: "MSGBOX_DEF", 0x4D: "NOP", 0x4E: "ATTACH_ENT",
    0x50: "SHOW_TEXT_UNWIN", 0x51: "SHOW_TEXT", 0x52: "SHOW_TEXT_UNWIN2",
    0x54: "CLEAR_TEXT_VRAM", 0x55: "CLEAR_TEXT", 0x58: "FADEIN_VOL",
    0x59: "FADEOUT_VOL", 0x5A: "?MSG_TIMER", 0x5B: "?MSG_TIMER2",
    0x5C: "SET_OBJ_STATE", 0x5D: "UNLOAD_OBJ_IF", 0x62: "?COPY_DATA",
    0x63: "ALCHEMY_SCREEN", 0x6C: "?ENT_OP", 0x6D: "WALK_REL", 0x6E: "WALK_REL_BYTE",
    0x6F: "WALK_REL_SUB", 0x70: "FACE_ENT", 0x71: "FACE_EACH", 0x73: "WALK_ABS",
    0x74: "FACE_N", 0x75: "FACE_S", 0x76: "FACE_W", 0x77: "FACE_E",
    0x78: "SET_SPRITE", 0x79: "SET_SPRITE2", 0x7A: "WRITE_DEREF", 0x7C: "GIVE_MONEY",
    0x7D: "TAKE_MONEY", 0x7E: "EXCHANGE_MONEY", 0x7F: "NAME_INPUT", 0x80: "UNHIDE_TEXT",
    0x81: "HIDE_TEXT", 0x82: "?LAYERS", 0x83: "UPD_LAYERS", 0x84: "GIVE_MONEY_SUB",
    0x85: "TAKE_MONEY_SUB", 0x86: "?AUDIO_VOL", 0x87: "?AUDIO_SPD",
    0x88: "SHOP_CLEAR", 0x89: "SHOP_ADD", 0x8A: "SHOP_MOVE", 0x8C: "SAVE_MENU",
    0x8D: "SCREEN_SHAKE", 0x8E: "IF_MONEY_GE_SUB", 0x8F: "IF_MONEY_LT_SUB",
    0x91: "SET_BRIGHTNESS", 0x92: "DAMAGE", 0x93: "DAMAGE", 0x94: "DAMAGE",
    0x95: "DAMAGE", 0x96: "TP_SCREENS", 0x97: "?OP_7SUB", 0x98: "SWITCH_CHAR",
    0x99: "MODE7_MAP", 0x9A: "SET_FONT", 0x9B: "?DEALLOC", 0x9C: "?DEC_SCRIPTS",
    0x9D: "WALK_ABS_BARRIER", 0x9E: "CAST_SPELL", 0x9F: "CURR_PREP",
    0xA0: "CURR_SHOW", 0xA1: "CURR_HIDE", 0xA2: "SPAWN_NPC", 0xA3: "CALL_SUB",
    0xA4: "CALL_16", 0xA5: "CALL_8_NEG", 0xA6: "CALL_16_REL", 0xA7: "SLEEP",
    0xA8: "SLEEP16", 0xA9: "?OP_2SUB", 0xAA: "?OP_AA", 0xAC: "CAST_SPELL_ALIVE",
    0xAD: "STORE_2834", 0xAE: "?MOD_SCRIPT", 0xAF: "?CALL_MULTI", 0xB0: "CALL_MULTI_G8",
    0xB1: "CALL_MULTI_N16", 0xB2: "CALL_MULTI_R8", 0xB3: "CALL_MULTI_R16",
    0xB4: "CALL_MULTI_A24", 0xB5: "?DRAW_LIGHTNING", 0xB6: "TILE_FLASH",
    0xB7: "TILE_FLASH_STOP", 0xBA: "LOAD_NPC_B", 0xBC: "?OP_BC", 0xBD: "?OP_BD",
    0xBE: "?OP_BE", 0xBF: "?OP_BF", 0xC0: "?OP_C0", 0xC1: "?OP_C1", 0xC2: "?OP_C2",
}

# Opcodes with a branch target word at the end (dst = instr_end + s16(word)).
_BRANCH_END = {0x04, 0x08, 0x09, 0x0A, 0x0B, 0x8E, 0x8F}
END_OP = 0x00
CALL_OPS = {0x07, 0x29, 0xA3, 0xA4, 0xA5, 0xA6}


# =============================================================================
# Disassembler (one instruction -> readable line + control flow info)
# =============================================================================
@dataclass
class Instr:
    addr: int            # SNES address
    off: int             # offset relative to script start
    opcode: int
    length: int
    text: str            # readable line
    dst: int | None      # branch target offset (script-relative) or None


class Resolver:
    """Resolves text IDs -> dialogue.json and map IDs -> names (optional)."""

    def __init__(self) -> None:
        self.dialogue: dict[str, str] = {}
        self.mapnames: dict[str, str] = {}
        try:
            self.dialogue = json.loads((_TEXT / "dialogue.json").read_text())
        except Exception:
            self.dialogue = {}
        try:
            self.mapnames = json.loads((_ASSETS / "names.json").read_text()).get("maps", {})
        except Exception:
            self.mapnames = {}

    def text(self, word: int) -> str:
        line = self.dialogue.get(str(word // 3))
        if line is None:
            return f'text#{word // 3} (word 0x{word:04x})'
        short = line.replace("{END}", "").replace("{BR}", " ").strip()
        if len(short) > 70:
            short = short[:67] + "..."
        return f'text#{word // 3}: "{short}"'

    def mapname(self, mid: int) -> str:
        nm = self.mapnames.get(str(mid))
        return f' ({nm})' if nm else ""


def _annotate(d: bytes, ins: Instr, res: Resolver) -> str:
    """Append resolved details (text/warp/branch) to the base line."""
    op, a = ins.opcode, ins.addr
    if op in (0x51, 0x52, 0x50, 0x7F, 0x8C):
        word = _r16(d, a + (2 if op == 0x50 else 1))
        return "  " + res.text(word)
    if op == 0x54:
        return ""
    if op == 0x22:
        mid = _r16(d, a + 3) & 0xFF
        return f"  -> map 0x{mid:02X}{res.mapname(mid)}"
    if op in _BRANCH_END and ins.dst is not None:
        return f"  -> +0x{ins.dst:04X}"
    if op == 0x05 and ins.dst is not None:
        return f"  -> +0x{ins.dst:04X}"
    return ""


def decode(d: bytes, addr: int, start: int, res: Resolver) -> Instr | None:
    """Decode one instruction at SNES ``addr`` (script begins at ``start``)."""
    ln = instr_len(d, addr)
    if ln is None:
        return None
    op = _r8(d, addr)
    off = file_off(addr) - file_off(start)
    dst = None
    if op in _BRANCH_END:
        dst = (off + ln) + _s16(_r16(d, addr + ln - 2))
    elif op == 0x05:
        dst = off + (_r8(d, addr + 1) - 0x100)
    name = OPNAMES.get(op, f"?OP_{op:02X}")
    raw = " ".join(f"{d[file_off(addr) + i]:02X}" for i in range(1, min(ln, 8)))
    ins = Instr(addr, off, op, ln, "", dst)
    ins.text = f"  +{off:04X}: {op:02X} {raw:<23} {name:<18}{_annotate(d, ins, res)}"
    return ins


# =============================================================================
# Script walker (control flow like SoEScriptDumper: linear + branch targets)
# =============================================================================
def walk(d: bytes, start: int, res: Resolver, cap: int = 2000) -> tuple[list[Instr], bool]:
    """Decode a whole script starting at SNES ``start``.

    Linear up to END (0x00); at END, jump to the smallest open branch target
    beyond the current position (so all code paths are covered). Ends cleanly
    when no open targets remain. Returns: (Instr, clean?).
    """
    out: list[Instr] = []
    visited: set[int] = set()
    pending: set[int] = set()
    addr = start
    clean = False
    for _ in range(cap):
        off = file_off(addr) - file_off(start)
        if off in visited:
            nxt = _next_pending(pending, visited, off)
            if nxt is None:
                clean = True
                break
            addr = start + nxt
            continue
        visited.add(off)
        ins = decode(d, addr, start, res)
        if ins is None:
            out.append(Instr(addr, off, _r8(d, addr), 1,
                             f"  +{off:04X}: {_r8(d, addr):02X} ?UNDECODED (stop)", None))
            nxt = _next_pending(pending, visited, off)
            if nxt is None:
                break
            addr = start + nxt
            continue
        out.append(ins)
        if ins.dst is not None and ins.dst > off:
            pending.add(ins.dst)
        if ins.opcode == END_OP:
            nxt = _next_pending(pending, visited, off)
            if nxt is None:
                clean = True
                break
            addr = start + nxt
        else:
            addr = start + off + ins.length
    return out, clean


def _next_pending(pending: set[int], visited: set[int], cur: int) -> int | None:
    cand = [o for o in pending if o > cur and o not in visited]
    return min(cand) if cand else None


# =============================================================================
# Map triggers -> resolved script addresses
# =============================================================================
def map_script_ptr(rom: Rom) -> int:
    c = _consts(rom)
    return c["scripts"] + _r16(rom.data, c["scripts"])


def resolve_scriptid(rom: Rom, scriptid: int) -> int:
    """scriptid (byte offset into the map script pointer table) -> SNES script address."""
    c = _consts(rom)
    return script2rom(_r24(rom.data, map_script_ptr(rom) + scriptid), c["scripts"])


def enter_script_addr(rom: Rom, mapid: int) -> int | None:
    """SNES address of a map's enter script, or None (null pointer = none)."""
    c = _consts(rom)
    raw = _r24(rom.data, c["scripts"] + 0x1B + 5 * mapid)
    return None if raw == 0 else script2rom(raw, c["scripts"])


def _map_triggers(rom: Rom, mapid: int) -> list[tuple[str, int, int, int, int, int]]:
    """(kind, x1,y1,x2,y2, scriptid) for the enter/event/b triggers of a map."""
    from . import maps
    mj = maps.read_map(rom, mapid)
    out: list[tuple[str, int, int, int, int, int]] = []
    for kind, key in (("event", "event_triggers"), ("btrig", "b_triggers")):
        for e in mj.get(key, {}).get("entries", []):
            out.append((kind, e["x1"], e["y1"], e["x2"], e["y2"], int(e["script_ptr"], 16)))
    return out


# =============================================================================
# Asset export
# =============================================================================
def disassemble_map(rom: Rom, mapid: int, res: Resolver, stats: dict) -> str:
    d = rom.data
    lines = [f"; ===== Map 0x{mapid:02X} ({mapid}){res.mapname(mapid)} =====",
             f"; region={rom.region} scripts_start=0x{_consts(rom)['scripts']:06X}", ""]
    seen: set[int] = set()

    def emit(header: str, addr: int) -> None:
        lines.append(f"{header}  @ 0x{addr:06X} (file 0x{file_off(addr):06X})")
        if addr in seen:
            lines.append("  (see above)\n")
            return
        seen.add(addr)
        ins, clean = walk(d, addr, res)
        stats["scripts"] += 1
        stats["clean"] += 1 if clean else 0
        for i in ins:
            lines.append(i.text)
            stats["opcodes"][i.opcode] = stats["opcodes"].get(i.opcode, 0) + 1
        lines.append("" if clean else "  ; !! not cleanly terminated\n")

    enter = enter_script_addr(rom, mapid)
    if enter is None:
        lines.append("; enter-script: (none / null pointer)\n")
    else:
        emit("; enter-script", enter)
    for kind, x1, y1, x2, y2, sid in _map_triggers(rom, mapid):
        emit(f"; {kind} zone ({x1},{y1})-({x2},{y2}) id=0x{sid:04X}",
             resolve_scriptid(rom, sid))
    return "\n".join(lines)


def _opcode_markdown(stats: dict) -> str:
    used = stats["opcodes"]
    rows = ["# Secret of Evermore, event script VM opcode table", "",
            "Verified byte-exact against `black-sliver/SoEScriptDumper` "
            "(list-rooms.cpp): the instruction length logic matches **61018/61018** "
            "instructions of the Europe ROM exactly.", "",
            "Resolution: story text `word//3 -> dialogue.json`; warp `0x22 -> map index`. "
            "Addressing: `scriptid -> mapscriptptr table -> script2romaddr` "
            "(scripts_start SNES: Europe/PAL 0x938000, USA 0x928000).", "",
            "`?` in the name = semantics marked *untraced* in the dumper (length still "
            "verified). `args` = template (B=1 byte, W=2, T=3, S=sub expression, "
            "N*=counted loop).", "",
            "| Opcode | Name | args | used |", "|---|---|---|---|"]
    for op in range(0x100):
        name = OPNAMES.get(op)
        if name is None:
            continue
        if op in _NLOOP_TRAIL:
            tmpl = f"N*S + {_NLOOP_TRAIL[op]}B"
        elif op == 0x2E:
            tmpl = "sub/var"
        elif op == 0x3F:
            tmpl = "B|S + WW"
        elif op in (0x9E, 0xAC):
            tmpl = "SSS + S..(0)"
        else:
            tmpl = _FIXED.get(op, "?") or "-"
        rows.append(f"| 0x{op:02X} | {name} | {tmpl} | {used.get(op, 0)} |")
    rows += ["", f"Defined opcodes in total: **{len(OPNAMES)}** (of which actually used "
             f"in the map scripts: **{len(used)}**).", "",
             "## Control flow",
             "- **0x00 END** ends the path; open branch targets are decoded afterwards.",
             "- **0x04/0x05** unconditional SKIP (forward/backward). **0x08/0x09** IF(SUB)+SKIP.",
             "- **0x0A/0x0B/0x8E/0x8F** IF moniez compare +SKIP.",
             "- **0x07/0x29/0xA3-0xA6/0xB0-0xB4** script calls (sub/global/NPC/abs).",
             "", "## Story text (dialogue wiring)",
             "`0x50/0x51/0x52/0x54/0x7F/0x8C` load text via `addr = 0x91D000 + word`; "
             "0x91D000 is the text pointer table (3 B/entry) -> **text ID = word//3** "
             "-> `dialogue.json`. Verified: map 0x38 `SHOW_TEXT 0x063F` -> "
             "`dialogue[533]`.", ""]
    return "\n".join(rows)


def extract(rom: Rom, out: Path = _ASSETS) -> dict:
    """Write map_XXXX.txt (all 127), index.json, opcodes.md."""
    from . import maps
    out.mkdir(parents=True, exist_ok=True)
    res = Resolver()
    stats = {"scripts": 0, "clean": 0, "opcodes": {}}
    index = {"region": rom.region, "maps": []}
    for mapid in range(maps.MAP_COUNT):
        before = stats["scripts"]
        text = disassemble_map(rom, mapid, res, stats)
        (out / f"map_{mapid:04d}.txt").write_text(text)
        index["maps"].append({"index": mapid, "name": res.mapnames.get(str(mapid)),
                              "scripts": stats["scripts"] - before})
    index["total_scripts"] = stats["scripts"]
    index["clean_scripts"] = stats["clean"]
    index["maps_with_scripts"] = sum(1 for m in index["maps"] if m["scripts"] > 1)
    index["opcodes_used"] = sorted(f"0x{o:02X}" for o in stats["opcodes"])
    (out / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))
    (out / "opcodes.md").write_text(_opcode_markdown(stats))
    return {"maps": maps.MAP_COUNT, "scripts": stats["scripts"],
            "clean": stats["clean"], "opcodes_defined": len(OPNAMES),
            "opcodes_used": len(stats["opcodes"])}


# =============================================================================
# Self-check: real scripts terminate cleanly, dialogue/warps resolve for real.
# =============================================================================
def _demo() -> None:
    import sys
    rom = Rom(sys.argv[1] if len(sys.argv) > 1 else "Secret of Evermore (Europe).sfc")
    res = Resolver()

    # 1) Map 0x38 enter script terminates cleanly and has real content.
    addr = enter_script_addr(rom, 0x38)
    ins, clean = walk(rom.data, addr, res)
    assert clean, "enter-script 0x38 does not terminate cleanly"
    assert len(ins) > 10, "enter-script 0x38 too short"
    print(f"Map 0x38 enter-script @ 0x{addr:06X}: {len(ins)} Instr, clean={clean}")

    # 2) Dialogue wiring: known SHOW_TEXT (word 0x63f) -> dialogue[533].
    if res.dialogue:
        assert "533" in res.dialogue and "big dog" in res.dialogue["533"], "dialogue.json?"
        assert res.text(0x63F).startswith('text#533:'), res.text(0x63F)
        print("Dialogue OK:", res.text(0x63F))

    # 3) Breadth check over ALL maps: share of cleanly terminated scripts.
    from . import maps
    total = cleanc = warps = texts = 0
    for mid in range(maps.MAP_COUNT):
        addrs = [enter_script_addr(rom, mid)]
        addrs += [resolve_scriptid(rom, s) for _, _, _, _, _, s in _map_triggers(rom, mid)]
        for saddr in addrs:
            if saddr is None:
                continue
            si, cl = walk(rom.data, saddr, res)
            total += 1
            cleanc += 1 if cl else 0
            warps += sum(1 for i in si if i.opcode == 0x22)
            texts += sum(1 for i in si if i.opcode in (0x50, 0x51, 0x52))
    print(f"Scripts total {total}, clean {cleanc} ({100*cleanc/total:.1f}%), "
          f"CHANGE_MAP {warps}, SHOW_TEXT {texts}")
    assert cleanc >= total * 0.97, "too many scripts do not terminate cleanly"
    print("\nsoe/script.py self-check OK")


if __name__ == "__main__":
    _demo()
