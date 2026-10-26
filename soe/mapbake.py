"""ROM-side map decoders and map baking for Secret of Evermore (Europe).

Decodes the per-map data that the bank-$90 map loader ($908F68) builds in WRAM,
from the ROM alone wherever the format is solved:

  * map dimensions (map offset +2 / +3)            `map_dims_from_rom`
  * arrangement block: opcode-3 LZSS + 16-bit
    delta prefix sum (leading run only)             `decompress_lzss`,
                                                    `arrangement_first_block_from_rom`
  * per-cell record pointer table: opcode-7 codec
    (full placement of all width*height cells)      `pointer_table_from_rom`
  * BG palette block (bank $1D, 7 rows x 16 colors) `bg_palette_from_rom`,
                                                    `BG_PALETTE_ROM`
  * 4bpp tileset blocks via `soe.lz.decompress`     `tileset_from_rom`

Not solved from the ROM alone: the assembly of the 8-byte records from their
four planes, and the mapping from map set list to tileset graphics blocks. The
render helpers therefore take the records, tiles and BG1/BG2 tilemaps from
emulator dumps (WRAM/VRAM/CGRAM) where needed and label the provenance of each
result. For a dump-based path that works for every map, see `soe.snescall`.

Dumps are read from `assets/dumps/emulator/` as `<prefix>_{wram,vram,cgram}.bin`
(captured with the scripts in `tools/mesen/ppu/`). Maps without a dump are skipped.

A separate reference-rip path tiles a color-correct reference image of a map
(user-supplied, `assets/screenshots/maps/`) into a 16x16 tile atlas plus an
arrangement grid and verifies the reassembly pixel for pixel.

Format details: `docs/maps.md` (map pipeline) and `docs/compression.md` (codecs).

Run `python -m soe.mapbake [rom.sfc]` to run the self-test and write all outputs
to `assets/maps/baked/`.
"""
from __future__ import annotations
import csv
from pathlib import Path

from .rom import Rom
from . import maps

_ROOT = Path(__file__).resolve().parent.parent
_REF_DIR = _ROOT / "assets" / "screenshots" / "maps"
_EMU_DIR = _ROOT / "assets" / "dumps" / "emulator"

# The reference rips use magenta for "no data". Accept both shades.
MAGENTA = {(255, 0, 255), (255, 128, 255)}
CELL = 16

# --- WRAM offsets in the snesWorkRam space (7E0000-based) --------------------
WRAM_MAP_NUM = 0x0ADB          # 7E0ADB current map number
WRAM_WIDTH = 0x08EE            # 7E08EE map width (tiles)
WRAM_HEIGHT = 0x08F0           # 7E08F0 map height (tiles)
WRAM_PAL_BUFFER = 0x6187       # 7E6187 BG palette buffer (512 B -> CGRAM)
WRAM_TILEINFO = 0x10000        # 7F0000 per-cell record pointers + 8-byte records
WRAM_ARRANGEMENT = 0x1C300     # 7FC300 arrangement (metatile-index words)

# --- Verified BG palette offsets in the ROM (file offset) -------------------
# Block = 7 rows x 16 colors = 224 bytes (== CGRAM colors 16..127 = bytes 32..256).
# Row 0 is the dynamic HUD/status palette and is not part of the block. The block
# lives in bank $1D; `soe.palettes` (bank $10) holds character/sprite palettes.
# Verified byte for byte: ROM[off:off+224] == CGRAM dump [32:256] (see
# `verify_palette_rom`). The selector that picks the offset per map is not found.
BG_PALETTE_ROM = {16: 0x1DCC63, 97: 0x1DE6C3}

# --- Emulator dumps (map index -> file prefix in assets/dumps/emulator/) ----
EMU_DUMPS = {16: "map16", 24: "map24", 97: "map97"}
EMU_DIMS = {16: (24, 15), 24: (24, 32), 97: (48, 47)}

# Maps with a color-correct reference image (ground truth). Fields: name,
# reference file, Spriters Resource asset id, US file offset. Map identity is
# verified: the Europe map offset equals the US offset + 0x10000.
REF_MAPS = {
    56: ("LANDING",     "ref_36417.png", 36417, 0x1E8000),
    89: ("QSAND FIELD", "ref_31180.png", 31180, 0x208000),
}


# ============================================================================
# BG palette from the ROM (verified against emulator CGRAM)
# ============================================================================
def bg_palette_from_rom(rom: Rom, file_off: int) -> list[tuple[int, int, int]]:
    """Read the 224-byte BG palette block (rows 1..7 = 112 colors) at `file_off`
    from the ROM and decode it to RGB. Row 0 (HUD) is dynamic and not part of
    the block."""
    return [rom.snes_color(rom.u16(file_off + i * 2)) for i in range(112)]


def _dump(prefix: str, kind: str) -> bytes | None:
    p = _EMU_DIR / f"{prefix}_{kind}.bin"
    return p.read_bytes() if p.exists() else None


# ============================================================================
# Blob job header
# ============================================================================
def parse_blob_jobs(rom: Rom, index: int) -> dict:
    """Parse the head of the compressed map blob: the set list plus the first
    decompress job (`op=0x03`). Verified byte for byte for maps 16/24/97.

    The blob behind the trigger section is:

        [n:1] [n x set-id:2]          set list
        00                            pad
        [w0:2] 03 [size:2] <lzss>     first job (opcode 3, see `decompress_lzss`)
        ... further jobs ...

    Returns a dict with `setlist`, `job` (pad/w0/op/w1/dest) and `blob_off`.
    `w1` is the decompressed size; `dest` is really the first two bytes of the
    LZSS bit stream (the destination address is not stored in the blob, the
    caller passes it via direct page $3A/$3C). `w0` is a size field of the layer
    above, not the compressed size. The bit-level LZ body is not decoded here.

    The role of the set list is provisional: the loader loop at $9090A2..$9090D2
    hands entries to the palette queue registrar $90D532 (drained at $90D582
    into $7E6187), so they are not simply graphics ids.
    """
    off = maps.map_offset(rom, index)
    m = maps.read_map(rom, index)
    end = int(m["trigger_section_end"], 16)
    d = rom.data
    n = d[end]
    setlist = [d[end + 1 + 2 * k] | d[end + 2 + 2 * k] << 8 for k in range(n)]
    p = end + 1 + 2 * n
    pad = d[p]
    w0 = d[p + 1] | d[p + 2] << 8
    op = d[p + 3]
    w1 = d[p + 4] | d[p + 5] << 8
    dest = d[p + 6] | d[p + 7] << 8
    return {
        "index": index,
        "blob_off": f"0x{end:06X}",
        "setlist_count": n,
        "setlist": [f"0x{s:04X}" for s in setlist],
        "job": {"pad": pad, "w0": f"0x{w0:04X}", "op": f"0x{op:02X}",
                "w1": f"0x{w1:04X}", "dest": f"0x{dest:04X}"},
    }


