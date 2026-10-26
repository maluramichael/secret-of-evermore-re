# Maps

How the game turns a map id into BG layers, collision and palettes. Codec details are in
[compression.md](compression.md); RAM addresses are collected in
[memory-map.md](memory-map.md); event scripts and trigger zones in [scripts.md](scripts.md).

Address convention: SNES addresses are written `$BBAAAA`. The ROM is HiROM without a copier
header; for the ROM banks used here (`$C0-$EF`, the `$80-$BF` upper-half mirror and
`$40-$7D`) the file offset is `snes & 0x3FFFFF`. The map loader executes in bank `$90`;
some listings show the same bytes as bank `$D0` (for example `$9090F9` = `$D090F9`).
Map ids are given in decimal with hex in parentheses where useful: map 16 (`$10`),
map 24 (`$18`), map 56 (`$38`), map 97 (`$61`).

## Pipeline overview

```
$7E0ADB  current map id
   |
   v
$908F68  map loader entry (LDA $0ADB)
   |  map pointer table $E0FDE4, 4 bytes per map
   v
map data (banks $DD-$EE, file 0x1D8000-0x2EFFFF)
   |  header: width, height, PPU registers, ...
   |  trigger zones (event, B)
   |  compressed blob:
   |    opcode 3 LZSS -> $7FC300 (deltas) -> prefix sum $908E85 -> metatile index per cell
   |    opcode 7      -> $7F0000 record pointer per cell
   |    opcode 3 LZSS -> $7F0000+BASE record data
   |  palette-animation setlist -> queue $90D532 -> drain $90D582 -> $7E6187
   v
per cell: $7F0000[2*cell] -> 8-byte record:
   word0 = BG1 large tile, word1 = BG2 large tile, word2 = attributes (collision), word3 = 0
   |
   v
PPU: Mode 1, BG1 and BG2 with 16x16 tiles, char base VRAM $4000 (bytes)
```

## Map id and loader entry

- WRAM `$7E0ADB` holds the current map id (valid ids 0 to 126). The loader reads it
  with `LDA $0ADB`; writing the target id to `$0ADB` (and 0 to `$0ADC`) right before that
  instruction makes the game build any map through its own code path. This is the basis
  of the map extraction technique in [emulator-techniques.md](emulator-techniques.md).
- Loader entry: `$908F68`.

```asm
908F68  LDA $0ADB          ; current map id
        ASL A
        ASL A              ; * 4
        TAX
        LDA $A0FDE5,X
        STA $8B
        LDA $A0FDE6,X
        STA $8C            ; $8B/$8C/$8D = 24-bit map data pointer
```

## Map pointer table

- File `0x20FDE4` (`$E0FDE4`, read through the mirror as `$A0FDE4`).
- 127 records of 4 bytes (508 bytes, ends at `0x20FFE0`).
- Record: `00 <lo> <mid> <bank>`. Byte 0 is always `0x00`; bytes 1 to 3 are a 24-bit SNES
  pointer to the map data.
- All 127 pointers resolve into file `0x1D8000-0x2EFFFF`.
- For the US ROM, Data Crystal and SoEScriptDumper use file `0x1FFDE7` (`$9FFDE7`), about
  `0x10000` lower. The US layout is not checked here.

Verified dereferences: map 0 to `$ACF501`, map 16 to `$AEC5C6`, map 97 to `$A9B3AA`. A
read trace of the map 97 load shows the CPU reading the map data from `$A9B3AA` on,
through the `$80-$BF` mirror (bank `$A9`, not `$E9`). Read traces must cover
`$808000-$EFFFFF` to see these reads.

## Map data layout

### Header

Parsed by the loader at `$908F85-$909049` via `LDA [$8B],Y`:

