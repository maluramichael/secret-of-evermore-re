# Compression

Secret of Evermore (Europe) uses several unrelated codecs. This document describes each
one, how the game calls it, and how far it is verified. Map-specific use of the codecs is
in [maps.md](maps.md), sprite use in [sprites.md](sprites.md), the text codec in
[text.md](text.md).

Address convention: SNES addresses are written `$BBAAAA`. The ROM is HiROM without a copier
header, so for every ROM bank used here (`$C0-$EF`, the `$80-$BF` upper-half mirror and
`$40-$7D`) the file offset is `snes & 0x3FFFFF`. Example: `$8C9C22` and `$CC9C22` are the
same bytes at file `0x0C9C22`.

## Overview

| Codec | Used for | Game routine | Python | Status |
|---|---|---|---|---|
| Dispatcher opcode 0 | raw block copy | `$8C9C46` | not needed | verified (decompiler) |
| Dispatcher opcode 3, LZSS | map arrangement, map record data, graphics blobs in banks `$C6`/`$C7` | `$8C9C5E` | `soe/mapbake.py::decompress_lzss` | verified byte-exact |
| Dispatcher opcode 7, 2D word LZ | per-cell record pointer table of a map | `$8C9EFA` | `soe/mapbake.py::_Op7`, `pointer_table_from_rom` | byte-exact on maps 16 and 97, see open points |
| 16-mode tile codec | 16x16 BG tile graphics blocks (4bpp) | not located | `soe/lz.py::decompress` | byte-exact against VRAM (known plaintext) |
| Zero-word sprite codec | 8x8 and 16x16 sprite graphics blocks | inside `$8096FD` and `$80A4B4` | `soe/lz.py::decompress_sprite` | verified (decoded frames match emulator OAM/VRAM pixel for pixel) |
| Text dictionary codec | dialogue and story text | see [text.md](text.md) | `soe/dialogue.py` | see [text.md](text.md) |

The dispatcher codecs (0, 3, 7) and the two graphics codecs share nothing. The 16-mode
tile codec and the zero-word sprite codec were first described by the third-party
SoETilesViewer project (`tile.h`, `spriteblock.h`); this repo ports them and verifies them
against the Europe ROM.

## The decompression dispatcher `$8C9C22`

`JSL $8C9C22` processes one compressed block ("blob"). The routine runs in bank `$8C`.
It is called from at least 11 sites (byte scan for `JSL $8C9C22`).

### Call interface

The caller sets four 16-bit direct-page variables (native mode, `REP #$30`, D = 0) and
then calls the dispatcher:

| DP | Meaning |
|---|---|
| `$36` | source offset (16-bit) |
| `$38` | source bank |
| `$3A` | destination offset (16-bit) |
| `$3C` | destination bank (in all observed calls `$7F`) |

The destination is chosen entirely by the caller. Nothing in the blob encodes where the
output goes. Observed caller setups:

```
src $C7:0100 -> dst $7F:0000
src $C7:13A0 -> dst $7F:0000   (the blob stored directly after the previous one)
src $C7:163B -> dst $7F:0000
src $C6:1800 -> dst $7F:0000
map loader  -> dst $7F:C300   (map arrangement)
map loader  -> dst $7F:0000   (map record pointer table, opcode 7)
map loader  -> dst $7F:BASE   (map record data, BASE = width*height*2)
```

Blobs in bank `$C7` are stored back to back: decompressing the blob at `$C70100` ends
exactly at `$C713A0`, the source of the next caller.

### Blob header and dispatch

```
byte 0     opcode
bytes 1-2  16-bit parameter (little-endian); stored to DP $34
bytes 3-   codec payload
```

```asm
8C9C22  LDY #$0000
        LDA [$36],Y        ; word 0
        INY
        AND #$00FF         ; opcode = low byte
        ASL A
        TAX
        LDA [$36],Y        ; bytes 1..2 = parameter
        INY
        INY
        STA $34
        JMP ($9C36,X)      ; jump table $8C9C36
```

Jump table `$8C9C36`:

| Opcode | Handler | Meaning |
|---|---|---|
| 0 | `$8C9C46` | raw block copy |
| 1 | `$8C9C5C` | `STP` (invalid, guard) |
| 2 | `$8C9C5D` | `STP` (invalid, guard) |
| 3 | `$8C9C5E` | LZSS |
| 4 | `$8C9EF9` | `RTL` (no-op) |
| 5 | `$0000` | null entry, unused |
| 6 | `$0000` | null entry, unused |
| 7 | `$8C9EFA` | 2D-context word LZ (record pointer table) |

## Opcode 0: raw block copy (`$8C9C46`)

Copies `param + 1` bytes (as `(param + 1) >> 1` words) from `src + 3` to the destination.
No compression. Confirmed by the decompiler.

## Opcode 3: LZSS (`$8C9C5E`)

Header: `03 <decompressed_size:u16le>`, followed by an MSB-first bitstream.

Setup in the handler:

- `$2A/$2C` = source + 3 (start of the bitstream); `$02/$04` = destination.
- `DBR = $7F` for the whole routine (`PEA $7F7F; PLB; PLB`).
- 4096-byte ring buffer in WRAM `$7FA000-$7FAFFF`. `$08` = ring write pointer (starts at
  `$A000`), `$0C` = ring end (`$B000`), `$0A` = bit index.
- Bit-mask table `$8C9DDB` (16 words `$8000, $4000, ..., $0001`), so bits are consumed
  MSB first.

Per symbol (loop at `$8C9C92`):

- Read 1 control bit.
- Bit = 1, literal: read 8 bits as a byte. Write it to the output and to the ring at the
  write pointer; advance both; the ring pointer wraps from `$B000` to `$A000`.
- Bit = 0, match: read a 16-bit token.
  - `V = token >> 4` (12-bit ring position), `len = (token & 0x0F) + 2` (2 to 17 bytes).
  - `V == 0` ends the stream.
  - Copy `len` bytes starting at ring offset `V - 1` (the code computes
    `X = V + $9FFF`). Each copied byte goes to the output and back into the ring
    (standard LZSS self-reference).
  - Tokens `>= $FEE0` take a variant copy loop at `$8C9D9F` that also wraps the ring read
    pointer at `$B000`.

The handlers around `$8C9DFB`, `$8C9E4D` and `$8C9EA7` are the bit-aligned reader (bit
position in `$0A`, byte offset in Y). They do not affect the format. The match copy
routine is at `$8C9D5E`.

Reference decoder (equivalent to `soe/mapbake.py::decompress_lzss`):

```python
def decompress_lzss(rom, src):
    size = rom[src + 1] | rom[src + 2] << 8
    p, bitbuf, nbits = src + 3, 0, 0
    ring, wp, out = bytearray(0x1000), 0, bytearray()
    def bit():
        nonlocal p, bitbuf, nbits
        if nbits == 0:
            bitbuf, p, nbits = rom[p], p + 1, 8
        nbits -= 1
        return (bitbuf >> nbits) & 1
    def bits(n):
        v = 0
        for _ in range(n):
            v = (v << 1) | bit()
        return v
    while len(out) < size:
        if bit():                      # literal
            b = bits(8)
            out.append(b); ring[wp] = b; wp = (wp + 1) & 0xFFF
        else:                          # match
            tok = bits(16); v = tok >> 4
            if v == 0:
                break
            for i in range((tok & 0x0F) + 2):
                b = ring[(v - 1 + i) & 0xFFF]
                out.append(b); ring[wp] = b; wp = (wp + 1) & 0xFFF
    return out
```

Verification: the blob at `$C70100` (header `03 00 18`, size `$1800`) decodes to exactly
6144 bytes, reaches `V == 0` at the declared size and ends at `$C713A0`, the source of the
next caller. The map arrangement blocks decode byte-exact against WRAM dumps of
`$7FC300` (after the prefix sum described in [maps.md](maps.md)).

## Opcode 7: 2D-context word LZ (`$8C9EFA`)

Opcode 7 produces the per-cell record pointer table of a map at `$7F0000`: one 16-bit
word per map cell, each word a byte offset (from `$7F0000`) to that cell's 8-byte record.
It is a 16-bit-word LZ with prediction from the cell above and the cell to the left.