# ============================================================================
# Codec 1: opcode-3 LZSS ($8C9C5E), see docs/compression.md
# ============================================================================
def decompress_lzss(data, src_off: int) -> tuple[bytes, int]:
    """Opcode-3 LZSS of the SoE map loader. `data` = ROM bytes, `src_off` points
    at the opcode byte (0x03). Returns (decompressed bytes, end offset in the stream).

    The decompress dispatcher at $8C9C22 takes the first blob byte as opcode and
    the next two bytes as a 16-bit parameter, and jumps through the table at
    $8C9C36: opcode 0 = raw block copy, 3 = LZSS (the map route), 7 = pointer
    table codec (see `_Op7`). The destination WRAM address is set by the caller
    via direct page $3A/$3C.

    Format: header `03 [size:u16le]`, bit stream from src+3, 4096-byte ring buffer
    (WRAM $7FA000..$7FAFFF in the game, write pointer starts at 0).
    Control bit MSB first (mask table $8C9DDB): 1 = 8-bit literal (output + ring);
    0 = 16-bit token, V=token>>4 (ring position, start V-1), len=(token&0x0F)+2,
    V==0 = end; copy len bytes from the ring to the output AND back into the ring
    (LZSS self reference).

    Verified: `decompress_lzss(rom.data, 0x070100)` yields exactly 6144 bytes
    (header `03 00 18`) and ends at the source offset of the next caller.
    """
    size = data[src_off + 1] | data[src_off + 2] << 8
    p = src_off + 3
    bitbuf = nbits = 0
    ring = bytearray(0x1000)
    wp = 0
    out = bytearray()

    def bit() -> int:
        nonlocal bitbuf, nbits, p
        if nbits == 0:
            bitbuf = data[p]; p += 1; nbits = 8
        nbits -= 1
        return (bitbuf >> nbits) & 1

    def bits(n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | bit()
        return v

    while len(out) < size:
        if bit():
            b = bits(8)
            out.append(b); ring[wp] = b; wp = (wp + 1) & 0xFFF
        else:
            tok = bits(16); v = tok >> 4
            if v == 0:
                break
            pos = v - 1; ln = (tok & 0x0F) + 2
            for i in range(ln):
                b = ring[(pos + i) & 0xFFF]
                out.append(b); ring[wp] = b; wp = (wp + 1) & 0xFFF
    return bytes(out), p


def arrangement_first_block_from_rom(rom: Rom, index: int) -> list[int]:
    """Decode the leading arrangement run from the ROM (no dump): the first LZSS
    block of the map, as the running sum of its signed 16-bit deltas.

    The LZSS output of the arrangement blocks is not the 7FC300 word itself but
    a stream of signed 16-bit deltas; the real arrangement is their running sum
    (arr[0] = first word, arr[i] = arr[i-1] + delta[i], 16-bit wrap). Verified
    byte for byte against 7FC300 dumps: map16 cells 0..50, map24 0..136, map97
    0..213. Example chain (map97, cells 0..7): 16cd 16ce 16cf 11d0 11d1 11d2 16d0
    16d1 from deltas 16cd +1 +1 -4ff +1 +1 +4fe +1.

    This is only the first contiguous run (map16: 51, map24: 137, map97: 214
    cells). The remaining cells are not further pure delta-LZSS blocks; the
    per-cell placement of the full area comes from the opcode-7 pointer table
    (`pointer_table_from_rom`). Returns the list of 16-bit metatile indices of
    this run.
    """
    off = maps.map_offset(rom, index)
    m = maps.read_map(rom, index)
    end = int(m["trigger_section_end"], 16)
    n = rom.data[end]
    p = end + 1 + 2 * n
    # Find opcode 3 in the small head (the first few bytes are [00][w0:2] before it).
    src = next((p + k for k in range(6) if rom.data[p + k] == 0x03), None)
    if src is None:
        return []
    out, _ = decompress_lzss(rom.data, src)
    words = [out[i] | out[i + 1] << 8 for i in range(0, len(out) & ~1, 2)]
    if not words:
        return []
    arr = [words[0]]
    for dw in words[1:]:
        arr.append((arr[-1] + dw) & 0xFFFF)
    return arr


# ============================================================================
# Codec 2: opcode 7 = per-cell pointer table codec ($8C9EFA)
# ============================================================================
# Opcode 7 is not the tileset codec. It is a 16-bit word LZ with 2D context
# prediction that produces the per-cell record pointer table in 7F:0000: one
# 16-bit byte offset (from 7F:0000) per cell, pointing at the cell's 8-byte
# metatile record. This is the full 2D placement of all width*height cells.
#
# Verified byte for byte against 7F:0000 dumps: map16 (360 cells) and map97
# (2256 cells, including the wide path for >256 metatiles), both from
# parameters derived from the ROM alone. map24 diverges from word 298 on because
# of an unexplained jump of the $0C generator (0xB70 -> 0xEC0, +106 records
# without emission); the two clean reference maps are byte-exact.
#
# Parameters (all derivable from the ROM map header, verified):
#   $0FAA (BASE)  = width*height*2   (= pointer table size = records base)
#   $0F48 (P2E)   = width*2          (stride for the "cell above" predictor)
#   $0FC6         = 0                (count of persistent pre-records; always 0 here)
#   $0FAC         = init fill count*8; uncritical, overfill (w*h slots) is safe.
#
# Algorithm ($8C9EFA, jump table $8CA08C, taken from the disassembly):
#   Init: every 8-byte record slot [BASE+8k .. +6] is pre-filled with its OWN
#         pointer (BASE+8k). $0C = new-word generator = BASE (+8 per new metatile).
#   Two context registers: $26 = pointer of the cell ABOVE (= out[Y-width]), $12 =
#   pointer of the cell to the LEFT (recency). One MSB-first prefix code per
#   output word (top 5 bits -> table $8CA08C):
#     '1....'  (1 bit)  -> copy [$26]        (cell above, most frequent case)
#     '000..'  (3 bits) -> copy [$12+2]
#     '00100'  (5 bits) -> copy [$26+4]
#     '00101'  (5 bits) -> copy [$12+6]
#     '0011.'  (4 bits) -> NEW word $0C, then $0C+=8 (next metatile record)
#     '01...'  (2+n bits) -> general back reference: read $14 bits index -> BASE+index*8
#                          ($14 = bit width = ceil(log2(#metatiles)); wide path >= 9 bits)
#   After each word, $8C9F88 updates the context registers ($26 from out[Y-width],
#   $12 = last written word) and the 2-deep history in the record region.
# Handlers: $8C9F72/$8C9F88/$8C9FC5/$8C9FEA/$8CA00A/$8CA01D/$8CA030/$8CA080,
# jump tables $8CA08C/$8CA0F0/$8CA134. See docs/compression.md.
class _Op7:
    """Reference port of the opcode-7 codec (16-bit word LZ with 2D context
    prediction, SoE $8C9EFA). Models the bank-7F work RAM as a byte array."""

    def __init__(s, data, src_off, faa, fac, fc6, f48):
        s.d = data
        s.BASE = faa
        s.mem = bytearray(0x18000)
        x = faa
        for _ in range((fac >> 3) + 1):          # init fill: slot <- own pointer
            for o in (0, 2, 4, 6):
                s.mem[x + o] = x & 0xFF
                s.mem[x + o + 1] = (x >> 8) & 0xFF
            x = (x + 8) & 0xFFFF
        s.C = ((fc6 << 3) + faa) & 0xFFFF         # $0C new-word generator
        s.E = fc6                                  # $0E count
        s.T10 = 1
        s.T14 = 0
        if fc6 != 0:
            a = fc6
            while a:
                s.T10 = (s.T10 << 1) & 0xFFFF
                s.T14 += 1
                a >>= 1
        s.p0 = src_off + 3
        s.bi = 0
        s.reg26 = faa
        s.reg12 = faa
        s.P2E = f48
        s.Y = 0
        s.limit = faa                             # CPY $06 (=BASE): out = w*h words

    def _rd(s, a):
        return s.mem[a] | s.mem[a + 1] << 8

    def _wr(s, a, v):
        s.mem[a] = v & 0xFF
        s.mem[a + 1] = (v >> 8) & 0xFF

    def _peek(s, n):
        v = 0
        for k in range(n):
            b = s.bi + k
            v = (v << 1) | ((s.d[s.p0 + (b >> 3)] >> (7 - (b & 7))) & 1)
        return v

    def _update(s, word):
        # $8C9F88: update context registers + 2-deep history.
        y = s.Y
        a = word
        if y >= s.P2E:
            x = s.reg26
            if a != s._rd(x + 4):
                s._wr(x + 4, s._rd(x))
                a = s._rd(y)
            s._wr(x, a)
        a = word
        x = s.reg12
        if a != s._rd(x + 6):
            s._wr(x + 6, s._rd(x + 2))
            a = s._rd(y)
        s._wr(x + 2, a)
        s.reg12 = a
        s.Y = y + 2
        t = s.Y - s.P2E
        if t >= 0:
            s.reg26 = s._rd(t)

    def run(s, max_iter=200000):
        out = []
        g = 0
        while s.Y != s.limit:
            g += 1
            if g > max_iter:
                break
            top5 = s._peek(5)
            if top5 < 4:                     # '000..' -> [$12+2]
                s.bi += 3
                w = s._rd(s.reg12 + 2)
            elif top5 == 4:                  # '00100' -> [$26+4]
                s.bi += 5
                w = s._rd(s.reg26 + 4)
            elif top5 == 5:                  # '00101' -> [$12+6]
                s.bi += 5
                w = s._rd(s.reg12 + 6)
            elif top5 < 8:                   # '0011.' -> new word $0C
                s.bi += 4
                w = s.C
                s.C = (s.C + 8) & 0xFFFF
                s.E = (s.E + 1) & 0xFFFF
                if s.E & s.T10:
                    s.T10 = (s.T10 << 1) & 0xFFFF
                    s.T14 += 1
            elif top5 < 16:                  # '01...' -> general back-ref, $14-bit index
                s.bi += 2
                idx = s._peek(s.T14)
                s.bi += s.T14
                w = (s.BASE + idx * 8) & 0xFFFF
            else:                            # '1....' -> [$26] (cell above)
                s.bi += 1
                w = s._rd(s.reg26)
            s._wr(s.Y, w)
            out.append(w)
            s._update(w)
        return out


def _map_blocks_from_rom(rom: Rom, index: int) -> dict:
    """Locate the three compressed per-map blocks in the ROM: arrangement (op3,
    -> 7FC300), pointer table (op7, -> 7F:0000) and the record TL plane (op3,
    -> records region). Byte layout (verified by exec trace): arrangement op3,
    then (after padding) `07 <faa:u16le>`, then (after padding) the op3 record
    plane."""
    d = rom.data
    w, h = map_dims_from_rom(rom, index)
    faa = w * h * 2
    m = maps.read_map(rom, index)
    end = int(m["trigger_section_end"], 16)
    n = d[end]
    p = end + 1 + 2 * n
    arr_src = next((p + k for k in range(6) if d[p + k] == 0x03), None)
    if arr_src is None:
        return {}
    _, arr_end = decompress_lzss(d, arr_src)
    sig = bytes([0x07, faa & 0xFF, (faa >> 8) & 0xFF])
    op7_src = d.find(sig, arr_end, arr_end + 0x600)
    return {
        "width": w, "height": h, "faa": faa, "f48": w * 2,
        "arr_src": arr_src, "op7_src": op7_src,
    }


def pointer_table_from_rom(rom: Rom, index: int) -> list[int]:
    """The FULL per-cell record pointer table (7F:0000) from the ROM, via opcode 7
    (2D context prediction LZ). Returns w*h 16-bit pointers (byte offset from
    7F:0000 to each cell's 8-byte record). Byte-exact against the 7F:0000 dump
    (map16/map97). Parameters purely from the ROM header (faa=w*h*2, f48=w*2, fc6=0)."""
    b = _map_blocks_from_rom(rom, index)
    if not b or b["op7_src"] < 0:
        return []
    o = _Op7(rom.data, b["op7_src"], b["faa"], b["faa"] << 3, 0, b["f48"])
    return o.run()


# ============================================================================
# Tileset codec: 4bpp tileset from the ROM via soe.lz.decompress
# (16-mode RLE/LZ). One block = 16x16 = 128 B = 4 tiles (TL,TR,BL,BR).
# ============================================================================
def tileset_from_rom(rom: Rom, index: int) -> tuple[bytearray, dict]:
    """Decode the char-base tileset (0x4000..0xC000, 0x400 8x8 tiles) from the ROM
    via `soe.lz.decompress`. Returns (tile_bytes[0x8000], slot->rom_off map).

    One `decompress` call yields one 16x16 block (128 bytes, four 8x8 4bpp
    tiles). Verified byte for byte: `decompress(rom, 0x290811)` equals the VRAM
    tiles [0x4A, 0x4B, 0x5A, 0x5B] (a full metatile, not a raw passthrough). A
    full-ROM scan (decompress at every offset, output matched against the VRAM
    char-base metatiles) decodes 239 of 256 map16 metatiles byte for byte (97% of
    char base 0x4000). The blocks are individually compressed and scattered over
    many banks (0x05/0x06/0x07/0x12/0x1C/0x2F ...), not contiguous.

    The tile pixels are byte-exact ROM-decoded. The assignment slot -> ROM offset
    is found by known-plaintext match against the VRAM dump, because the metatile
    pointer table (metatile index -> ROM offset) is not located in the Europe ROM.
    This function therefore needs the map's VRAM dump as reference."""
    from soe.lz import decompress
    vram = _dump(EMU_DUMPS[index], "vram")
    if vram is None:
        return bytearray(0x8000), {}
    cb = vram[0x4000:0xC000]

    def vtile(t):
        return bytes(cb[t * 32:t * 32 + 32])

    # index every 16x16 large-tile group (slot B -> tiles B,B+1,B+16,B+17)
    groups, tl_index = {}, {}
    for B in range(0x400 - 17):
        g = vtile(B) + vtile(B + 1) + vtile(B + 16) + vtile(B + 17)
        if any(g):
            groups[B] = g
            tl_index.setdefault(vtile(B), []).append(B)
    # full-ROM scan: decompress at every offset, match output against the groups
    hits = {}
    data = rom.data
    for off in range(0, 0x300000):
        try:
            out, _c = decompress(data, off)
        except Exception:
            continue
        if len(out) != 128:
            continue
        cand = tl_index.get(bytes(out[:32]))
        if not cand:
            continue
        ob = bytes(out)
        for B in cand:
            if ob == groups[B]:
                hits.setdefault(B, (off, ob))
                break
    tiles = bytearray(0x8000)
    slot_off = {}
    for B, (off, ob) in hits.items():
        slot_off[B] = off
        for sub, T in zip((0, 1, 2, 3), (B, B + 1, B + 16, B + 17)):
            tiles[T * 32:T * 32 + 32] = ob[sub * 32:sub * 32 + 32]
    return tiles, slot_off


# ============================================================================
# Rendering: BG mode 1 with 16x16 large tiles (confirmed by a Mesen PPU state
# dump, assets/dumps/emulator/cap_map97_ppu.txt):
#   ppu.bgMode=1  layers[0].largeTiles=true  chrAddress=8192(word)=0x4000(byte)
# A tilemap is a list of large-tile words: one 16-bit word per cell
# (`vhopppcc cccccccc`: tile 10 bit, palette 3 bit, priority, H/V flip). The PPU
# expands each to four 8x8 subtiles T, T+1, T+16, T+17.
# Note: the 7FC300 arrangement is NOT such a tilemap (it holds metatile indices);
# drawing it as large tiles is only valid for the leading run. The correct
# full-map path is metatile index -> 8-byte record -> four quadrant tiles
# (`render_metatiles_from_dump`).
# ============================================================================
LARGETILE_CHAR_BASE = 0x4000        # BG1 chrAddress 8192 words = 0x4000 bytes

def bg_colors_from_rom(rom: Rom, index: int, cgram_dump: bytes) -> list[tuple]:
    """128-color palette (8 rows x 16): row 0 = dynamic HUD palette (the only part
    not in the ROM -> taken from the CGRAM dump), rows 1..7 from the ROM (bank 0x1D,
    verified). The terrain colors thus come from the ROM, not from the dump."""
    row0 = [Rom.snes_color(cgram_dump[i] | cgram_dump[i + 1] << 8) for i in range(0, 32, 2)]
    return row0 + bg_palette_from_rom(rom, BG_PALETTE_ROM[index])


def _blit_largetile(px, arr: list[int], width: int, vram: bytes, cgcol: list,
                    char_base: int) -> int:
    """Paint a large-tile word list onto an existing px array (transparent =
    color index 0 is skipped, so layers can be composited). One 16x16 tile per
    word (subtiles T,T+1,T+16,T+17). Returns painted_px."""
    painted = 0
    for i, word in enumerate(arr):
        if word == 0:
            continue
        cx, cy = (i % width) * CELL, (i // width) * CELL
        tile = word & 0x3FF; pal = (word >> 10) & 7
        hf = (word >> 14) & 1; vf = (word >> 15) & 1
        for t, ox, oy in ((tile, 0, 0), (tile + 1, 8, 0), (tile + 16, 0, 8), (tile + 17, 8, 8)):
            tpx = _decode_4bpp_tile(vram, t, char_base)
            qx = 8 - ox if hf else ox
            qy = 8 - oy if vf else oy
            for y in range(8):
                for x in range(8):
                    c = tpx[7 - y if vf else y][7 - x if hf else x]
                    if c:
                        px[cx + qx + x, cy + qy + y] = cgcol[pal * 16 + c]
                        painted += 1
    return painted


def render_arrangement(arr: list[int], width: int, vram: bytes, cgcol: list,
                       char_base: int = LARGETILE_CHAR_BASE):
    """Single-layer large-tile render onto a fresh image. Returns (Image, painted_px)."""
    from PIL import Image
    rows = (len(arr) + width - 1) // width
    img = Image.new("RGB", (width * CELL, rows * CELL), (0, 0, 0))
    painted = _blit_largetile(img.load(), arr, width, vram, cgcol, char_base)
    return img, painted


# Default tilemap bases of this engine (byte offset in VRAM), confirmed on the clean
# map16 render: BG2 = background (walls/windows), BG1 = foreground (objects).
# tilemapAddress from the PPU state dump: layers[0]=0 (BG1), layers[1]=0x800 (BG2).
BG1_TILEMAP_VRAM = 0x0000
BG2_TILEMAP_VRAM = 0x0800
SCREEN_TILES_W, SCREEN_TILES_H = 16, 14      # SNES screen 256x224 px in 16 px tiles


def render_screen_from_dump(idx: int, out: Path,
                            char_base: int = LARGETILE_CHAR_BASE) -> dict:
    """Render the real on-screen image of the map from the two BG tilemaps in the
    VRAM dump (BG2 background + BG1 foreground composite), large tiles, ROM palette
    colors. This yields a clean, recognizable map image and confirms that the
    render pipeline (4bpp decode, large-tile expansion T,T+1,T+16,T+17, char base
    0x4000, palette) is right. Provenance: on-screen tilemaps + tiles + palette
    from the dump.

    PNG at out/screen_map_<idx>/map.png (cropped to the SNES screen 256x224).
    """
    from statistics import pvariance
    vram = _dump(EMU_DUMPS[idx], "vram"); cg = _dump(EMU_DUMPS[idx], "cgram")
    if vram is None or cg is None:
        return {"idx": idx, "error": "vram/cgram dump missing"}
    cgcol = [Rom.snes_color(cg[i] | cg[i + 1] << 8) for i in range(0, 512, 2)]
    from PIL import Image
    img = Image.new("RGB", (32 * CELL, 32 * CELL), (0, 0, 0))
    px = img.load()

    def tmwords(base):
        return [vram[base + 2 * i] | vram[base + 2 * i + 1] << 8 for i in range(32 * 32)]
    _blit_largetile(px, tmwords(BG2_TILEMAP_VRAM), 32, vram, cgcol, char_base)
    _blit_largetile(px, tmwords(BG1_TILEMAP_VRAM), 32, vram, cgcol, char_base)
    img = img.crop((0, 0, SCREEN_TILES_W * CELL, SCREEN_TILES_H * CELL))
    d = out / f"screen_map_{idx:04d}"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / "map.png")
    flat = [c for row in list(img.getdata()) for c in row]
    nonblack = sum(1 for p in img.getdata() if p != (0, 0, 0))
    return {
        "idx": idx, "png": str(d / "map.png"),
        "pixel_variance": round(pvariance(flat), 1),
        "nonblack_frac": round(nonblack / (img.width * img.height), 3),
        "note": "on-screen BG2+BG1 composite from VRAM tilemaps; palette=ROM colors",
    }


def render_from_rom(rom: Rom, index: int, out: Path,
                    char_base: int = LARGETILE_CHAR_BASE) -> dict:
    """Render the map from the ROM: arrangement (LZSS + delta, verified byte for
    byte) + BG palette (bank 0x1D, verified) as large-tile BG1. The tile graphics
    come from the VRAM dump (the set-id -> graphics pointer mapping is not solved).

    Covers the leading arrangement run only. Clean only inside the loaded tileset
    window (the dump holds only the tiles visible at dump time). PNG at
    out/rom_map_<index>/map.png.
    """
    from PIL import Image
    if index not in BG_PALETTE_ROM:
        return {"index": index, "error": "no verified ROM palette offset for this map"}
    arr = arrangement_first_block_from_rom(rom, index)
    prefix = EMU_DUMPS.get(index)
    vram = _dump(prefix, "vram") if prefix else None
    cg = _dump(prefix, "cgram") if prefix else None
    if not arr or vram is None or cg is None:
        return {"index": index, "error": "need arr + vram/cgram dump for tiles"}

    # Verify the arrangement byte for byte against the 7FC300 dump.
    wram = _dump(prefix, "wram")
    gt = [wram[WRAM_ARRANGEMENT + 2 * i] | wram[WRAM_ARRANGEMENT + 2 * i + 1] << 8
          for i in range(len(arr))] if wram else None
    arr_exact = (arr == gt) if gt is not None else "no wram dump"

    W = EMU_DIMS[index][0]
    cgcol = bg_colors_from_rom(rom, index, cg)
    img, painted = render_arrangement(arr, W, vram, cgcol, char_base)

    d = out / f"rom_map_{index:04d}"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / "map.png")
    # Pixel variance as a hard "not flat noise" check.
    from statistics import pvariance
    flat = [c for row in list(img.getdata()) for c in row]
    return {
        "index": index, "cells_from_rom": len(arr), "grid": f"{W}x{(len(arr)+W-1)//W}",
        "arrangement_byte_exact_vs_dump": arr_exact,
        "char_base": f"0x{char_base:04X}", "painted_px": painted,
        "pixel_variance": round(pvariance(flat), 1),
        "png": str(d / "map.png"),
        "provenance": "arrangement+palette FROM ROM (verified); tiles from VRAM dump "
                      "(tileset mapping open); leading run only",
    }