| Offset | Size | Destination | Meaning | Status |
|---|---|---|---|---|
| `+0x00` | 1 | `$0F88` | unknown | read verified, meaning open |
| `+0x01` | 1 | `$0F8A` | unknown | read verified, meaning open |
| `+0x02` | 1 | `$08EE` | width in 16x16 cells | verified (maps 16, 24, 97) |
| `+0x03` | 1 | `$08F0` | height in 16x16 cells | verified (maps 16, 24, 97) |
| `+0x04` | 1 | `$212C` (TM) and shadow `$0F82` | main-screen layers | verified |
| `+0x05` | 1 | `$212D` (TS) and shadow `$0F83` | sub-screen layers | verified |
| `+0x06` | 1 | `$2131` (CGADSUB) and shadow `$0F84` | color math | verified |
| `+0x07` | 1 | `$2130` (CGWSEL) and shadow `$0F85` | color math | verified |
| `+0x08` | 1 | `$7E241F` | unknown | read verified, meaning open |
| `+0x09` | 2 | `$0F86` | unknown | provisional |
| `+0x0D` | 2 | | length of the event trigger section in bytes | verified (127/127 maps have a multiple of 6) |
| `+0x0F` | n | | event trigger entries, 6 bytes each | verified |

Bytes `+0x08` to `+0x0B` are zero on 118 of 127 maps. The loader also derives
sub-table offsets into `$1064`/`$1069` and far pointers into the map data at
`$1066`/`$106B`; which header bytes feed them is not pinned down.

Width and height (map 16: 24 x 15, map 24: 24 x 32, map 97: 48 x 47) match the emulator.
`soe/mapbake.py::map_dims_from_rom` reads them.

Common pitfall: earlier tooling read `+0x02..+0x04` as a 3-byte "graphics pointer" in bank
`$16`/`$17`. Bytes `+0x02/+0x03` are the dimensions and `+0x04` is the TM register value,
which is `0x16` or `0x17` (BG1+BG2(+BG3)+OBJ) on almost every map. There is no tileset
pointer in the header.

### Trigger sections

After the event trigger entries:

```
[btrig_len:u16]  length of the second trigger section in bytes
[btrig entries]  6 bytes each
```

A trigger entry is a rectangle plus a script reference:
`[x1][y1][x2][y2][scriptid:u16]`, coordinates in cells. The scriptid resolution is in
[scripts.md](scripts.md). `soe/maps.py::read_map` parses both sections.

### Compressed blob

Directly after the trigger sections (`trigger_section_end` in `soe/maps.py`):

```
[n:1] [n x id:u16]       list of 16-bit ids, meaning open (see below)
00                       pad
[w0:u16]                 meaning open
03 [size:u16] ...        opcode-3 block: arrangement deltas      -> $7FC300
(padding)
07 [BASE:u16] ...        opcode-7 block: record pointer table    -> $7F0000
(padding)
03 [size:u16] ...        opcode-3 block: record data             -> $7F0000 + BASE
```

The id list holds consecutive ids per map (map 16: 7 ids `$004A-$0050`, map 24: 14 ids,
map 97: 7 ids `$011D-$0123`). Its role is not established. Possibly it names the tile
graphics sets of the map (the map-16 tiles fall into about 7 clusters in ROM), but this is
unverified.

Exec trace of the map-16 load (three dispatcher calls, consecutive frames):

| Opcode | Source | Destination | Size | Content |
|---|---|---|---|---|
| 3 | `$AEC5F5` | `$7F:C300` | `$0066` | arrangement deltas |
| 7 | `$AEC66B` | `$7F:0000` | `$02D0` | record pointer table (24 * 15 * 2) |
| 3 | `$AEC6F0` | `$7F:02D0` | `$0300` | record data |

`soe/mapbake.py::_map_blocks_from_rom` locates the first two blocks from ROM data alone
(the opcode-7 block is found by its header `07 <BASE:u16le>`).

## Arrangement: `$7FC300`

Call site `$9090F9`:

```asm
LDA [$8B],Y         ; 16-bit length from the map data
LSR A               ; / 2 = number of words
PHA
LDA #$7FC3
STA $3B             ; destination bank $7F
LDA #$C300
STA $3A             ; destination $7FC300
JSL $8C9C22         ; opcode-3 LZSS
PLA
PHA
JSR $8E85           ; $908E85, in-place prefix sum
```