Common pitfall: opcode 7 is not a tile or bitplane codec. That reading appears in early
notes; an exec trace of a map load shows it writing the pointer table.

### Parameters

The handler reads its parameters from WRAM. All of them follow from the map header (see
[maps.md](maps.md)):

| WRAM | Meaning | Value |
|---|---|---|
| `$0FAA` | BASE: size of the pointer table in bytes, and start of the record area | `width * height * 2` |
| `$0F48` | stride of the "cell above" predictor | `width * 2` |
| `$0FC6` | number of persistent pre-existing records | 0 on all observed maps |
| `$0FAC` | init fill count * 8 | overfilling to `width * height` slots is safe |

Blob header: `07 <BASE:u16le>`, bitstream (MSB first) from `src + 3`. Output is
`width * height` words.

### Algorithm

- Init: every 8-byte record slot at `BASE + 8k` is pre-filled (words at `+0, +2, +4, +6`)
  with its own pointer `BASE + 8k`. The new-word generator `$0C` starts at
  `BASE + 8 * $0FC6`.
- Two context registers: `$26` = pointer of the cell above (`out[Y - width]`), `$12` =
  pointer of the cell to the left (last written word).
- Each output word starts with a prefix code; the top 5 bits index the jump table
  `$8CA08C`:

| Prefix | Bits | Output word |
|---|---|---|
| `1....` | 1 | `[$26]` (copy cell above, most common) |
| `000..` | 3 | `[$12 + 2]` |
| `00100` | 5 | `[$26 + 4]` |
| `00101` | 5 | `[$12 + 6]` |
| `0011.` | 4 | new word `$0C`, then `$0C += 8` (next record) |
| `01...` | 2 + n | general back reference: read n bits as index, word = `BASE + index * 8` |

- The back-reference width n (DP `$14`) starts at 0 (with `$0FC6 = 0`) and grows by one
  bit each time the count of new words reaches the next power of two (mask in `$10`).
  Maps with more than 256 records take the wide path (`$8CA080`).
- After each word, `$8C9F88` updates `$26` and `$12` and a two-deep history kept inside
  the record slots (`+4` holds the previous `+0` value for the cell above, `+6` the
  previous `+2` value for the left context). See `_Op7._update` for the exact rule.

Handlers: `$8C9F72` bit reader, `$8CA0F0` bit-reader cascade table, `$8CA134` index
extractor table, `$8C9F88` context update, `$8C9FC5` new word, `$8C9FEA` copy cell
above, `$8CA00A` and `$8CA01D` history copies, `$8CA030` and `$8CA080` back references.

Verification: the Python port reproduces the `$7F0000` WRAM dumps byte-exact for map 16
(360 cells) and map 97 (2256 cells, including the wide path), with all parameters taken
from the ROM header.

Open: on map 24 the port diverges from word 298 on (an unexplained jump of the
new-word generator from `0x0B70` to `0x0EC0`, 106 records skipped without being
emitted). The cause is not known.

## 16-mode tile codec (BG tile graphics)

One call decodes one 16x16 block: 128 bytes, four 4bpp 8x8 tiles in the order top-left,
top-right, bottom-left, bottom-right.

First byte (info byte):

- Bit 7 = 0, uncompressed: `(info & 0x7F) + 1` words follow directly. If that is fewer than
  64 words, the last word is repeated until 128 bytes are filled. (Counts above 64 are
  clamped to 64.)
- Bit 7 = 1, compressed: `info & 0x7F` is the offset (from the info byte) of the main
  stream. A second, parallel stream of 4-bit mode nibbles starts at `offset + 1`, high
  nibble first.

Main stream: one indicator byte gates the next 8 output words, MSB first. Indicator bit
0 = copy a literal word (2 bytes) from the main stream. Indicator bit 1 = read a mode
nibble and produce one word (or a run) as follows (`P` = previous output word, `D` = next
byte from the main stream, words are little-endian):