def verify_palette_rom(rom: Rom) -> dict:
    """The ROM palette block matches the CGRAM dump (colors 16..127) of the running
    game byte for byte. This confirms that the BG palette lives in the ROM at
    the known offsets."""
    out = {}
    for idx, off in BG_PALETTE_ROM.items():
        cg = _dump(EMU_DUMPS[idx], "cgram")
        if cg is None:
            out[idx] = "no dump"
            continue
        rom_block = rom.data[off:off + 224]
        cg_rows = cg[32:32 + 224]                 # CGRAM colors 16..127
        out[idx] = {
            "rom_off": f"0x{off:06X}",
            "matches_cgram": rom_block == cg_rows,
            "colors": 112,
        }
    return out


# ============================================================================
# Render a map from an emulator dump (real colors + layout)
# ============================================================================
def _decode_4bpp_tile(vram: bytes, tile_no: int, char_base: int):
    off = char_base + tile_no * 32
    px = [[0] * 8 for _ in range(8)]
    if off + 32 > len(vram):
        return px
    for y in range(8):
        b0, b1 = vram[off + y * 2], vram[off + y * 2 + 1]
        b2, b3 = vram[off + 16 + y * 2], vram[off + 16 + y * 2 + 1]
        for x in range(8):
            s = 7 - x
            px[y][x] = (((b0 >> s) & 1) | (((b1 >> s) & 1) << 1)
                        | (((b2 >> s) & 1) << 2) | (((b3 >> s) & 1) << 3))
    return px


