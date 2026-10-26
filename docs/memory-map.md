# Memory map

Known WRAM, direct-page, CGRAM, VRAM and OAM locations of Secret of Evermore (Europe).
Each entry links to the document that explains it. "Verified" means confirmed by
disassembly plus emulator dumps or traces; "provisional" means inferred from a short
listing, a single observation or a name, and needs confirmation.

Address convention: WRAM is written as `$7Exxxx`/`$7Fxxxx`. Code often accesses
`$7E0000-$7E1FFF` through the low-RAM mirror (`$0ADB` = `$7E0ADB`) or with DBR = `$7E`
(`$5127` = `$7E5127`). ROM addresses in this document follow the HiROM rule
`file = snes & 0x3FFFFF` (no copier header).

## WRAM bank `$7E`

| Address | Size | Meaning | Status | Doc |
|---|---|---|---|---|
| `$7E0059` | 2 | camera X: top-left of the view in map pixels | verified (map 56) | [maps.md](maps.md) |
| `$7E005B` | 2 | camera Y | verified (map 56) | [maps.md](maps.md) |
| `$7E00BF`, `$7E00C1` | 2 + 2 | mirrors of camera X / Y (same values observed) | verified (map 56) | |
| `$7E0104` | 2 | joypad, newly pressed buttons | verified | [sprites.md](sprites.md) |
| `$7E0133`, `$7E0135`, `$7E0137`, `$7E0139` | | state updated by the rotate-and-add routine `$80859B`, likely RNG state | provisional | [labels.md](labels.md) |
| `$7E08EE` | 2 | map width in 16x16 cells (header `+0x02`) | verified | [maps.md](maps.md) |
| `$7E08F0` | 2 | map height in cells (header `+0x03`) | verified | [maps.md](maps.md) |
| `$7E0ADB` | 1 | current map id (0-126); `$7E0ADC` is set to 0 when overriding the id | verified | [maps.md](maps.md) |
| `$7E0E4D` | | current song id; the music upload routine at `$8C8583` compares and stores it, table index = id * 3 | verified (disassembly, emulator) | [audio.md](audio.md) |
| `$7E0EC8` | 2 | joypad, held buttons (standard auto-joypad layout; right `$0100`, left `$0200`, down `$0400`, up `$0800`) | verified | [sprites.md](sprites.md) |
| `$7E0F48` | 2 | opcode-7 parameter: `width * 2` | verified | [compression.md](compression.md) |
| `$7E0F82-$7E0F85` | 4 | shadows of TM, TS, CGADSUB, CGWSEL (header `+0x04..+0x07`) | verified | [maps.md](maps.md) |
| `$7E0F86` | 2 | from map header `+0x09` | provisional | [maps.md](maps.md) |
| `$7E0F88` | 1 | from map header `+0x00`, meaning open | verified (read) | [maps.md](maps.md) |
| `$7E0F8A` | 1 | from map header `+0x01`, meaning open | verified (read) | [maps.md](maps.md) |
| `$7E0FAA` | 2 | opcode-7 BASE = `width * height * 2`; also source offset of the inline tileset DMA | verified | [compression.md](compression.md) |
| `$7E0FAC` | 2 | opcode-7 init fill count * 8 | verified | [compression.md](compression.md) |
| `$7E0FC6` | 2 | opcode-7 count of persistent records (0 on observed maps) | verified | [compression.md](compression.md) |
| `$7E0FCC`, `$7E0FCE`, `$7E0FD0` | 2 each | staging values written by animation opcode `$5B` (table value, entity X, entity Y) | verified (disassembly) | [sprites.md](sprites.md) |
| `$7E1064`, `$7E1069` | | sub-table offsets derived from the map data | provisional | [maps.md](maps.md) |
| `$7E1066`, `$7E106B` | | far pointers into the map data | provisional | [maps.md](maps.md) |
| `$7E1278` | 2 | display-list node allocator (reset to `$512F`, `+15` per node) | verified | [sprites.md](sprites.md) |
| `$7E1374,X` | | palette-animation queue: id/target, 8 slots | verified | [maps.md](maps.md) |
| `$7E1394,X`, `$7E13B4,X` | | palette-animation queue: entry byte 1 values | verified | [maps.md](maps.md) |
| `$7E13D4,X` | | palette-animation queue: entry byte 2 value | verified | [maps.md](maps.md) |
| `$7E13F4,X` | | palette-animation queue: per-slot counter, decremented per tick | verified | [maps.md](maps.md) |
| `$7E1462`, `$7E1464` | | values used before `JMP $D08124` in action selection | provisional | [sprites.md](sprites.md) |
| `$7E2258` | | flag area addressed by script opcodes `..._2258` | provisional (from opcode names) | [scripts.md](scripts.md) |
| `$7E2261-$7E2263` | 3 | charm bit flags; `$7E2262` bit 1 = Jaguar Ring | verified (bisection) | [sprites.md](sprites.md) |
| `$7E2401`, `$7E2405` | 2 + 2 | mirrors of camera X / Y | verified (map 56) | |
| `$7E241F` | 1 | from map header `+0x08`, meaning open | verified (read) | [maps.md](maps.md) |
| `$7E2834` | | variable area addressed by script opcodes `..._2834` | provisional (from opcode names) | [scripts.md](scripts.md) |
| `$7E4E89` | | boy entity block (field table in sprites.md) | verified | [sprites.md](sprites.md) |
| `$7E4E8F-$7E4E91` | 3 | boy layer 2 metasprite pointer (entity `+0x06`) | verified | [sprites.md](sprites.md) |
| `$7E4E92-$7E4E94` | 3 | boy layer 1 metasprite pointer (entity `+0x09`) | verified | [sprites.md](sprites.md) |
| `$7E4E95` | | boy OAM attribute base (entity `+0x0C`) | verified | [sprites.md](sprites.md) |
| `$7E4EA3` | 2 | boy X position in map pixels (entity `+0x1A`); writable, camera follows | verified | [sprites.md](sprites.md) |
| `$7E4EA5` | 2 | boy Y position in map pixels (entity `+0x1C`); camera Y follows with offset 104 | verified | [sprites.md](sprites.md) |
| `$7E4EAB` | 1 | boy facing = direction * 4 (entity `+0x22`) | verified | [sprites.md](sprites.md) |
| `$7E4EB7` | | boy direction (entity `+0x2E`), written by player control | verified | [sprites.md](sprites.md) |
| `$7E4EE9` | | boy entity `+0x60`, candidate for the action-table index | provisional | [sprites.md](sprites.md) |
| `$7E4EF7` | 2 | metasprite offset of the static party/HUD boy (entity `+0x6E`) | verified | [sprites.md](sprites.md) |
| `$7E4EF9` | 1 | metasprite bank of the static party/HUD boy | verified | [sprites.md](sprites.md) |
| `$7E4F17` | 2 | X value read by the party-boy render call `$8FC5DD` (entity `+0x8E`) | provisional | [sprites.md](sprites.md) |
| `$7E4F37` | | dog entity block | verified (display-list insert trace) | [sprites.md](sprites.md) |
| `$7E4F65` | | dog direction (entity `+0x2E`) | verified | [sprites.md](sprites.md) |
| `$7E50A7-$7E5127` | | 17 display-list bucket anchors, 8 bytes apart; `$7E5127` = list head, a fixed address (no code stores a head pointer) | verified | [sprites.md](sprites.md) |
| `$7E50AD,X` | | display-list bucket shortcut cache | verified | [sprites.md](sprites.md) |
| `$7E512F` | | start of the display-list node pool (15-byte nodes) | verified | [sprites.md](sprites.md) |
| `$7E6187-$7E6386` | 512 | palette buffer (256 colors) transferred to CGRAM; target of the palette-animation drain | verified | [maps.md](maps.md) |
| `$7E7D51,X` | | 8x8 sprite block to VRAM slot cache | verified | [sprites.md](sprites.md) |
| `$7E95AE,Y` | | 8x8 slot cache lookup table | verified | [sprites.md](sprites.md) |
| `$7E96AE`, `$7E9730`, `$7E972F` | | 8x8 slot LRU lists | verified | [sprites.md](sprites.md) |
| `$7E97B2,X` | | 16x16 sprite block to VRAM slot cache | verified | [sprites.md](sprites.md) |
| `$7EAABC,Y` | | 16x16 slot cache lookup table | verified | [sprites.md](sprites.md) |
| `$7EAB7C`, `$7EABDE`, `$7EABDD` | | 16x16 slot LRU lists | verified | [sprites.md](sprites.md) |
| `$7EAC42-$7EAE61` | 544 | OAM shadow (512-byte table + 32-byte high table), DMA'd to OAM every NMI | verified | [sprites.md](sprites.md) |