| Mode | Output | Mode | Output |
|---|---|---|---|
| 0 | `0x0000` | 8 | low = high = `D` |
| 1 | low `FF`, high `00` | 9 | repeat `P` once |
| 2 | low `00`, high `FF` | 10 | repeat `P` twice |
| 3 | `0xFFFF` | 11 | repeat `P` three times |
| 4 | low `D`, high `00` | 12 | repeat `P` (4 + N) times, N = next nibble |
| 5 | low `D`, high `FF` | 13 | low = `P.low`, high = `D` |
| 6 | low `00`, high `D` | 14 | low = `D`, high = `P.high` |
| 7 | low `FF`, high `D` | 15 | low = `D`, high = `D ^ 0xFF` |

Decoding stops at 128 output bytes. Reference implementation: `soe/lz.py::decompress`.

Verification: `decompress(rom, 0x290811)` equals the VRAM tiles `$4A, $4B, $5A, $5B` of
map 16 (one full large tile, relative to BG char base `$4000`). A whole-ROM scan
(decompress at every offset, compare against the map-16 VRAM tile groups) reproduces 239
of 256 map-16 large tiles byte-exact (31965 of 32768 bytes of the char base). The blocks
are stored individually and scattered over many file banks (`0x05`, `0x06`, `0x07`,
`0x12`, `0x1C`, `0x2F` and others).

Open:

- The 65816 routine that runs this codec in the game is not identified.
- The Europe table that maps a tile block index to its ROM offset is not located. The
  offsets above were found by known plaintext against a VRAM dump.

Common pitfall: SoETilesViewer gives `$EE0000` as the tile pointer table for the US ROM.
In the Europe ROM, `$EE0000` is the 16x16 sprite block table (see [sprites.md](sprites.md)),
not the BG tile table.

## Zero-word sprite codec

Used for sprite graphics blocks: 128 bytes for a 16x16 block, 32 bytes for an 8x8 block.

```
for each group of 8 output words:
    status = next byte
    for bit in 0..7 (LSB first):
        if status bit is 1: output word = 0x0000 (nothing read)
        else:               output word = next 2 bytes (literal)
```

A 16x16 block has 8 groups, an 8x8 block 2 groups. The block pointer tables carry a
"compressed" flag (bit 7 of the third pointer byte); uncompressed blocks are stored raw.
Reference implementation: `soe/lz.py::decompress_sprite` (returns the bytes consumed, so
consecutive blocks can be walked). The game's decode loop is at `$80975D` inside the
16x16 graphics loader `$8096FD`; the 8x8 loader is `$80A4B4`. Pointer tables and bank
rules are in [sprites.md](sprites.md).

Verification: boy animation frames composed from blocks decoded with this codec match
emulator OAM, VRAM and CGRAM reconstructions with score 1.000 (see [sprites.md](sprites.md)).

## Address quick reference

| What | SNES | File |
|---|---|---|
| dispatcher entry | `$8C9C22` | `0x0C9C22` |
| opcode jump table | `$8C9C36` | `0x0C9C36` |
| opcode 0, block copy | `$8C9C46` | `0x0C9C46` |
| opcode 3, LZSS | `$8C9C5E` | `0x0C9C5E` |
| LZSS symbol loop | `$8C9C92` | `0x0C9C92` |
| LZSS match copy | `$8C9D5E` | `0x0C9D5E` |
| LZSS wrap-read variant | `$8C9D9F` | `0x0C9D9F` |
| LZSS bit-mask table (16 words) | `$8C9DDB` | `0x0C9DDB` |
| opcode 7 entry | `$8C9EFA` | `0x0C9EFA` |
| opcode 7 prefix jump table (32 words) | `$8CA08C` | `0x0CA08C` |
| opcode 7 bit-reader cascade | `$8CA0F0` | `0x0CA0F0` |
| opcode 7 index extractors | `$8CA134` | `0x0CA134` |
| opcode 7 context update | `$8C9F88` | `0x0C9F88` |
| sprite 16x16 loader (zero-word decode at `$80975D`) | `$8096FD` | `0x0096FD` |
| sprite 8x8 loader | `$80A4B4` | `0x00A4B4` |
| LZSS ring buffer | `$7FA000-$7FAFFF` | WRAM |