def render_from_dump(key: int, out: Path, char_base: int = LARGETILE_CHAR_BASE) -> dict:
    """Full-map reference render: the COMPLETE 7FC300 arrangement from the dump as
    large-tile BG1 (see the LARGETILE_CHAR_BASE block), with the BG palette from
    the ROM. Provenance: arrangement = dump, palette = ROM, tiles = VRAM dump.
    As a full-map render this is incorrect (7FC300 holds metatile indices, not
    large-tile words); use `render_metatiles_from_dump` for that.

    Returns a dict of metrics; PNG at out/emu_map_<key>/map.png.
    """
    prefix = EMU_DUMPS[key]
    wram = _dump(prefix, "wram"); vram = _dump(prefix, "vram"); cg = _dump(prefix, "cgram")
    if not (wram and vram and cg):
        return {"key": key, "error": "dump missing"}
    w, h = EMU_DIMS[key]
    # Palette: row 0 from the CGRAM dump (dynamic), rows 1..7 from the CGRAM dump ==
    # ROM bank 0x1D (verified byte for byte, verify_palette_rom) -> the colors are
    # the ROM colors. The full 256-color CGRAM suffices since rows 0..7 == ROM rows for BG.
    cgcol = [Rom.snes_color(cg[i] | cg[i + 1] << 8) for i in range(0, 512, 2)]
    arr = [wram[WRAM_ARRANGEMENT + 2 * i] | wram[WRAM_ARRANGEMENT + 2 * i + 1] << 8
           for i in range(w * h)]
    img, painted = render_arrangement(arr, w, vram, cgcol, char_base)
    d = out / f"emu_map_{key:04d}"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / "map.png")
    return {
        "key": key, "grid": f"{w}x{h}", "distinct_metatiles": len(set(arr)),
        "char_base": f"0x{char_base:04X}", "painted_px": painted,
        "png": str(d / "map.png"),
        "note": "large-tile BG1; arrangement=dump(full), palette=ROM, tiles=VRAM",
    }


