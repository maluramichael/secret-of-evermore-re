"""Static, reproducible Boy sprite decoder from the ROM (Europe/PAL).

Implements the render chain documented in docs/sprites.md as a data decoder.
Nothing is guessed: every offset and format is derived from the actual 65816 code
in the ROM (sprite_compose $809032, gfx-load $8096FD) and checked against the
ROM bytes.

Render chain (verified)
-----------------------
An actor frame is a **metasprite** (SoE's own OAM format), read by sprite_compose
$809032 through pointer [$26]:

  metasprite = count:u8 + dataoff:u8 + count * chunk[5]
  chunk      = flags:u8, x:i8, y:i8, block:u16
             flags bit0 = OBJ size / path select; upper bits -> OAM attr (h/v flip, pal)
             x/y        = screen offset of the 16x16 sprite (relative to the actor anchor)
             block      = index into the SpriteBlock 16x16 table

block -> graphics (gfx-load $8096FD, $80973A ff):
  entry = SPRITEBLOCK_TABLE[block*3]  (3 bytes)
  off  = u16(byte0, byte1)
  bank = (byte2 & 0x7F) + 0x5A
  compressed = bit7(byte2)
  addr = bank<<16 | off   (file = addr & 0x3FFFFF)
  compressed -> soe.lz.decompress_sprite (zero-word-skip codec) -> 128 B
  else       -> raw 128 B
  128 B = 16x16 4bpp = 4 8x8 tiles (TL,TR,BL,BR in the 8x8 4bpp layout of Rom.decode_4bpp)

Frame enumeration (verified)
----------------------------
* The player-controlled Boy is NOT rendered through $7E4EF7/$CD3F03 (that is the
  1-chunk party Boy) but through anim scripts in bank $C8, addressed via the action
  table $C4452E (BOY_ACTIONS: stand/walk/run/attack for up/right/down/left). Each
  script frame names its metasprites (bank $CB) and its duration.
* Chunk flags bit0 selects the graphics table: 0 -> 8x8 blocks from $D90000,
  1 -> 16x16 from $EE0000. A Boy frame mixes both (small parts for hands/feet/head,
  16x16 for the torso).
* Stand frames consist of two layers (opcode $2C = layer 1 + $22 = layer 2),
  walk/run only of layer 2.

`compose_metasprite(rom, bank, off)` returns a frame at its REAL size (variable,
not forced into a 16x16/16x32 grid), plus its origin (actor anchor).
Details: docs/sprites.md.
"""
from __future__ import annotations

from .rom import Rom
from . import lz

# Two SpriteBlock pointer tables, selected by chunk flags bit0 (verified from
# $809117 ROR/BCC, $80A4FB LDA $D90001,X and $80973A LDA $EE0000,X; index = block*3,
# no base is EVER added):
#   bit0 = 1 -> 16x16 path (compose_variant_16 $8091FC, gfx-load $8096FD): table $EE0000,
#               bank = (byte2 & 0x7F) + 0x5A, 128 B per block.
#   bit0 = 0 -> 8x8 path   (compose_emit_loop $80911D,  gfx-load $80A4B4): table $D90000,
#               bank = (byte2 & 0x7F) + 0x52, 32 B per block.
# bit7 of byte2 = compressed (zero-word-skip codec) in both tables.
SPRITEBLOCK_TABLE = 0x2E0000     # SNES $EE0000, file offset (16x16)
BLOCK_BANK_BASE = 0x5A           # bank = (byte2 & 0x7F) + 0x5A
BLOCK_BYTES = 128                # 16x16 4bpp
SPRITEBLOCK_TABLE_8 = 0x190000   # SNES $D90000, file offset (8x8)
BLOCK_BANK_BASE_8 = 0x52         # bank = (byte2 & 0x7F) + 0x52
BLOCK_BYTES_8 = 32               # 8x8 4bpp
BOY_STAND_METASPRITE = (0xCD, 0x3F03)   # bank, off
BOY_BLOCK_RANGE = (0x0795, 0x07F1)      # blocks that resolve into the Boy graphics region


def resolve_block(rom: Rom, block: int, small: bool = False) -> tuple[int, bool]:
    """block:u16 -> (file_addr, compressed). small=True: 8x8 table $D90000, else $EE0000."""
    table, base = (SPRITEBLOCK_TABLE_8, BLOCK_BANK_BASE_8) if small else (SPRITEBLOCK_TABLE, BLOCK_BANK_BASE)
    e = table + block * 3
    d = rom.data
    off = d[e] | (d[e + 1] << 8)
    hi = d[e + 2]
    bank = (hi & 0x7F) + base
    addr = ((bank << 16) | off) & 0x3FFFFF
    return addr, bool(hi & 0x80)