`$908E85` converts signed 16-bit deltas into absolute values:

```asm
908E85  TAX           ; X = word count
        TDC           ; A = 0
        TAY           ; Y = 0
        BRA +
loop:   CLC
        ADC [$3A],Y   ; running sum
        STA [$3A],Y
        INY
        INY
+:      DEX
        BPL loop
        RTS
```

Result: one 16-bit metatile index per cell for a leading contiguous run of cells
(map 16: cells 0-50, map 24: 0-136, map 97: 0-213). Byte-exact against WRAM dumps;
`soe/mapbake.py::arrangement_first_block_from_rom` reproduces it. Example (map 97, cells
0-7): `16cd 16ce 16cf 11d0 11d1 11d2 16d0 16d1`, from deltas
`16cd +1 +1 -4ff +1 +1 +4fe +1`.

The values are global metatile indices, not PPU tilemap words; rendering them as tilemap
words produces noise. The full-map render does not use `$7FC300` at all (it uses the
records below). What the game uses the arrangement for is open; a plausible but
unverified reading is that it selects which tile graphics blocks to stage in VRAM.

## Record pointer table and records: `$7F0000`

```
$7F0000 + 2*cell        u16 byte offset (from $7F0000) of the cell's record
$7F0000 + BASE + 8*k    8-byte records, BASE = width*height*2
```

Cells with identical content share a record, so the number of distinct pointers equals
the number of distinct records. The pointer table is the output of opcode 7 (full 2D
placement of all `width * height` cells, see [compression.md](compression.md)).

Record layout (verified: rendering from this layout gives clean images for all 127 maps
from WRAM/VRAM dumps of their loads, and spot checks of indoor and outdoor maps match the
live PPU frame):

| Word | Meaning |
|---|---|
| 0 | BG1 large-tile word (foreground: walls, foliage, objects) |
| 1 | BG2 large-tile word (ground: floor, dirt, water) |
| 2 | attribute word; low nibble = collision (see below) |
| 3 | always 0 |

Each large-tile word uses the SNES tilemap layout `vhopppcc cccccccc`: bit 15 V-flip,
bit 14 H-flip, bit 13 priority, bits 12-10 palette row, bits 9-0 tile number.

Common pitfall: early notes read the record as four 8x8 quadrant words (TL, TR, BL, BR).
That reading renders indoor maps passably and outdoor maps as a checkerboard. Words 1 and
2 are a BG2 tile and an attribute field.

The third blob (opcode 3 to `$7F0000 + BASE`) supplies the record data, but its output is
not yet the final interleaved record array: for map 16 its first words are
`e800, 648e, 648e, e800` while the final first record is `e800, 44a0, 101f, 0000`. The
step that assembles the final records is not reversed; the sub-routines called after
`$909105` (`$90A0B7`, `$90A146`, `$90D043`, `$8CAED7`, `$8CCC4F`, `$9094D2`, `$90CC1F`,
plus hardware division by 3 via `$4204/$4206`) are located but not analysed.

## BG layers and rendering

PPU state during gameplay (from a Mesen2 PPU dump on map 97, matching map 16):

- BG mode 1.
- BG1 and BG2 use 16x16 tiles ("large tiles").
- BG char base: VRAM byte `$4000` (word `$2000`), 4bpp.
- BG1 tilemap at VRAM byte `$0000`, BG2 tilemap at VRAM byte `$0800`.

A large-tile word with tile number `T` draws the four 8x8 tiles `T`, `T+1`, `T+16`, `T+17`
(top-left, top-right, bottom-left, bottom-right) with the word's palette; H/V flip swaps
the quadrants and flips each tile.

Full-map render rule (`soe/snescall.py::render_map`): for each cell, draw word 1 (BG2),
then word 0 (BG1) on top, skipping color index 0, with the tiles from VRAM and the palette
from CGRAM of a map load. Limit: cells whose tiles were not yet staged in VRAM at dump time
render dark (see "Tile graphics" below).

The VRAM BG tilemaps hold only the visible scroll window (32 x 32 entries); the full map
exists only as the `$7F0000` records.