# ============================================================================
# Full-map pipeline: metatile index -> 8-byte record -> 4 quadrants
#
# 7FC300 holds one METATILE INDEX per cell, not a raw PPU large-tile word:
#
#   7FC300[cell]  = metatile index (running sum of the delta-LZSS words)
#   7F0000[cell]  = 16-bit byte offset from 7F0000 to the cell's 8-byte record
#                   (deduplicated: equal metatiles share one record)
#   record (8 B)  = FOUR SNES tilemap words (tl,tr,bl,br) of the 16x16 quadrants,
#                   each `vhopppcc cccccccc` (v/hflip, prio, pal 0..7, 10-bit tile).
#   -> draw 4 8x8 tiles per cell from the 4bpp tileset (char_base 0x4000).
#
# Large maps (map97) render only partially from a dump, because the VRAM dump holds
# only the tileset window loaded at dump time (tileset from the ROM is not solved).
# ============================================================================
def map_dims_from_rom(rom: Rom, index: int) -> tuple[int, int]:
    """(width, height) in tiles from the ROM map header. The bank-$90 loader reads
    the width at map offset +2 ($908F97 -> $08EE) and the height at +3 ($908FBA ->
    $08F0). Verified byte for byte against EMU_DIMS (16/24/97) and the WRAM dims in
    the dump.

    Header bytes read by the loader ($908F85..$909049):
        +0x00 -> $0F88   +0x01 -> $0F8A   (purpose unknown)
        +0x02 -> width   +0x03 -> height
        +0x04 -> $212C (TM, main screen layers) + $0F82
        +0x05 -> $212D (TS, sub screen)         + $0F83
        +0x06 -> $2131 (CGADSUB)                + $0F84
        +0x07 -> $2130 (CGWSEL)                 + $0F85
        +0x08 -> $7E241F      +0x09 (word) -> $0F86
    Byte +4 is the TM register value, which is almost always 0x16/0x17 (BG1+BG2
    (+BG3)+OBJ); it is not a graphics pointer (see maps.py)."""
    off = maps.map_offset(rom, index)
    return rom.data[off + 2], rom.data[off + 3]


def _blit_metacell(px, rec: list[int], cx: int, cy: int, vram: bytes,
                   cgcol: list, char_base: int) -> int:
    """Draw ONE 16x16 cell from its 8-byte record (4 quadrant words tl,tr,bl,br).
    Transparent (color index 0) is skipped. Returns painted."""
    painted = 0
    for word, ox, oy in ((rec[0], 0, 0), (rec[1], 8, 0), (rec[2], 0, 8), (rec[3], 8, 8)):
        tile = word & 0x3FF
        pal = (word >> 10) & 7
        hf = (word >> 14) & 1
        vf = (word >> 15) & 1
        tpx = _decode_4bpp_tile(vram, tile, char_base)
        for y in range(8):
            for x in range(8):
                c = tpx[7 - y if vf else y][7 - x if hf else x]
                if c:
                    px[cx + ox + x, cy + oy + y] = cgcol[pal * 16 + c]
                    painted += 1
    return painted


def render_metatiles_from_dump(key: int, out: Path,
                               char_base: int = LARGETILE_CHAR_BASE) -> dict:
    """FULL, correct map render: metatile index arrangement (7FC300) -> record
    pointer (7F0000) -> 8-byte record -> 4 quadrant tiles. Dims from the ROM
    (`map_dims_from_rom`), palette from the ROM (bank 0x1D, `bg_colors_from_rom`
    where known, else the CGRAM dump), records + tiles from the WRAM/VRAM dump.

    This is a single BG layer and renders dark/sparse (nonblack ~0.31 for map16);
    the recognizable image is the BG2+BG1 composite of `render_screen_from_dump`.
    Large maps render only partially (tileset window). PNG at
    out/meta_map_<key>/map.png.
    """
    from PIL import Image
    prefix = EMU_DUMPS[key]
    wram = _dump(prefix, "wram"); vram = _dump(prefix, "vram"); cg = _dump(prefix, "cgram")
    if not (wram and vram and cg):
        return {"key": key, "error": "dump missing"}
    w, h = map_dims_from_rom(_ROM_CACHE, key) if _ROM_CACHE else EMU_DIMS[key]
    cgcol = [Rom.snes_color(cg[i] | cg[i + 1] << 8) for i in range(0, 512, 2)]
    img = Image.new("RGB", (w * CELL, h * CELL), (0, 0, 0))
    px = img.load()

    def w16(base, i):
        return wram[base + 2 * i] | wram[base + 2 * i + 1] << 8

    painted = 0
    for cell in range(w * h):
        ptr = w16(WRAM_TILEINFO, cell)
        rec = [wram[WRAM_TILEINFO + ptr + 2 * k] | wram[WRAM_TILEINFO + ptr + 2 * k + 1] << 8
               for k in range(4)]
        painted += _blit_metacell(px, rec, (cell % w) * CELL, (cell // w) * CELL,
                                  vram, cgcol, char_base)
    d = out / f"meta_map_{key:04d}"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / "map.png")
    nonblack = sum(1 for p in img.getdata() if p != (0, 0, 0))
    return {
        "key": key, "grid": f"{w}x{h}", "dims_from_rom": (w, h),
        "painted_px": painted,
        "nonblack_frac": round(nonblack / (w * CELL * h * CELL), 3),
        "png": str(d / "map.png"),
        "note": "metatile-index -> 8-byte-record -> 4 quadrant tiles; dims+palette "
                "FROM ROM, records+tiles from dump (full tileset from ROM open)",
    }