The sprite slot tables (`$7D51` to `$ABDD`) are accessed as 16-bit absolute addresses by
`sprite_compose`; bank `$7E` follows from DBR = `$7E` set by the display-list walker.

## WRAM bank `$7F`

| Address | Size | Meaning | Status | Doc |
|---|---|---|---|---|
| `$7F0000` | `width * height * 2` | per-cell record pointer table (16-bit offsets from `$7F0000`), output of opcode 7 | verified | [maps.md](maps.md) |
| `$7F0000 + BASE` | 8 per record | map cell records: BG1 word, BG2 word, attribute/collision word, 0 | verified | [maps.md](maps.md) |
| `$7F0000` | | also used as a graphics staging buffer by the bank-`$C0` blob loader before VRAM DMA | verified | [compression.md](compression.md) |
| `$7FA000-$7FAFFF` | 4096 | LZSS ring buffer (opcode 3) | verified | [compression.md](compression.md) |
| `$7FC300` | 2 per cell | map arrangement: global metatile index per cell (prefix-summed deltas) | verified | [maps.md](maps.md) |

## Direct page (D = 0)

Direct-page variables are scratch registers reused by different routines. Context
matters.

| DP | Context | Meaning | Status | Doc |
|---|---|---|---|---|
| `$02`, `$04` | LZSS handler | destination pointer | verified | [compression.md](compression.md) |
| `$02`, `$04`, `$06` | sprite_compose | screen X base, screen Y base, OAM attribute base | verified | [sprites.md](sprites.md) |
| `$02`, `$04`, `$06`, `$08` | palette list loop | entry slot, low nibble, byte 1, byte 2 | verified | [maps.md](maps.md) |
| `$07` | sprite_compose | attribute mask (`$CE` at `$809032`; bit 0 cleared at `$80903F`) | verified | [sprites.md](sprites.md) |
| `$08`, `$0A`, `$0C` | LZSS handler | ring write pointer, bit index, ring end | verified | [compression.md](compression.md) |
| `$08` | display-list builder | Y value from which the sort key (minus 10) is derived | verified | [sprites.md](sprites.md) |
| `$0C`, `$0E`, `$10`, `$12`, `$14` | opcode 7 | new-word generator, new-word count, width mask, left context, back-reference width | verified | [compression.md](compression.md) |
| `$16`, `$18` | sprite_compose | chunk screen X, screen Y | verified | [sprites.md](sprites.md) |
| `$26`, `$27`, `$28` | sprite_compose | 24-bit metasprite pointer | verified | [sprites.md](sprites.md) |
| `$26` | opcode 7 | above-cell context | verified | [compression.md](compression.md) |
| `$26`, `$28`, `$2E` | VRAM DMA `$808650` | source address, VRAM address (VMADD) | verified | [maps.md](maps.md) |
| `$2A`, `$2C` | LZSS handler | source pointer (source + 3) | verified | [compression.md](compression.md) |
| `$34` | dispatcher | 16-bit block parameter (header bytes 1-2) | verified | [compression.md](compression.md) |
| `$36`, `$38` | dispatcher | source offset, source bank | verified | [compression.md](compression.md) |
| `$3A`, `$3C` | dispatcher | destination offset, destination bank | verified | [compression.md](compression.md) |
| `$3E`, `$40`, `$46`, `$48` | routine `$91CA90` | dx = `$3E - $46`, dy = `$40 - $48` | provisional | [labels.md](labels.md) |
| `$44` | routine `$8FA8C5` | state flags (tests `$2040`, `$40`) | provisional | [labels.md](labels.md) |
| `$4C` | display-list builder | entity base address | verified | [sprites.md](sprites.md) |
| `$5D`, `$5F` | animation VM | script cursor, script bank | verified | [sprites.md](sprites.md) |
| `$82` | interpreter `$8CEE44` | bytecode pointer | provisional | [scripts.md](scripts.md) |
| `$8B`, `$8C`, `$8D` | map loader | 24-bit map data pointer | verified | [maps.md](maps.md) |
| `$D3` | sprite_compose | running byte offset into the OAM shadow | verified | [sprites.md](sprites.md) |
| `$D5`, `$D7` | sprite_compose | OAM high-table bits being collected | verified | [sprites.md](sprites.md) |
| `$DB` | sprite_compose | allocated VRAM tile slot | verified | [sprites.md](sprites.md) |
| `$DD` | sprite graphics loader | block number | verified | [sprites.md](sprites.md) |
| `$DF` | sprite_compose | chunk flags | verified | [sprites.md](sprites.md) |