### Walk-behind (priority bit)

Measured on rendered maps: BG2 words practically never set the priority bit (bit 13)
(map 1: 0 of 1572 drawn words, map 54: 3 of 624, map 16: 18 of 342). On BG1 the bit
varies and marks canopy and other overhead detail (map 1: 528 set, 138 clear). Player
sprites use OBJ priority 3, and TM is `0x17` (BG1+BG2+BG3+OBJ).

Under plain Mode 1 ordering OBJ priority 3 is above all BG1 tiles, so the in-game
walk-behind must lower the player's effective priority somewhere. That mechanism is not
traced. `soe/maplayers.py` splits maps into "below" and "above" images by the BG1 priority
bit (provisional, checked visually with `tools/verify_maplayers.py`).

## Collision

The low nibble of record word 2 holds the blocking bits of a cell:

| `word2 & 0x0F` | Meaning |
|---|---|
| `0x0` | fully walkable |
| `0xF` | fully solid |
| `0x1-0xE` | partially blocked edge cells; exact sub-cell or direction semantics open |

Evidence: map 56 (83 x 91 = 7553 cells) has nibble 0 on 1393 cells, `0xF` on 5709 cells
and other values on 451 cells. As an overlay on the rendered map, nibble 0 covers the
paths and clearings and `0xF` the dense foliage and the void border. Verified on map 56
only. The upper 12 bits of word 2 are not decoded. `soe/mapdata.py::collision_grid`
extracts the grid (treating any non-zero nibble as solid).

## Tile graphics (tileset)

- The 4bpp BG tiles are not stored in the map data. They are 16x16 blocks (128 bytes)
  compressed with the 16-mode tile codec ([compression.md](compression.md)), stored
  individually and scattered over many ROM banks.
- During a map load the char base is filled by an inline DMA at `$9091C1` (VMADD = word
  `$2000`) from `$7F:[$0FAA]`, i.e. from the record area start `$7F0000 + BASE`.
- VRAM slots follow the large-tile quadrant order (`T`, `T+1`, `T+16`, `T+17`).
- Open: the Europe table from a tile block index to its ROM offset is not located, and the
  game routine that decodes the blocks is not identified. `soe/mapbake.py::tileset_from_rom`
  therefore finds block offsets by known plaintext against a VRAM dump (239 of 256 large
  tiles of map 16 found). Some maps stream tiles while scrolling, so a single VRAM dump does
  not always hold the full tileset.

Common pitfall: the tileset is not an opcode-3 or opcode-7 blob in banks `$C6`/`$C7`. The
bank-`$C0` loader at `$C0B406` does decompress opcode-3 blobs from bank `$C7` to
`$7F0000` and DMAs them to VRAM via `$808650`, but that path is a separate graphics
loader, not the map tileset.

## BG palette

- CGRAM rows 1 to 7 (colors 16-127) of a map come from a 224-byte block in ROM file bank
  `0x1D` (7 rows x 16 colors x 2 bytes). Verified byte-exact against CGRAM dumps:
  map 16 at file `0x1DCC63`, map 97 at file `0x1DE6C3`.
- Row 0 (colors 0-15) is a dynamic HUD/status palette and is not part of the block.
- The blocks are not aligned to 32 bytes.
- Open: the selector from map id to palette block. No direct 3-byte pointer to these
  offsets exists in the ROM, and no header field matches them linearly.
- The character and sprite palettes in bank `$10` (see [sprites.md](sprites.md)) are a
  different table. Using them for BG tiles gives wrong colors.

WRAM `$7E6187` (512 bytes, 256 colors) is the palette buffer that the game transfers to
CGRAM.

## Palette animation queue

Water, torches and foliage shimmer are palette cycling, not tile animation (on map 1,
CGRAM entries 17, 18 and 19 rotate).

The map data contains a palette-animation list read by the loop at `$9090A2-$9090D2`:

```asm
LDA [$8B],Y
INY
AND #$00FF
BEQ end              ; 0 = no entries
TAX                  ; X = entry count
loop:
  ...                ; 3 bytes per entry -> $02/$04, $06, $08
  JSL $90D532        ; register one entry
  DEX
  BNE loop
```