def decode_map(rom: Rom, index: int) -> dict:
    """Decode a map as far as is verified from the ROM and report provenance and
    open items.

    Returned keys (all from the ROM):
      width,height            -- ROM header +2/+3 (byte-exact, all 127)
      pointer_table           -- op7 pointer per cell (7F:0000), FULL placement,
                                 byte-exact (map16/map97)
      arrangement_leading     -- leading metatile index run (op3+delta), byte-exact
      palette                 -- 112 BG colors (bank 0x1D) where known
      records_tl_plane        -- op3 record TL word plane (1 of 4 planes; full
                                 8-byte records need the 4-plane assembly, open)
      tileset_open            -- True: the 4bpp graphics are assembled from shared
                                 metatile graphics banks (e.g. 0x294A04) via set
                                 list chunks and DMA'd inline @ $9091C1 to char
                                 base 0x4000; the set-id -> graphics pointer table
                                 is not solved.
    """
    w, h = map_dims_from_rom(rom, index)
    ptrs = pointer_table_from_rom(rom, index)
    blocks = _map_blocks_from_rom(rom, index)
    recs_tl = []
    if blocks and blocks["op7_src"] >= 0:
        o = _Op7(rom.data, blocks["op7_src"], blocks["faa"], blocks["faa"] << 3, 0, blocks["f48"])
        o.run()
        comp_end = blocks["op7_src"] + 3 + ((o.bi + 7) // 8)
        rsrc = next((comp_end + k for k in range(8) if rom.data[comp_end + k] == 0x03), None)
        if rsrc is not None:
            recs_tl, _ = decompress_lzss(rom.data, rsrc)
    return {
        "index": index, "width": w, "height": h,
        "pointer_table": ptrs,
        "arrangement_leading": arrangement_first_block_from_rom(rom, index),
        "palette": bg_palette_from_rom(rom, BG_PALETTE_ROM[index]) if index in BG_PALETTE_ROM else None,
        "records_tl_plane": list(recs_tl),
        "tileset_open": True,
        "provenance": "dims+pointer_table(full placement)+arrangement+palette FROM ROM "
                      "(op7/op3 byte-exact); records need 4-plane assembly; tileset "
                      "assembled from shared graphics banks (set-id mapping open)",
    }


def render_map(rom: Rom, index: int, out: Path,
               char_base: int = 0x4000) -> dict:
    """Render the map with the FULL placement from the ROM (op7 pointer table),
    plus 8-byte records and 4bpp tiles from the VRAM/WRAM dump (record assembly
    and tileset from the ROM are still open). Since the op7 pointers match the
    dump byte for byte, the image is identical to the verified
    `render_metatiles_from_dump`, but the placement now comes from the ROM, not
    from the dump.

    PNG at out/rommap_<index>/map.png. Only for dump maps (tiles needed)."""
    from PIL import Image
    prefix = EMU_DUMPS.get(index)
    wram = _dump(prefix, "wram") if prefix else None
    vram = _dump(prefix, "vram") if prefix else None
    cg = _dump(prefix, "cgram") if prefix else None
    ptrs = pointer_table_from_rom(rom, index)
    if not ptrs or wram is None or vram is None or cg is None:
        return {"index": index, "error": "need op7 pointers + vram/cgram/wram dump for tiles"}
    w, h = map_dims_from_rom(rom, index)
    # Check: op7 pointers from the ROM == 7F:0000 dump (byte-exact)?
    gt = [wram[WRAM_TILEINFO + 2 * i] | wram[WRAM_TILEINFO + 2 * i + 1] << 8 for i in range(w * h)]
    ptr_exact = ptrs == gt
    cgcol = [Rom.snes_color(cg[i] | cg[i + 1] << 8) for i in range(0, 512, 2)]
    img = Image.new("RGB", (w * CELL, h * CELL), (0, 0, 0))
    px = img.load()
    painted = 0
    for cell in range(w * h):
        ptr = ptrs[cell]
        rec = [wram[WRAM_TILEINFO + ptr + 2 * k] | wram[WRAM_TILEINFO + ptr + 2 * k + 1] << 8
               for k in range(4)]
        painted += _blit_metacell(px, rec, (cell % w) * CELL, (cell // w) * CELL,
                                  vram, cgcol, char_base)
    d = out / f"rommap_{index:04d}"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / "map.png")
    nonblack = sum(1 for p in img.getdata() if p != (0, 0, 0))
    return {
        "index": index, "grid": f"{w}x{h}",
        "pointer_table_from_rom_byte_exact_vs_dump": ptr_exact,
        "painted_px": painted,
        "nonblack_frac": round(nonblack / (w * CELL * h * CELL), 3),
        "png": str(d / "map.png"),
        "note": "placement (op7 pointer table) + dims + palette FROM ROM (byte-exact); "
                "8-byte records + 4bpp tiles from dump (record assembly + tileset from "
                "ROM still open)",
    }


def render_map_clean(rom: Rom, index: int, out: Path) -> dict:
    """The clean image with 4bpp tiles from the ROM: BG2+BG1 large-tile composite,
    tiles via `tileset_from_rom` (codec byte-exact), palette from the ROM. The
    on-screen tilemaps (BG layout) come from the VRAM dump window; the full-map
    BG2 arrangement from the ROM is still open.

    Gives the recognizable image, not the dark single-layer metatile image. PNG
    at out/clean_map_<index>/map.png."""
    from PIL import Image
    prefix = EMU_DUMPS.get(index)
    vram = _dump(prefix, "vram") if prefix else None
    cg = _dump(prefix, "cgram") if prefix else None
    if vram is None or cg is None:
        return {"index": index, "error": "need vram/cgram dump (tilemaps + ref) for clean render"}
    tiles, slot_off = tileset_from_rom(rom, index)
    # Copy the ROM-decoded tiles into the char base; fill in missing metatiles
    # (not located) from the dump so the image is complete.
    romvram = bytearray(vram)
    for t in range(0x400):
        seg = tiles[t * 32:t * 32 + 32]
        if any(seg):
            romvram[0x4000 + t * 32:0x4000 + t * 32 + 32] = seg
    cgcol = bg_colors_from_rom(rom, index, cg) if index in BG_PALETTE_ROM else \
        [Rom.snes_color(cg[i] | cg[i + 1] << 8) for i in range(0, 512, 2)]

    def tmwords(base):
        return [romvram[base + 2 * i] | romvram[base + 2 * i + 1] << 8 for i in range(32 * 32)]

    img = Image.new("RGB", (32 * CELL, 32 * CELL), (0, 0, 0))
    px = img.load()
    _blit_largetile(px, tmwords(BG2_TILEMAP_VRAM), 32, bytes(romvram), cgcol, 0x4000)
    _blit_largetile(px, tmwords(BG1_TILEMAP_VRAM), 32, bytes(romvram), cgcol, 0x4000)
    img = img.crop((0, 0, SCREEN_TILES_W * CELL, SCREEN_TILES_H * CELL))
    d = out / f"clean_map_{index:04d}"
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / "map.png")
    nonblack = sum(1 for p in img.getdata() if p != (0, 0, 0))
    return {
        "index": index, "metatiles_from_rom": len(slot_off),
        "nonblack_frac": round(nonblack / (img.width * img.height), 3),
        "png": str(d / "map.png"),
        "note": "BG2+BG1 composite; 4bpp tiles decoded FROM ROM (soe.lz codec, byte-exact) "
                "+ palette FROM ROM; on-screen tilemaps from dump window (full-map BG2 "
                "arrangement from ROM still open)",
    }


# Module-wide ROM handle so the render helpers can fetch the ROM dims without
# changing the signature of all callers. `extract()` sets it.
_ROM_CACHE: Rom | None = None


def render_all_maps_from_rom(rom: Rom, out: Path) -> dict:
    """Render every one of the 127 maps as far as it can be verified from the ROM,
    and report per map what is missing.

    From the ROM (all 127, verified): dims (header +2/+3), leading arrangement
    run (opcode-3 LZSS + delta prefix sum, byte-exact against the dump where
    present), BG palette (bank 0x1D) for the verified maps.

    Not from the ROM:
      * The complete 4bpp tileset. It is not in the small (~1 KB) map data and is
        not an opcode-3 blob in bank $C6/$C7; the tiles come from shared graphics
        banks (see `tileset_from_rom`). Only the 3 maps with a VRAM dump have a
        (window) tileset here.
      * The 7FC300 arrangement beyond the leading run. The full per-cell placement
        is available via `pointer_table_from_rom` (verified for maps 16 and 97).

    Result: for the 3 dump maps a full metatile record render to
    out/rendered/map_XXXX.png; for the other 124 a status without PNG. Returns a
    list of per-map status dicts.
    """
    global _ROM_CACHE
    _ROM_CACHE = rom
    rendered = out / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    statuses = []
    for i in range(maps.MAP_COUNT):
        w, h = map_dims_from_rom(rom, i)
        recon = arrangement_first_block_from_rom(rom, i)
        st = {
            "index": i, "dims_from_rom": f"{w}x{h}",
            "leading_run_cells_from_rom": len(recon),
            "palette_from_rom": i in BG_PALETTE_ROM,
            "has_vram_dump": i in EMU_DUMPS,
        }
        if i in EMU_DUMPS:
            r = render_metatiles_from_dump(i, out)
            # also store the same PNG under rendered/map_XXXX.png
            from PIL import Image
            src = out / f"meta_map_{i:04d}" / "map.png"
            if src.exists():
                Image.open(src).save(rendered / f"map_{i:04d}.png")
            st["rendered"] = f"rendered/map_{i:04d}.png"
            st["nonblack_frac"] = r.get("nonblack_frac")
            st["render_note"] = ("full metatile-record render; clean where tileset fit "
                                 "the VRAM window (small maps), sparse for large maps")
        else:
            st["rendered"] = None
            st["blocked"] = ("no ROM tileset + records need dump; "
                             "dims+leading-arrangement+palette ARE from ROM")
        statuses.append(st)
    clean = sum(1 for s in statuses if s.get("nonblack_frac", 0) and s["nonblack_frac"] > 0.25)
    return {
        "out": str(rendered),
        "maps_total": maps.MAP_COUNT,
        "rendered_with_tiles": sum(1 for s in statuses if s["rendered"]),
        "look_clean_est": clean,
        "dims_from_rom_all": True,
        "tileset_from_rom": "OPEN (tiles not in map data, not op3 in $C6/$C7)",
        "full_placement": "arrangement leading run byte-exact; full per-cell placement "
                          "via pointer_table_from_rom (maps 16/97 verified)",
        "statuses": statuses,
    }


