"""Secret of Evermore graphics decompressors (faithful port from SoETilesViewer).

SoE stores 16x16 graphics blocks (4bpp, 128 bytes uncompressed = four 8x8 SNES
tiles) with TWO different codecs. Both are ported 1:1 from
github.com/black-sliver/SoETilesViewer (not guessed):

1. **Sprite codec** (``decompress_sprite``), from ``spriteblock.h::loadPixels``.
   Simple zero-word RLE: 1 status byte gates 8 words (16 bytes of output). Per
   bit (LSB first): bit=0 -> copy a literal word from the stream, bit=1 -> the
   word is 0x0000 (output stays 0, nothing is read). This is the codec that
   yields the real sprites/objects of the Europe ROM (VERIFIED, see __main__
   and the demo PNG).

2. **Tile/tileset codec** (``decompress``), from ``tile.h::loadPixels``.
   The 16-mode RLE/LZ. A control byte gates 8 words; set bits pull a 4-bit
   mode from a SECOND, parallel nibble stream. Ported faithfully and checked
   with synthetic vectors in the self-test. Verified on real Europe ROM data by
   known plaintext: ``decompress(rom, 0x290811)`` equals the map-16 VRAM tiles
   $4A/$4B/$5A/$5B, and a whole-ROM scan reproduces 239 of 256 map-16 large
   tiles byte-exact (docs/compression.md). Still open: the Europe table from a
   tile block index to its ROM offset is not located (the US table is at SNES
   0xEE0000; in the Europe ROM that address holds the 16x16 sprite block table).

Addressing: HiROM, no SMC header -> file offset == (snes_addr & 0x3FFFFF)
(exactly like SoETilesViewer ``rom.h::mapaddr`` = ``addr & ~0xc00000``).

Byte layout of a decompressed 16x16 block: four consecutive 32-byte SNES 4bpp
tiles (subblock index = j + 2*l, i.e. 0=top-left, 1=top-right, 2=bottom-left,
3=bottom-right). Each 32-byte tile can be decoded directly with
``Rom.decode_4bpp``.
"""
from __future__ import annotations

# 16x16 4bpp = 4 subblocks of 8x8 = 4*8*8/2 = 128 bytes.
UNCOMPRESSED_16 = 128

# --- Address helper (HiROM, headerless) ---------------------------------------
def snes_to_file(addr: int) -> int:
    """SNES address -> file offset (HiROM). Like SoETilesViewer: addr & ~0xC00000."""
    return addr & 0x3FFFFF


# --- Verified offsets (Europe ROM) --------------------------------------
# Start of a sequentially stored chain of real sprite blocks, found by chain
# scan and visually confirmed as real graphics (drops, arrows, icons ...).
# The sprite blocks are contiguous: next block = offset + consumed bytes.
SPRITE_CHAIN_START_EU = 0x21FFD4

# US pointer tables from SoETilesViewer (reference only, they do not apply to Europe):
#   Tile (16-mode):        SNES 0xEE0000, data pointers of 3 bytes each, absolute
#   SpriteBlock 16x16:     SNES 0xEC0000 (+base 0xD90000), bit23 = compressed
#   SpriteBlock 8x8:       SNES 0xD80000 (+base 0xD10000), bit23 = compressed
# Europe ROM (verified, see soe/boysprites.py and docs/sprites.md): the 16x16 sprite
# block table is at SNES 0xEE0000 (bank = (byte2 & 0x7F) + 0x5A), the 8x8 table at
# SNES 0xD90000 (bank = (byte2 & 0x7F) + 0x52); index = block * 3, no base added,
# bit 7 of byte2 = compressed. The Europe tile (16-mode) table is not located.
US_TILE_PTR_TABLE = 0xEE0000
US_SPRITE16_PTR_TABLE = 0xEC0000
US_SPRITE16_DATA_BASE = 0xD90000