def decode_block(rom: Rom, block: int, small: bool = False) -> list[list[int]]:
    """One block as a palette index grid (0..15): 16x16 (4 8x8 tiles TL,TR,BL,BR) or 8x8."""
    addr, comp = resolve_block(rom, block, small)
    n = BLOCK_BYTES_8 if small else BLOCK_BYTES
    if comp:
        raw, _ = lz.decompress_sprite(rom.data, addr, n)
    else:
        raw = rom.data[addr:addr + n]
    if small:
        return rom.decode_4bpp(raw)
    grid = [[0] * 16 for _ in range(16)]
    for qi, (qx, qy) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
        tile = rom.decode_4bpp(raw[qi * 32:qi * 32 + 32])
        for y in range(8):
            for x in range(8):
                grid[qy * 8 + y][qx * 8 + x] = tile[y][x]
    return grid


def decode_metasprite(rom: Rom, bank: int, off: int) -> dict:
    """Metasprite (SpriteInfo) @ bank:off -> {count, dataoff, chunks:[{flags,x,y,block}]}."""
    base = ((bank << 16) | off) & 0x3FFFFF
    d = rom.data
    count = d[base]
    dataoff = d[base + 1]
    chunks = []
    for i in range(count):
        c = base + dataoff + i * 5
        flags = d[c]
        x = d[c + 1] - 256 if d[c + 1] >= 128 else d[c + 1]
        y = d[c + 2] - 256 if d[c + 2] >= 128 else d[c + 2]
        block = d[c + 3] | (d[c + 4] << 8)
        chunks.append({"flags": flags, "x": x, "y": y, "block": block})
    return {"count": count, "dataoff": dataoff, "chunks": chunks}


def compose_metasprite(rom: Rom, bank: int, off: int) -> dict:
    """Compose a frame at its REAL size from its chunks.

    Returns {grid, w, h, origin, chunks}. `grid` = palette index grid (0=transparent),
    `origin` = (ax, ay) = position of the actor anchor (chunk offset (0,0)) in the grid,
    so the frame can be aligned to its world position. flags:
    bit0 = 0 -> 8x8 chunk (table $D90000), 1 -> 16x16 chunk (table $EE0000);
    bit6 (0x40) = h-flip, bit7 (0x80) = v-flip (SNES OAM attr convention).
    Chunk order = OAM slot order; a lower OAM slot is in FRONT (SNES priority).
    Drawing therefore runs backwards: chunk 0 last, i.e. on top
    (verified against an OAM dump: slots 14..17 = layer 2 chunks 0..3).
    """
    ms = decode_metasprite(rom, bank, off)
    return compose_chunks(rom, ms["chunks"])


def compose_chunks(rom: Rom, chunks: list[dict]) -> dict:
    """Like compose_metasprite, but for an arbitrary chunk list (e.g. two layers)."""
    if not chunks:
        return {"grid": [], "w": 0, "h": 0, "origin": (0, 0), "chunks": []}
    sz = [16 if c["flags"] & 1 else 8 for c in chunks]
    minx = min(c["x"] for c in chunks)
    miny = min(c["y"] for c in chunks)
    w = max(c["x"] + s for c, s in zip(chunks, sz)) - minx
    h = max(c["y"] + s for c, s in zip(chunks, sz)) - miny
    grid = [[0] * w for _ in range(h)]
    for c, s in reversed(list(zip(chunks, sz))):
        blk = decode_block(rom, c["block"], small=(s == 8))
        hf = bool(c["flags"] & 0x40)
        vf = bool(c["flags"] & 0x80)
        bx, by = c["x"] - minx, c["y"] - miny
        for y in range(s):
            for x in range(s):
                v = blk[s - 1 - y if vf else y][s - 1 - x if hf else x]
                if v:
                    grid[by + y][bx + x] = v
    return {"grid": grid, "w": w, "h": h, "origin": (-minx, -miny), "chunks": chunks}