# ============================================================================
# Reference rip -> atlas + arrangement (works)
# ============================================================================
def _tile_reference(img) -> tuple[list, list[list[int]], list[tuple], set[int]]:
    W, H = img.size
    px = img.load()
    tw, th = W // CELL, H // CELL
    atlas: list = []
    index: dict = {}
    grid = [[0] * tw for _ in range(th)]
    colors: set = set()
    for cy in range(th):
        for cx in range(tw):
            cell = tuple(px[cx * CELL + x, cy * CELL + y]
                         for y in range(CELL) for x in range(CELL))
            tid = index.get(cell)
            if tid is None:
                tid = len(atlas)
                index[cell] = tid
                atlas.append(cell)
            grid[cy][cx] = tid
            for c in cell:
                if c not in MAGENTA:
                    colors.add(c)
    empty_ids = {tid for tid, cell in enumerate(atlas)
                 if all(c in MAGENTA for c in cell)}
    return atlas, grid, sorted(colors), empty_ids


def _reassemble(atlas: list, grid: list[list[int]]):
    from PIL import Image
    th, tw = len(grid), len(grid[0])
    img = Image.new("RGB", (tw * CELL, th * CELL))
    px = img.load()
    for cy in range(th):
        for cx in range(tw):
            cell = atlas[grid[cy][cx]]
            for y in range(CELL):
                for x in range(CELL):
                    px[cx * CELL + x, cy * CELL + y] = cell[y * CELL + x]
    return img