# ---------------------------------------------------------------------------
# Codec 1: Sprite (spriteblock.h), zero-word RLE
# ---------------------------------------------------------------------------
def decompress_sprite(data: bytes, offset: int, uncompressed_size: int = UNCOMPRESSED_16) -> tuple[bytes, int]:
    """Decompress a sprite block starting at ``offset``.

    Returns (decompressed bytes, consumed input bytes). The byte count allows
    walking a sprite chain sequentially (next block = offset+n).

    Format (faithful from spriteblock.h::loadPixels, compressed branch):
    ``uncompressed_size/2/8`` groups; each group has 1 status byte, followed by
    one 2-byte word from the stream for every clear bit. Status bit (LSB first):
    1 = word 0x0000 (read nothing), 0 = copy the word literally.
    """
    out = bytearray(uncompressed_size)
    src = offset
    dst = 0
    for _ in range(uncompressed_size // 2 // 8):   # 1 bit per output word
        bits = data[src]
        src += 1
        for _bit in range(8):
            if bits & 1:                            # word is 0x0000
                dst += 2
            else:                                   # copy word literally
                out[dst] = data[src]
                out[dst + 1] = data[src + 1]
                src += 2
                dst += 2
            bits >>= 1
    return bytes(out), src - offset


# ---------------------------------------------------------------------------
# Codec 2: Tile/tileset (tile.h), 16-mode RLE/LZ with parallel nibble control
# ---------------------------------------------------------------------------
def decompress(data: bytes, offset: int, uncompressed_size: int = UNCOMPRESSED_16) -> tuple[bytes, int]:
    """Decompress a 16x16 tile block starting at ``offset`` (info byte).

    Returns (decompressed bytes, consumed input bytes).

    Faithful from tile.h::loadPixels. The first byte is the info byte:
      * bit7 = 0  -> UNCOMPRESSED. Lower 7 bits + 1 = number of words directly
        after it; missing words up to 128 bytes are filled with the last word.
      * bit7 = 1  -> COMPRESSED. Lower 7 bits = dataOffset: the main stream
        (control bytes + literals + mode data bytes) starts at
        ``offset+dataOffset``; the 4-bit modes live in a PARALLEL nibble stream
        starting at ``offset+1``.

    Compression modes (one 4-bit value each, high nibble first; ``P`` = previous word):
      0  -> 0x0000                       8  -> 0xVVVV (V twice, from data)
      1  -> 0x00ff (low=ff)              9  -> repeat P once
      2  -> 0xff00 (high=ff)            10  -> repeat P twice
      3  -> 0xffff                      11  -> repeat P three times
      4  -> low=data,  high=00          12  -> repeat P (4+N) times (N = next nibble)
      5  -> low=data,  high=ff          13  -> low=P.low,  high=data
      6  -> low=00,    high=data        14  -> low=data,  high=P.high
      7  -> low=ff,    high=data        15  -> low=V, high=V^0xff (V from data)
    (Byte order in memory is little-endian: low first, then high.)
    """
    info = data[offset]
    out = bytearray(uncompressed_size)

    if not (info & 0x80):
        # --- uncompressed -------------------------------------------------
        word_count = (info & 0x7F) + 1
        if word_count > uncompressed_size // 2:
            word_count = 64                          # tile.h: "or maybe it's just junk"
        n = word_count * 2
        out[0:n] = data[offset + 1:offset + 1 + n]
        for i in range(n, uncompressed_size, 2):     # repeat the last word until full
            out[i] = out[i - 2]
            out[i + 1] = out[i - 1]
        return bytes(out), 1 + n

    # --- compressed -------------------------------------------------------
    data_ptr = offset + (info & 0x7F)                # main stream
    cmd_ptr = offset + 1                             # parallel 4-bit mode stream
    cmd_second_half = False
    op = 0

    def read4() -> int:
        nonlocal cmd_ptr, cmd_second_half
        v = data[cmd_ptr]
        v = (v & 0x0F) if cmd_second_half else (v >> 4)
        if cmd_second_half:
            cmd_ptr += 1
        cmd_second_half = not cmd_second_half
        return v

    while op < uncompressed_size:
        indicators = data[data_ptr]
        data_ptr += 1
        for _bit in range(8):
            if not (indicators & 0x80):
                # uncompressed word: 2 literal bytes
                out[op] = data[data_ptr]
                out[op + 1] = data[data_ptr + 1]
                data_ptr += 2
                op += 2
            else:
                mode = read4()
                if mode == 0:
                    out[op] = 0x00; out[op + 1] = 0x00; op += 2
                elif mode == 1:
                    out[op] = 0xFF; out[op + 1] = 0x00; op += 2
                elif mode == 2:
                    out[op] = 0x00; out[op + 1] = 0xFF; op += 2
                elif mode == 3:
                    out[op] = 0xFF; out[op + 1] = 0xFF; op += 2
                elif mode == 4:
                    out[op] = data[data_ptr]; data_ptr += 1; out[op + 1] = 0x00; op += 2
                elif mode == 5:
                    out[op] = data[data_ptr]; data_ptr += 1; out[op + 1] = 0xFF; op += 2
                elif mode == 6:
                    out[op] = 0x00; out[op + 1] = data[data_ptr]; data_ptr += 1; op += 2
                elif mode == 7:
                    out[op] = 0xFF; out[op + 1] = data[data_ptr]; data_ptr += 1; op += 2
                elif mode == 8:
                    v = data[data_ptr]; data_ptr += 1
                    out[op] = v; out[op + 1] = v; op += 2
                elif 9 <= mode <= 12:
                    n = mode - 9 + 1 + (read4() if mode == 12 else 0)
                    for _ in range(n):
                        if op < 2:                    # no predecessor -> zero
                            out[op] = 0; out[op + 1] = 0; op += 2
                        else:
                            out[op] = out[op - 2]; op += 1
                            out[op] = out[op - 2]; op += 1
                        if op >= uncompressed_size:
                            break
                elif mode == 13:
                    if op < 2:
                        out[op] = 0; op += 1
                    else:
                        out[op] = out[op - 2]; op += 1
                    out[op] = data[data_ptr]; data_ptr += 1; op += 1
                elif mode == 14:
                    out[op] = data[data_ptr]; data_ptr += 1; op += 1
                    if op < 2:
                        out[op] = 0; op += 1
                    else:
                        out[op] = out[op - 2]; op += 1
                elif mode == 15:
                    v = data[data_ptr]; data_ptr += 1
                    out[op] = v; out[op + 1] = v ^ 0xFF; op += 2
            if op >= uncompressed_size:
                break
            indicators = (indicators << 1) & 0xFF
        if op >= uncompressed_size:
            break

    consumed = max(data_ptr, cmd_ptr) - offset
    return bytes(out), consumed


# Alias: the generic 4bpp graphics decompression.
decompress_gfx = decompress


# ---------------------------------------------------------------------------
# Self-test + demo
# ---------------------------------------------------------------------------
def _selftest_tile_codec() -> None:
    """Synthetic vectors for the 16-mode codec (checks modes + nibble stream)."""
    # Vector A: 64 words, all mode 0 -> 128 zero bytes.
    #   info: compressed, dataOffset = 1 + 32 (cmd) = 33 = 0x21 -> 0x80|0x21 = 0xA1
    #   cmd:  32 bytes 0x00 (64 nibbles = 64x mode 0)
    #   data: 8 control bytes 0xFF (all 8 bits set = all compressed)
    block_a = bytes([0xA1] + [0x00] * 32 + [0xFF] * 8)
    out_a, _ = decompress(block_a, 0)
    assert out_a == bytes(128), "Vector A (mode 0) failed"

    # Vector B: literal + mode 9 (repeat) + mode 3 (0xffff), rest mode 0.
    #   Word0 literal 0x3412 (bytes 12 34), Word1 mode 9 -> 3412, Word2 mode 3 -> ffff,
    #   Word3..7 literal 0x0000, then 56 words of mode 0.
    #   Control byte 0 = 0b01100000 = 0x60 (bit7=0 literal, bits 6/5 set).
    #   cmd: byte 0 = 0x93 (nibble 9 then 3), then 28 bytes 0x00 (56 nibbles of mode 0).
    #     -> dataOffset = 1 + 29 = 30 = 0x1E -> info = 0x9E
    #   data: [0x60, 12,34, 00*10, 0xFF*7]
    block_b = bytes([0x9E, 0x93] + [0x00] * 28 + [0x60, 0x12, 0x34] + [0x00] * 10 + [0xFF] * 7)
    out_b, _ = decompress(block_b, 0)
    expected_b = bytes([0x12, 0x34, 0x12, 0x34, 0xFF, 0xFF]) + bytes(128 - 6)
    assert out_b == expected_b, f"Vector B (modes 9/3/literal) failed: {out_b[:8].hex()}"

    # Vector C: uncompressed. info=0x02 -> 3 words, then filled with the last one.
    block_c = bytes([0x02, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
    out_c, consumed_c = decompress(block_c, 0)
    assert consumed_c == 1 + 6
    assert out_c[:6] == bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
    assert out_c[6:8] == bytes([0x55, 0x66])         # last word repeated
    assert out_c[126:128] == bytes([0x55, 0x66])
    print("  16-mode codec: vectors A/B/C OK")


def _selftest_sprite_codec() -> None:
    """Sprite codec round trip on a hand-built block."""
    # 8 groups. Group 0: status 0x01 (bit0 set -> word0=0000), rest literal 0xBEEF.
    # Remaining 7 groups: status 0xFF (all words 0000, no data).
    block = bytearray()
    block.append(0x01)
    block += b"\xEF\xBE" * 7          # 7 literal words
    block += bytes([0xFF]) * 7        # 7 groups completely zeroed
    out, consumed = decompress_sprite(bytes(block), 0)
    assert consumed == 1 + 14 + 7
    assert out[0:2] == b"\x00\x00"    # word0 zeroed
    assert out[2:4] == b"\xEF\xBE"    # word1 literal
    assert out[16:] == bytes(112)     # groups 1..7 all 0
    print("  Sprite codec: round trip OK")


def _demo() -> None:
    """Decompress the real sprite chain of the Europe ROM and render a PNG."""
    import statistics
    from pathlib import Path
    from PIL import Image
    from soe.rom import Rom

    rom = Rom("Secret of Evermore (Europe).sfc")
    data = rom.data

    # Decompress 160 sprite blocks sequentially from the verified chain start.
    offset = SPRITE_CHAIN_START_EU
    blocks = []
    for _ in range(160):
        if offset >= len(data) - 8:
            break
        block, consumed = decompress_sprite(data, offset)
        blocks.append(block)
        offset += consumed

    # Hard assertions: plausible length + real pixel variance (not noise,
    # but not an empty area either).
    assert all(len(b) == UNCOMPRESSED_16 for b in blocks), "unexpected block length"
    all_px = []
    for b in blocks:
        for t in range(4):
            for row in rom.decode_4bpp(b[t * 32:t * 32 + 32]):
                all_px.extend(row)
    var = statistics.pvariance(all_px)
    distinct = len(set(all_px))
    assert var > 1.0, f"too little variance (noise/empty?): {var}"
    assert distinct >= 6, f"too few color values: {distinct}"
    # real sprites have large transparent (0) areas:
    zero_frac = all_px.count(0) / len(all_px)
    assert zero_frac > 0.15, f"hardly any transparency -> probably not a real sprite sheet: {zero_frac:.2f}"

    # Render PNG (16 blocks per row, each 16x16, subblock j+2l).
    cols, cell = 16, 16
    rows = (len(blocks) + cols - 1) // cols
    img = Image.new("L", (cols * cell, rows * cell), 0)
    px = img.load()
    for idx, b in enumerate(blocks):
        sub = [rom.decode_4bpp(b[t * 32:t * 32 + 32]) for t in range(4)]
        bx, by = (idx % cols) * cell, (idx // cols) * cell
        for l in range(2):
            for j in range(2):
                s = sub[j + 2 * l]
                for y in range(8):
                    for x in range(8):
                        px[bx + j * 8 + x, by + l * 8 + y] = s[y][x] * 17
    img = img.resize((img.width * 4, img.height * 4), Image.NEAREST)
    out_path = Path("assets/gfx/decompressed_demo.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    print(f"  Demo: {len(blocks)} sprite blocks from {SPRITE_CHAIN_START_EU:#08x}, "
          f"variance={var:.1f}, colors={distinct}, transparency={zero_frac:.0%}")
    print(f"  PNG -> {out_path}")


if __name__ == "__main__":
    print("SoE LZ self-test:")
    _selftest_tile_codec()
    _selftest_sprite_codec()
    _demo()
    print("All checks passed.")