Note: `$0059`/`$005B` (camera) also lie in the direct-page range.

## CGRAM

| Range | Meaning | Status | Doc |
|---|---|---|---|
| colors 0-15 (row 0) | BG HUD/status palette, set at run time | verified | [maps.md](maps.md) |
| colors 16-127 (rows 1-7) | BG map palette, copied from a 224-byte block in ROM file bank `0x1D` | verified (maps 16, 97) | [maps.md](maps.md) |
| colors 17-19 | cycled on map 1 (palette animation) | verified | [maps.md](maps.md) |
| colors 128-255 (rows 8-15) | OBJ palettes 0-7 | verified | [sprites.md](sprites.md) |
| OBJ palette 6 (colors 224-239) | boy (ROM `0x10AD70`) | verified | [sprites.md](sprites.md) |
| OBJ palette 7 (colors 240-255) | dog | verified | [sprites.md](sprites.md) |

## VRAM

Byte addresses, word addresses in parentheses.

| Address | Meaning | Status | Doc |
|---|---|---|---|
| `$0000` (`$0000`) | BG1 tilemap, 32 x 32 large-tile entries | verified | [maps.md](maps.md) |
| `$0800` (`$0400`) | BG2 tilemap | verified | [maps.md](maps.md) |
| `$4000` (`$2000`) | BG1/BG2 character base, 4bpp | verified | [maps.md](maps.md) |
| `$C000` (`$6000`) | OBJ character base | verified (gameplay maps) | [sprites.md](sprites.md) |
| `$E000` (`$7000`) | second OBJ name table (base + `$2000` bytes) | verified (gameplay maps) | [sprites.md](sprites.md) |