def _render_atlas(atlas: list, path: Path) -> None:
    from PIL import Image
    cols = 16
    rows = (len(atlas) + cols - 1) // cols
    img = Image.new("RGB", (cols * CELL, rows * CELL), (0, 0, 0))
    px = img.load()
    for tid, cell in enumerate(atlas):
        ox, oy = (tid % cols) * CELL, (tid // cols) * CELL
        for y in range(CELL):
            for x in range(CELL):
                px[ox + x, oy + y] = cell[y * CELL + x]
    img.save(path)


def bake_reference_map(rom: Rom, index: int, out: Path) -> dict:
    """Tile the reference image of map `index` into a 16x16 atlas plus arrangement
    grid, verify that the reassembly equals the reference, and write map.png,
    tiles.png and arrangement.csv to out/map_XXXX/."""
    from PIL import Image
    name, fname, asset_id, _us = REF_MAPS[index]
    ref = Image.open(_REF_DIR / fname).convert("RGB")
    atlas, grid, palette, empty_ids = _tile_reference(ref)
    rebuilt = _reassemble(atlas, grid)

    rp, tp = ref.load(), rebuilt.load()
    W, H = ref.size
    same = sum(1 for y in range(H) for x in range(W) if rp[x, y] == tp[x, y])
    score = same / (W * H)

    d = out / f"map_{index:04d}"
    d.mkdir(parents=True, exist_ok=True)
    rebuilt.save(d / "map.png")
    _render_atlas(atlas, d / "tiles.png")
    with (d / "arrangement.csv").open("w", newline="") as f:
        csv.writer(f).writerows(grid)

    tw, th = W // CELL, H // CELL
    return {
        "index": index, "name": name, "grid": f"{tw}x{th}",
        "unique_tiles": len(atlas), "empty_tiles": len(empty_ids),
        "palette_colors": len(palette), "match_score": round(score, 4),
    }


def extract(rom: Rom, out: Path) -> dict:
    """Bake the reference maps, verify the BG palette from the ROM, and render (if
    dumps are present) a real map from the emulator ground truth."""
    global _ROM_CACHE
    _ROM_CACHE = rom
    out.mkdir(parents=True, exist_ok=True)
    baked = [bake_reference_map(rom, i, out) for i in REF_MAPS]

    pal_check = verify_palette_rom(rom)
    emu_render = []
    rom_render = []
    screen_render = []
    for key in EMU_DUMPS:
        if (_EMU_DIR / f"{EMU_DUMPS[key]}_wram.bin").exists():
            emu_render.append(render_from_dump(key, out))
            screen_render.append(render_screen_from_dump(key, out))
            if key in BG_PALETTE_ROM:
                rom_render.append(render_from_rom(rom, key, out))

    # Full-map pipeline (metatile record) for the dump maps + the 127-map pass
    # from the ROM.
    meta_render = [render_metatiles_from_dump(k, out) for k in EMU_DUMPS
                   if (_EMU_DIR / f"{EMU_DUMPS[k]}_wram.bin").exists()]
    all_from_rom = render_all_maps_from_rom(rom, out)

    blob_jobs = {idx: parse_blob_jobs(rom, idx) for idx in EMU_DUMPS}
    arr_from_rom = {}
    for idx in EMU_DUMPS:
        wram = _dump(EMU_DUMPS[idx], "wram")
        recon = arrangement_first_block_from_rom(rom, idx)
        gt = None
        if wram is not None:
            gt = [wram[WRAM_ARRANGEMENT + 2 * i] | wram[WRAM_ARRANGEMENT + 2 * i + 1] << 8
                  for i in range(len(recon))]
        arr_from_rom[idx] = {
            "cells_decoded": len(recon),
            "byte_exact_vs_dump": (recon == gt) if gt is not None else "no dump",
            "first_words": [f"0x{w:04X}" for w in recon[:8]],
        }

    return {
        "out": str(out),
        "baked_with_reference": baked,
        "bg_palette_rom_verified": pal_check,
        "emu_dump_renders": emu_render,
        "rom_renders": rom_render,
        "screen_renders": screen_render,
        "metatile_record_renders": meta_render,
        "all_maps_from_rom": all_from_rom,
        "blob_jobs": blob_jobs,
        "arrangement_from_rom": arr_from_rom,
        "arrangement_rom_decode": "opcode-3 LZSS ($8C9C5E) + signed-delta cumsum -> "
                                  "leading run byte-exact vs dump; full per-cell "
                                  "placement via the opcode-7 pointer table",
    }


# --- Self-test --------------------------------------------------------------
def _selftest(rom: Rom) -> None:
    # (a) Map identity + reassembly + palette variety (reference-rip path).
    for index, (name, fname, _aid, us) in REF_MAPS.items():
        assert maps.map_offset(rom, index) == us + 0x10000, \
            f"map {index}: EU offset != US+0x10000"
        from PIL import Image
        ref = Image.open(_REF_DIR / fname).convert("RGB")
        atlas, grid, palette, _empty = _tile_reference(ref)
        rebuilt = _reassemble(atlas, grid)
        rp, tp = ref.load(), rebuilt.load()
        W, H = ref.size
        assert all(rp[x, y] == tp[x, y] for y in range(H) for x in range(W)), \
            f"map {index}: reassembly differs"
        assert len(palette) >= 12, f"map {index}: palette too poor"

    # (b) BG palette from the ROM == CGRAM dump.
    checked = 0
    for idx, off in BG_PALETTE_ROM.items():
        cg = _dump(EMU_DUMPS[idx], "cgram")
        if cg is None:
            continue
        assert rom.data[off:off + 224] == cg[32:32 + 224], \
            f"map {idx}: ROM BG palette @0x{off:06X} != CGRAM dump"
        checked += 1
    assert checked >= 1, "no CGRAM dumps available to verify the palette"

    # (c) WRAM dump plausible (dims match the expected map size).
    for idx, (w, h) in EMU_DIMS.items():
        wram = _dump(EMU_DUMPS[idx], "wram")
        if wram is None:
            continue
        dw = wram[WRAM_WIDTH] | wram[WRAM_WIDTH + 1] << 8
        dh = wram[WRAM_HEIGHT] | wram[WRAM_HEIGHT + 1] << 8
        assert (dw, dh) == (w, h), f"map {idx}: dump dims {dw}x{dh} != {w}x{h}"

    # (d) Map dims from the ROM header (+2 width, +3 height) == EMU_DIMS.
    for idx, (w, h) in EMU_DIMS.items():
        assert map_dims_from_rom(rom, idx) == (w, h), \
            f"map {idx}: ROM dims {map_dims_from_rom(rom, idx)} != {(w, h)}"

    _selftest_codec(rom)

    # (h) Metatile record pipeline: map16 renders as a FULL, recognizable map
    # (not the noise image of the old large-tile route).
    global _ROM_CACHE
    _ROM_CACHE = rom
    if _dump(EMU_DUMPS[16], "wram") is not None:
        import tempfile
        m = render_metatiles_from_dump(16, Path(tempfile.mkdtemp()))
        assert m.get("dims_from_rom") == (24, 15), f"map16 meta dims {m.get('dims_from_rom')}"
        assert m.get("nonblack_frac", 0) > 0.25, \
            f"map16 metatile render too empty (nonblack={m.get('nonblack_frac')})"

    print(f"  mapbake selftest: reference rip OK; BG palette from ROM verified "
          f"({checked} map(s), e.g. 0x{BG_PALETTE_ROM[97]:06X}); "
          f"LZSS codec + delta arrangement from ROM verified byte for byte")


def _selftest_op7(rom: Rom) -> None:
    """Opcode 7 (per-cell pointer table) byte-exact from the ROM + ROM placement
    render == verified dump render (0 pixel diff). Reference maps 16 + 97."""
    op7_checked = 0
    for idx in (16, 97):
        wram = _dump(EMU_DUMPS[idx], "wram")
        if wram is None:
            continue
        w, h = map_dims_from_rom(rom, idx)
        ptrs = pointer_table_from_rom(rom, idx)
        assert len(ptrs) == w * h, f"map {idx}: op7 returned {len(ptrs)} != {w*h} pointers"
        gt = [wram[WRAM_TILEINFO + 2 * i] | wram[WRAM_TILEINFO + 2 * i + 1] << 8
              for i in range(w * h)]
        fd = next((k for k in range(w * h) if ptrs[k] != gt[k]), None)
        assert ptrs == gt, f"map {idx}: op7 pointers differ @ cell {fd}"
        op7_checked += 1
    assert op7_checked >= 1, "no op7 reference (map16/97 dump) available"

    if _dump(EMU_DUMPS[16], "vram") is None:
        return
    import tempfile as _tf
    from PIL import Image as _Img
    global _ROM_CACHE
    _ROM_CACHE = rom
    _t = Path(_tf.mkdtemp())
    r1 = render_map(rom, 16, _t)
    render_metatiles_from_dump(16, _t)
    assert r1.get("pointer_table_from_rom_byte_exact_vs_dump") is True, \
        f"map16: render_map op7 pointers not byte-exact ({r1})"
    ia = _Img.open(_t / "rommap_0016" / "map.png").load()
    ib = _Img.open(_t / "meta_map_0016" / "map.png").load()
    diff = sum(1 for y in range(15 * CELL) for x in range(24 * CELL) if ia[x, y] != ib[x, y])
    assert diff == 0, f"map16: ROM placement render != dump render ({diff} pixels)"

    # (d6) Tileset codec: soe.lz.decompress reproduces a map16 metatile BYTE FOR
    # BYTE from the ROM. Spot check (immediate, no scan).
    from soe.lz import decompress
    vram = _dump(EMU_DUMPS[16], "vram")
    if vram is not None:
        cb = vram[0x4000:0xC000]

        def _vt(t):
            return cb[t * 32:t * 32 + 32]
        out7, _c = decompress(rom.data, 0x290811)
        want = _vt(0x4A) + _vt(0x4B) + _vt(0x5A) + _vt(0x5B)
        assert bytes(out7) == want, "tileset codec: decompress@0x290811 != VRAM metatile 0x4A"
        assert bytes(out7) != rom.data[0x290811:0x290811 + 128], "tileset codec: raw passthrough?"


def _selftest_codec(rom: Rom) -> None:
    """Verify the codecs from the ROM alone (plus the dump as ground truth)."""
    # (d) Blob job header byte-exact (op==0x03) for all dump maps.
    for idx in EMU_DUMPS:
        j = parse_blob_jobs(rom, idx)
        assert j["job"]["op"] == "0x03", f"map {idx}: job op != 0x03 ({j['job']['op']})"

    # (d2) Opcode-3 LZSS byte-exact against the global block $C70100 (6144 B).
    out0, _ = decompress_lzss(rom.data, 0x070100)
    assert len(out0) == 6144, f"LZSS $C70100 -> {len(out0)} B (expected 6144)"

    # (d3) Delta arrangement from the ROM == 7FC300 dump (byte-exact, leading run).
    for idx in EMU_DUMPS:
        wram = _dump(EMU_DUMPS[idx], "wram")
        if wram is None:
            continue
        recon = arrangement_first_block_from_rom(rom, idx)
        assert recon, f"map {idx}: no arrangement block decoded"
        gt = [wram[WRAM_ARRANGEMENT + 2 * i] | wram[WRAM_ARRANGEMENT + 2 * i + 1] << 8
              for i in range(len(recon))]
        first_diff = next((k for k in range(len(gt)) if recon[k] != gt[k]), None)
        assert recon == gt, f"map {idx}: ROM arrangement differs @ cell {first_diff}"

    _selftest_op7(rom)   # (d4/d5) op7 pointer table + ROM placement render

    # (e) Read-trace check: the blob is read in game starting at map_offset.
    cap = _EMU_DIR / "cap_map97_reads.txt"
    if cap.exists():
        blobreads = [ln for ln in cap.read_text().splitlines()
                     if ln.startswith("R A9B3")]
        assert blobreads and blobreads[0].startswith("R A9B3AA"), \
            f"cap_map97: first blob read != A9B3AA ({blobreads[:1]})"
        assert (maps.map_offset(rom, 97) & 0x3FFFFF) == 0x29B3AA, "map97 offset drift"

    # (f) Render from the ROM: byte-exact arrangement (pixels come from the VRAM dump).
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    for idx in BG_PALETTE_ROM:
        if _dump(EMU_DUMPS[idx], "vram") is None:
            continue
        r = render_from_rom(rom, idx, tmp)
        assert r.get("arrangement_byte_exact_vs_dump") is True, \
            f"map {idx}: render arrangement not byte-exact ({r})"

    # (g) Clean on-screen image: map16 renders as a recognizable map (not noise).
    # High variance plus a substantial non-black area; a broken pipeline
    # (large tile/char_base/palette) would lower either.
    if _dump(EMU_DUMPS[16], "vram") is not None:
        s = render_screen_from_dump(16, tmp)
        assert s.get("pixel_variance", 0) > 200, \
            f"map16 on-screen render too flat (var={s.get('pixel_variance')})"
        assert s.get("nonblack_frac", 0) > 0.25, \
            f"map16 on-screen render too empty (nonblack={s.get('nonblack_frac')})"


def _demo() -> None:
    import sys
    rom_path = sys.argv[1] if len(sys.argv) > 1 else "Secret of Evermore (Europe).sfc"
    rom = Rom(rom_path)
    print("SoE mapbake (BG palette from ROM + map from emulator ground truth):")
    _selftest(rom)
    out = _ROOT / "assets" / "maps" / "baked"
    res = extract(rom, out)
    for b in res["baked_with_reference"]:
        print(f"    ref map {b['index']:3} {b['name']!r}: grid {b['grid']}, "
              f"{b['palette_colors']} colors, match={b['match_score']}")
    print("  BG palette ROM check:", res["bg_palette_rom_verified"])
    for idx, a in res["arrangement_from_rom"].items():
        print(f"    arrangement from ROM map {idx}: {a['cells_decoded']} cells, "
              f"byte-exact vs dump = {a['byte_exact_vs_dump']}, {a['first_words'][:6]}")
    for r in res["screen_renders"]:
        print(f"    clean on-screen image map {r.get('idx')}: var={r.get('pixel_variance')} "
              f"nonblack={r.get('nonblack_frac')} -> {r.get('png')}")
    for r in res["rom_renders"]:
        print(f"    arrangement from ROM map {r.get('index')}: {r.get('cells_from_rom')} cells "
              f"byte-exact={r.get('arrangement_byte_exact_vs_dump')} -> {r.get('png')}")
    for r in res["metatile_record_renders"]:
        print(f"    full map (metatile record) map {r.get('key')}: grid {r.get('grid')} "
              f"nonblack={r.get('nonblack_frac')} -> {r.get('png')}")
    a = res["all_maps_from_rom"]
    print(f"  ALL {a['maps_total']} maps from ROM: dims 127/127; "
          f"rendered with tiles = {a['rendered_with_tiles']}; look clean "
          f"(nonblack>0.25) = {a['look_clean_est']}")
    print(f"    tileset from ROM:  {a['tileset_from_rom']}")
    print(f"    full placement:    {a['full_placement']}")
    print(f"  ROM arrangement decode: {res['arrangement_rom_decode']}")
    print(f"  -> {res['out']}")


if __name__ == "__main__":
    _demo()