# ---------------------------------------------------------------------------
# Anim scripts: bytecode VM in bank $D0 (dispatcher $D080D2, jump table $D08000)
# reads a script cursor per entity (entity+0x00/+0x01, bank +0x02) and writes the
# metasprite pointers of the current frame into the entity: opcode $2C -> entity+0x09..0x0B
# (layer 1, 3 bytes lo/hi/bank literal, handler $D08434), opcodes $22..$2B -> entity+0x06..0x08
# (layer 2, 2 bytes lo/hi, bank = opcode + $A9, handler $D0841D). The display list builder
# ($CFC662 ff.) enters both layers as nodes into the Y-sorted list ($809609 insert),
# the walker $C096BA renders each node through the sprite_compose re-entry $80903F.
# The Boy scripts live in bank $C8; frame duration = opcode $00..$1F (N frames, measured
# by trace: 8,8,7,8,8,6 for walk-up = exactly the script bytes).
# Order per action: up, right, down, left (walk measured by trace, stand/run follow
# the same layout: 4 scripts in a row).
# Boy action table: $C4452E, 16 B per action = 4 directions (up/right/down/left) x
# {addr:u16, bank:u8, flag:u8}. Script selection sets cursor + loop marker ($D0817F/$D08182)
# to the entry (measured: walk up -> $C81206, attack down -> $C81484).
# Every script starts with the reset opcode $52.
BOY_ACTION_TABLE = 0x04452E      # file offset of $C4452E
BOY_ACTIONS = {"stand": 5, "walk": 6, "run": 7, "attack": 10}   # group index in the table
DIRECTIONS = ("up", "right", "down", "left")
# Opcode semantics (handlers via jump table $D08000, index = op & 0x7F; bit7 = tick end):
#   $01..$1E wait N frames (handler $D08371: entity+5 = N, cursor persists)
#   $22..$2B layer 2 pointer (2 B), $2C layer 1 pointer (3 B), $30 set loop marker
#   $41/$C1 stop movement (0 B), $42/$C2 move by operand (1 B, signed)
#   $4D parameter -> entity+0x16 (2 B, speed: walk 4, run 12)
#   $52 script start marker (0 B; the selection routine sets cursor + loop marker here)
#   $53/$D3 loop jump to entity+3/4 (0 B; costs one tick = 1 extra frame at cycle end, measured)
#   $1F computed wait time (2 B), $2E SFX/effect (1 B), $3F direction effect (2 B), $47 arc
#   movement (4 B), $48 collision check (0 B), $4E direction=0 (0 B), $4F flags (0 B), $54 conditional
#   jump (2 B). (Handlers: docs/sprites.md.)
#   $21 no-op (handler $D08790 = bare RTS; no operand), $5B trigger (handler $D085C6 copies
#   entity+0x1A/+0x1C/+0x22 to $0FCC/$0FCE/$0FD0, reads no cursor operand). Both 0 B,
#   verified by disassembling the jump table $D08000 (opcode handler lengths).
_OPLEN = {0x1F: 2, 0x21: 0, 0x2E: 1, 0x30: 0, 0x52: 0, 0x3F: 2, 0x41: 0, 0x42: 1, 0x43: 0, 0x47: 4,
          0x48: 0, 0x4D: 2, 0x4E: 0, 0x4F: 0, 0x54: 2, 0x5B: 0, 0xC1: 0, 0xC2: 1, 0xC3: 0}
LOOP_OVERHEAD_FRAMES = 1


def parse_anim_script(rom: Rom, bank: int, off: int, max_bytes: int = 256) -> dict:
    """Script @ bank:off -> {frames:[{layers:[(bank,off)|None, (bank,off)|None], duration}], end}.

    frames[i].layers = [layer1 ($2C, entity+0x09), layer2 ($22.., entity+0x06)]; a frame
    is created at every wait opcode $01..$1E with the pointers set so far. Starts
    with the marker $52, ends at the loop opcode $D3 (jump to the loop marker = script start).
    """
    d = rom.data
    p = ((bank << 16) | off) & 0x3FFFFF
    end = p + max_bytes
    layers: list = [None, None]
    frames = []
    while p < end:
        op = d[p]
        p += 1
        if 0x01 <= op <= 0x1E:
            frames.append({"layers": list(layers), "duration": op})
        elif 0x22 <= op <= 0x2B:
            layers[1] = (op + 0xA9, d[p] | (d[p + 1] << 8))
            p += 2
        elif op == 0x2C:
            layers[0] = (d[p + 2], d[p] | (d[p + 1] << 8))
            p += 3
        elif op == 0xD3:
            return {"frames": frames, "end": p - (((bank << 16) | off) & 0x3FFFFF), "loop": True}
        elif op in _OPLEN:
            p += _OPLEN[op]
        else:
            raise ValueError(f"unknown anim opcode ${op:02X} @ ${bank:02X}{off:04X}+{p - 1 - (((bank << 16) | off) & 0x3FFFFF)}")
    raise ValueError(f"anim script without end @ ${bank:02X}{off:04X}")