## OAM

544 bytes, written only by DMA from the shadow `$7EAC42` in the NMI handler (`$8082E9`).
Format and OBJ conventions: [sprites.md](sprites.md).

## Hardware registers touched by documented routines

| Register | Use | Routine |
|---|---|---|
| `$2104` | OAMDATA, OAM DMA target | `$8082E9` |
| `$2115`, `$2116`, `$2118` | VMAIN, VMADD, VMDATA | `$808650`, `$9091C1` |
| `$2121`, `$2122` | CGADD, CGDATA | `$8085FA` |
| `$212C`, `$212D`, `$2130`, `$2131` | TM, TS, CGWSEL, CGADSUB from the map header | `$908F85` |
| `$4204`, `$4206`, `$4214` | hardware divide | `$80AEAB`, map loader tail `$909105` |
| `$420B` | MDMAEN | `$808650` |
| `$4212`, `$4218`, `$421A` | auto-joypad status and data | `$808471` |

## External references (not verified here)

The Data Crystal RAM map for Secret of Evermore lists many more addresses. The following
are relevant to the topics above but have not been checked in this project:

| Address | Meaning according to Data Crystal |
|---|---|
| `$7E2258-$7E225C` | known alchemy formulas, bit flags |
| `$7E22DA-$7E22DB` | weapons obtained, bit flags |
| `$7E22FF+` | alchemy ingredient counts |
| `$7E28FC-$7E2F27` | active script list, 20 slots of 79 bytes |
| `$7E3364`, `$7E3564` | alchemy attack slots (two formats) |
| `$7E3DE5-$7E4E88` | monster/NPC entity table, 142-byte entries (Data Crystal says 16 entries, which does not fill the range); event trigger flags at entry `+0x68`: `$0040` talk proximity, `$0100` damaged, `$0200` killed |
| `$7E6387-$7E64E6` | projectile list, 44 bytes x 8 slots |

Data Crystal documents the US ROM. The Europe addresses above coincide where this project
checked them (map id, map dimensions, palette buffer, `$7F0000`, `$7FC300`, boy and dog
entity bases), but the rows in this table
are not individually confirmed.

### Names from SoEScriptDumper

SoEScriptDumper (`data.h`) names some WRAM variables that event scripts read or write.
Not verified here; addresses are low-RAM (`$7Exxxx`).

| Address | Name in SoEScriptDumper |
|---|---|
| `$0E80+` | arguments passed by script call opcodes |
| `$238D` | change music |
| `$2391` | prize |
| `$2393` | amount |
| `$23E9-$23EF` | map scroll limit box |
| `$2443` | dog form |
| `$2445` | preselected alchemy |
| `$2449` | save spot |