This reading (a count byte, then that many 3-byte entries) comes from a short listing
and is provisional. Per entry: `byte0` gives the slot `(byte0 & 0x70) >> 4` (0-7) in `$02` and `byte0 & 0x0F`
in `$04`; `byte1` goes to `$06`; `byte2` to `$08`. Where in the map data this list sits is
not pinned down.

Registrar `$90D532` writes the entry into one of 8 slots of parallel WRAM arrays:

| Array | Content |
|---|---|
| `$1374,X` | id or target |
| `$1394,X`, `$13B4,X` | from `$06` |
| `$13D4,X` | from `$08` (a sign bit selects a branch) |
| `$13F4,X` | counter, decremented per tick |

Drain `$90D582` runs once per frame, reads the slots and updates the palette buffer
`$7E6187` using the CGRAM DMA primitive `$8085FA`. The exact color-cycling rule per slot
type is not decoded.

Common pitfall: this list was first read as a tileset "setlist" that selects graphics
chunks. It drives palettes only.

## Camera

Camera top-left in map pixels: `$7E0059` (x), `$7E005B` (y). The controlled character's
position is `$7E4EA3` (x) and `$7E4EA5` (y). Measured on map 56 only: the camera is clamped
to x 0-768, y 16-976, so the visible area is 1024 x 1184 pixels starting at y = 16; the top
16-pixel row and the area beyond x 1024 / y 1200 of the 1328 x 1456 map are never shown.
Clamping may differ per map. Details in [memory-map.md](memory-map.md).

## DMA primitives used by the loader

| Routine | Function |
|---|---|
| `$808650` | VRAM DMA: VMAIN `$2115`, VMADD `$2116` from DP `$2E`, source DP `$26/$28`, size in X, channel 1, fires via `$420B = $02` |
| `$8086C0` | sibling VRAM DMA (BBAD `$18`, DMAP `$01`) with an enqueue path |
| `$8085FA` | CGRAM DMA: CGADD `$2121`, BBAD `$22`; can transfer directly or enqueue |
| `$9091C1` | inline tileset DMA inside the map loader |

Mesen2 memory callbacks do not fire on these I/O registers; observe DMA with exec
callbacks on the routines and read their DP arguments (see
[emulator-techniques.md](emulator-techniques.md)).

## Open points

- Record assembly: how the third blob becomes the final interleaved 8-byte records.
- Opcode 7 divergence on map 24.
- Role of `$7FC300` and of the id list at the start of the blob.
- Tile graphics: Europe index-to-offset table and the in-game decode routine.
- BG palette selector (map id to bank-`0x1D` block).
- Header bytes `+0x00`, `+0x01`, `+0x08` to `+0x0C`.
- Collision values `0x1-0xE` and the upper bits of record word 2.
- The dynamic OBJ priority change behind the walk-behind effect.
- Camera clamp on maps other than 56.

## Address quick reference

| What | SNES | File |
|---|---|---|
| map loader entry | `$908F68` | `0x108F68` |
| header parse | `$908F85` | `0x108F85` |
| width store / height store | `$908F97` / `$908FBA` | `0x108F97` / `0x108FBA` |
| palette-animation list loop | `$9090A2` | `0x1090A2` |
| arrangement decompress call | `$9090F9` | `0x1090F9` |
| loader tail (remaining blocks) | `$909105` | `0x109105` |
| inline tileset DMA | `$9091C1` | `0x1091C1` |
| prefix sum | `$908E85` | `0x108E85` |
| palette queue registrar | `$90D532` | `0x10D532` |
| palette queue drain | `$90D582` | `0x10D582` |
| map pointer table | `$E0FDE4` | `0x20FDE4` |
| BG palette, map 16 | | `0x1DCC63` |
| BG palette, map 97 | | `0x1DE6C3` |
| VRAM DMA / CGRAM DMA | `$808650` / `$8085FA` | `0x008650` / `0x0085FA` |