def boy_action_scripts(rom: Rom, action: int) -> dict:
    """Action #action of the table $C4452E -> {direction: (bank, off)}."""
    d = rom.data
    out = {}
    for i, direction in enumerate(DIRECTIONS):
        e = BOY_ACTION_TABLE + action * 16 + i * 4
        out[direction] = (d[e + 2], d[e] | (d[e + 1] << 8))
    return out


def boy_animations(rom: Rom) -> dict:
    """{state: {direction: {"script": "C8:xxxx", "frames": [...], "loop": bool}}} purely from the ROM."""
    out = {}
    for state, action in BOY_ACTIONS.items():
        out[state] = {}
        for direction, (bank, off) in boy_action_scripts(rom, action).items():
            sc = parse_anim_script(rom, bank, off)
            out[state][direction] = {"script": f"{bank:02X}:{off:04X}", **sc}
    return out


def compose_frame(rom: Rom, layers) -> dict:
    """Compose an anim frame from its layers in OAM order: layer 2 (entity+0x06,
    earlier in the display list, lower OAM slots = in front) before layer 1 (entity+0x09).
    Verified against an OAM dump: slots 14..17 = $CB10F7 (layer 2), 18..19 = $CB10EB (layer 1)."""
    chunks = []
    for lay in (layers[1], layers[0]):
        if lay:
            chunks += decode_metasprite(rom, *lay)["chunks"]
    return compose_chunks(rom, chunks)


def _selftest(rom: Rom) -> None:
    # (1) block resolution: Boy stand block 0x07AB -> file 0x214A5A, compressed.
    addr, comp = resolve_block(rom, 0x07AB)
    assert addr == 0x214A5A and comp, f"block 0x07AB resolved wrongly: {addr:#08x} comp={comp}"

    # (2) all Boy blocks decode to 16x16 with content.
    lo, hi = BOY_BLOCK_RANGE
    for b in (lo, 0x07AB, 0x07B0, hi):
        g = decode_block(rom, b)
        assert len(g) == 16 and len(g[0]) == 16, f"block {b:#x} is not 16x16"
        assert sum(v for row in g for v in row) > 0, f"block {b:#x} empty"

    # (3) decode the stand metasprite: 1 chunk, block 0x07AB.
    ms = decode_metasprite(rom, *BOY_STAND_METASPRITE)
    assert ms["count"] == 1 and ms["chunks"][0]["block"] == 0x07AB, f"stand metasprite wrong: {ms}"

    # (4) compose: real size, not forced into the grid, with content.
    fr = compose_metasprite(rom, *BOY_STAND_METASPRITE)
    assert fr["w"] >= 16 and fr["h"] >= 16, f"frame too small: {fr['w']}x{fr['h']}"
    assert any(v for row in fr["grid"] for v in row), "frame empty"

    # (5) 8x8 path: walk-up frame 1 ($CB114B) mixes 8x8 and 16x16 chunks, renders non-empty.
    fr8 = compose_metasprite(rom, 0xCB, 0x114B)
    assert any((c["flags"] & 1) == 0 for c in fr8["chunks"]) and any(c["flags"] & 1 for c in fr8["chunks"])
    assert sum(1 for row in fr8["grid"] for v in row if v) > 150, "walk-up frame 1 nearly empty"

    # (6) Anim scripts: walk-up = 6 frames with durations 8,8,7,8,8,6 (measured by trace).
    an = boy_animations(rom)
    wu = an["walk"]["up"]
    assert [f["duration"] for f in wu["frames"]] == [8, 8, 7, 8, 8, 6], wu
    assert [f["layers"][1] for f in wu["frames"]] == [(0xCB, o) for o in (0x114B, 0x1165, 0x117A, 0x118F, 0x11AE, 0x11C3)], wu
    assert an["walk"]["up"]["script"] == "C8:1206" and an["stand"]["down"]["script"] == "C8:11EA"
    assert an["attack"]["down"]["script"] == "C8:1484", an["attack"]["down"]["script"]
    st = an["stand"]["down"]["frames"]
    assert len(st) == 1 and st[0]["layers"] == [(0xCB, 0x10EB), (0xCB, 0x10F7)] and st[0]["duration"] == 9, st
    for state in an:
        for direction in DIRECTIONS:
            assert an[state][direction]["frames"], f"{state}/{direction} without frames"

    print(f"boysprites selftest ok (block 0x07AB @0x{addr:06X} comp={comp}; "
          f"stand-metasprite $CD3F03 -> {fr['w']}x{fr['h']} px, origin {fr['origin']})")


if __name__ == "__main__":
    rom = Rom("Secret of Evermore (Europe).sfc")
    _selftest(rom)
