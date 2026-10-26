# Sprites

How actors (boy, dog, NPCs, enemies) get from an animation script to OAM. The boy's chain
is reversed end to end and verified pixel for pixel; other actors use the same engine but
their scripts are not mapped. Codecs are in [compression.md](compression.md), RAM
addresses in [memory-map.md](memory-map.md).

Address convention: SNES addresses are written `$BBAAAA`. The ROM is HiROM without a copier
header; for the ROM banks used here (`$C0-$EF`, the `$80-$BF` upper-half mirror and
`$40-$7D`) the file offset is `snes & 0x3FFFFF`. Example: sprite graphics in bank `$61`
are at file `0x21xxxx`.

## Render chain

```
action table $C4452E (action group x direction)
   |  selects a script; cursor and loop mark are set by $D0817F/$D08182/$D0818F
   v
animation script (boy: bank $C8)
   |  animation VM $D080D2, jump table $D08000, once per frame per entity
   v
entity +0x09..+0x0B  layer 1 metasprite pointer (opcode $2C)
entity +0x06..+0x08  layer 2 metasprite pointer (opcodes $22-$2B, bank = opcode + $A9)
   |  display-list builder $CFC662 -> insert $809609 (Y-sorted, rebuilt every frame)
   v
display-list walker $C096BA
   |  per node: JSL $80903F (sprite_compose re-entry)
   v
metasprite: count, dataoff, count x {flags, x, y, block}
   |  flags bit 0 = 0: 8x8 block from table $D90000
   |  flags bit 0 = 1: 16x16 block from table $EE0000
   |  block -> VRAM slot (runtime cache), graphics decoded on a cache miss
   v
OAM shadow $7EAC42 (544 bytes)
   |  NMI: inline DMA at $8082E9 -> OAMDATA $2104
   v
PPU
```

## Entity block

The controlled boy's entity block starts at `$7E4E89`, the dog's at `$7E4F37`. The
animation VM receives the entity's WRAM address in Y; the display-list builder takes it
from DP `$4C`. Known fields (offsets relative to the block start):

| Offset | Size | Meaning | Boy address | Status |
|---|---|---|---|---|
| `+0x00` | 2 | animation script cursor (offset) | `$7E4E89` | verified |
| `+0x02` | 1 | animation script bank | `$7E4E8B` | verified |
| `+0x03` | 2 | loop mark (cursor value) | `$7E4E8C` | verified |
| `+0x05` | 1 | wait counter, frames | `$7E4E8E` | verified |
| `+0x06` | 3 | layer 2 metasprite pointer (lo, hi, bank) | `$7E4E8F` | verified |
| `+0x09` | 3 | layer 1 metasprite pointer (lo, hi, bank) | `$7E4E92` | verified |
| `+0x0C` | | OAM attribute base (palette) | `$7E4E95` | verified for the party-boy render |
| `+0x12` | 2 | flags: bit 14 suppresses the layer 1 node, bit 15 the layer 2 node; bits `$0100`/`$0200` tested by loop opcode `$53` | `$7E4E9B` | verified |
| `+0x16` | 2 | speed parameter (walk 4, run 12), set by opcode `$4D` | `$7E4E9F` | verified |
| `+0x1A` | 2 | X position in map pixels | `$7E4EA3` | verified (writable, camera follows) |
| `+0x1C` | 2 | Y position in map pixels | `$7E4EA5` | verified |
| `+0x22` | 1 | facing = direction * 4 (`$00` up, `$04` right, `$08` down, `$0C` left) | `$7E4EAB` | verified |
| `+0x2E` | | direction written by the player-control code | `$7E4EB7` | verified (dog: `$7E4F65`) |
| `+0x44` | 2 | set to `$FFF0` by opcode `$52` | `$7E4ECD` | meaning open |
| `+0x60` | | candidate for the action-table index | `$7E4EE9` | unverified |
| `+0x6E` | 3 | metasprite pointer of the static party/HUD boy | `$7E4EF7` (off), `$7E4EF9` (bank) | verified |
| `+0x82` | | cleared by opcode `$52` | `$7E4F0B` | meaning open |
| `+0x8E` | 2 | X value read by the party-boy render call `$8FC5DD` | `$7E4F17` | provisional |

Common pitfall: `$7E4EF7` (pointing at the one-chunk metasprite `$CD3F03`) is not the
walking boy. It is a static boy drawn at a fixed screen position (`$02 = $0008`,
`$04 = $00C9`) by `$8FC5DD` (dog: `$8FC619`), which calls `$809032` directly. The walking
boy's frames are the layer pointers at `+0x06` and `+0x09`, drawn through the display list.

## Animation VM (bank `$D0`)

Dispatcher `$D080D2`, called per entity:

```asm
LDX $0000,Y        ; entity +0 = cursor
STX $5D
LDA $0002,Y        ; entity +2 = bank
STA $5F
LDA [$5D]          ; opcode
ASL A              ; index = (op & $7F) * 2, bit 7 -> carry
JSR ($8000,X)      ; jump table $D08000, 128 word entries
                   ; carry set (op >= $80): end of tick, path $D080FC
DEC $0005,X        ; entity +5 = wait counter; at 0 the cursor is persisted ($D0810F)
```

Bit 7 of an opcode means "end this tick after the handler". Several opcodes exist in
both forms (`$41`/`$C1`, `$42`/`$C2`, `$43`/`$C3`, `$53`/`$D3`).

| Opcode | Operand bytes | Handler | Effect |
|---|---|---|---|
| `$01-$1E` | 0 | `$D08371` | wait N frames (entity `+5 = N`), cursor persisted |
| `$1F` | 2 | `$D08381` | computed wait (hardware multiply) |
| `$21` | 0 | `$D08790` | no-op (bare `RTS`) |
| `$22-$2B` | 2 | `$D0841D` | layer 2 pointer: entity `+6/+7` = operand, `+8` = opcode + `$A9` (`$22` -> bank `$CB`, `$23` -> `$CC`, ...) |
| `$2C` | 3 | `$D08434` | layer 1 pointer: entity `+9..+B` = operand (lo, hi, bank) |
| `$2E` | 1 | `$D08926` | sound/effect index (table `$8C8700`) |
| `$30` | 0 | `$D08AE5` | set loop mark: entity `+3/+4` = cursor |
| `$3F` | 2 | `$D088C1` | direction-dependent effect; reads `$7E4EB7` (boy direction) directly |
| `$41`, `$C1` | 0 | `$D086AE` | stop movement |
| `$42`, `$C2` | 1 (signed) | `$D08671` | move by operand (`JSL $8FAD02`) |
| `$43`, `$C3` | 0 | `$D086C8` | counter + 1 |
| `$47` | 4 | `$D087BF` | arc movement |
| `$48` | 0 | `$D08815` | collision check at the layer 2 sprite |
| `$4D` | 2 | `$D0848A` | entity `+0x16` = operand (speed) |
| `$4E` | 0 | `$D0849A` | direction = 0 |
| `$4F` | 0 | `$D084AC` | flag check |
| `$52` | 0 | `$D08458` | script reset, first byte of every script: speed `+0x16`, `+0x06`, `+0x08`, `+0x0A`, `+0x82` = 0, `+0x44` = `$FFF0`, conditionally direction `+0x2E` = 0 |
| `$53`, `$D3` | 0 | `$D083B1` | loop: tests entity `+0x12` bits `$0100`/`$0200`; jump at `$D08412` sets cursor = loop mark |
| `$54` | 2 | `$D08C0E` | conditional jump, 2-byte target |
| `$5B` | 0 | `$D085C6` | trigger: entity `+0x22` indexes table `$9085E1`, result to `$0FCC`; entity `+0x1A` to `$0FCE`, `+0x1C` to `$0FD0` |

Operand lengths for all opcodes used by the 18 boy action groups are known (see
`soe/boysprites.py::_OPLEN`). A second pointer-setting variant at `$D0898B`/`$D089CD`
takes 3 bytes from the stream and calls `$809032` directly, outside the display list;
which opcodes reach it is not recorded. `$D083ED` contains `CPY #$4E89`, a special case
for the boy entity.

Timing: a wait opcode `N` holds the current frame for N frames (measured: walk up holds
8, 8, 7, 8, 8, 6 frames, equal to the script bytes). The `$D3` loop costs one extra tick,
so the last frame of each cycle lasts one frame longer than its script value.

Common pitfall: this VM has 128 jump-table entries indexed by `op & 0x7F`. Early notes
describe it as a "behavior VM with 103 opcodes" driven by map triggers; map triggers run
the separate event script VM ([scripts.md](scripts.md)).

## Action table and boy scripts

Action table `$C4452E` (file `0x04452E`): 16 bytes per action group, 4 directions in the
order up, right, down, left; each entry `{addr:u16, bank:u8, flag:u8}`. In all 18 groups
(0-17) the script bank is `$C8` and the flag is `$40` on the up entry, `$00` otherwise.

| Group | Meaning | Status |
|---|---|---|
| 5 | stand | verified |
| 6 | walk | verified (direction order measured) |
| 7 | run; only selected with the Jaguar Ring flag set (`$7E2262` bit 1) and A held | verified |
| 9 | attack while standing (B without direction), independent of the ring | verified |
| 10 | attack while moving without the ring (B + direction); with the ring, group 9 is used | verified |
| 0-4, 8, 11-17 | not identified | open |

Structure of the unidentified groups (static parse): group 0 has 5 frames and is the only
group with metasprite bank `$CC`; groups 2 and 14 are structural copies of walk (6
frames), groups 3 and 15 of run (4 frames); group 4 has 7 frames using both layers per
frame; groups 1 and 13 have 1 frame using both layers; groups 8 and 16 have 1 frame of
duration 19; group 11 has 4 frames (4, 5, 10, 5); group 12 has 8 frames; group 17 has 4
frames (7, 6, 5, 4). Not all 18 are distinct poses.

The code that computes the table index from action, direction and ring flag was not found
statically (it is reached through an indirect call). Readers at `$908124`, `$908139` and
`$908144` use `direction = entity[+0x22] / 4`; the attack reader at `$908344` always uses
direction 0. A trace points at `$1462`/`$1464` before `JMP $D08124` with caller `$CFCE2B`
(provisional).

Boy scripts (bank `$C8`):

| Action | Up | Right | Down | Left |
|---|---|---|---|---|
| stand (group 5) | `$C811CE` | `$C811DC` | `$C811EA` | `$C811F8` |
| walk (group 6) | `$C81206` | `$C81233` | `$C81260` | `$C8128D` |
| run (group 7) | `$C812BA` | `$C812DB` | `$C812FC` | `$C8131D` |
| attack while moving (group 10) | `$C8142E` | `$C81459` | `$C81484` | `$C814AF` |

Script shapes (`<..>` = operands):

```
stand  52 2C <lo hi> CB 22 <lo hi> 09 C1 41 D3 ...
walk   52 4D 04 00 (22 <lo hi> <dur> C2 06|07) x6 42 <n> D3 ...
run    52 4D 0C 00 (22 <lo hi> <dur> C2 0A|0B) x4 42 <n> D3 ...
```

Stand frames use both layers (for stand down: layer 1 `$CB10EB` feet, layer 2 `$CB10F7`
body); walk and run use layer 2 only.

Metasprites (bank `$CB`):

- Walk up: `$CB114B`, `$CB1165`, `$CB117A`, `$CB118F`, `$CB11AE`, `$CB11C3` (8, 8, 7, 8, 8, 6
  frames).
- Walk right: `$CB11D8` to `$CB12B4` (7, 8, 8, 7, 8, 7). Walk down: `$CB12E2` to `$CB1369`
  (8, 8, 7, 8, 8, 6). Walk left: `$CB137E` to `$CB145A` (7, 8, 8, 7, 8, 7), the mirror of
  right (chunk flags `$10` instead of `$50`).
- Run: 4 frames per direction (8, 6, 8, 5), metasprites `$CB1488` to `$CB16E0`.

Decoder: `soe/boysprites.py` (`parse_anim_script`, `boy_action_scripts`,
`compose_chunks`); atlas builder `soe/boyatlas.py`.

## Display list

Rebuilt every frame, sorted by Y.

- Reset `$809684`: rebuilds 17 bucket anchors at `$7E50A7-$7E5127` (8 bytes apart). The
  first anchor gets status `$FFFE`, the others `$FFFF`. Sets the node allocator
  `$1278 = $512F`.
- Insert `$809609`: Y = `$1278` (node already filled by the caller); bucket index
  `(node[+4] & $03C0) >> 3` via the shortcut cache `$50AD,X`; insertion sort on node `+4`;
  `$1278 += 15` (node size). Callers: `$CFC695`, `$CFC6EA`, `$CFC863`, `$D08219`,
  `$D0DC31`.
- Builder `$CFC662`: `LDX $4C` (entity). Layer 1: unless entity `+0x12` bit 14 is set,
  copies entity `+0x09..+0x0B` to node `+0x0C..+0x0E`; DP `$02`/`$04`/`$06` to node `+6`/`+8`/`+A`;
  sort key DP `$08` minus 10 to node `+4`; `JSL $809609`. Then (`$CFC69E-$CFC6B1`) the same for
  layer 2 from entity `+0x06..+0x08`, suppressed by bit 15.
  Measured on the boy: the layer 2 insert at `$CFC6EA` runs every frame, the layer 1
  insert at `$CFC695` only on stand frames.
- Walker `$C096BA`: sets DBR = `$7E`, `LDX $5127` (head = last of the 17 anchors). Loop
  `$C096C0-$C096EA`:
  - node `+4` bit 7 set: end marker; `$FFFE` resets and returns, otherwise follow node `+0`.
  - node `+6` to `$02` (screen X), `+8` to `$04` (screen Y), `+A` to `$06` (OAM attribute
    base; palette = `($06 >> 1) & 7`).
  - node `+C/+D` to `$26/$27` and node `+D/+E` to `$27/$28` (two overlapping 16-bit
    stores that also load the bank `$28`).
  - `PHX; JSL $80903F; PLY; LDX $0000,Y` (next node).

Node layout (15 bytes):

| Offset | Size | Meaning |
|---|---|---|
| `+0x00` | 2 | link to the next node |
| `+0x04` | 2 | sort key; bit 7 marks an anchor/end (`$FFFE`, `$FFFF`) |
| `+0x06` | 2 | screen X |
| `+0x08` | 2 | screen Y |
| `+0x0A` | 2 | OAM attribute base |
| `+0x0C` | 3 | 24-bit metasprite pointer |

Bytes `+0x02/+0x03` are not described.

## Metasprite format

A metasprite (SoETilesViewer calls it SpriteInfo) is read by `sprite_compose` through the
24-bit pointer in DP `$26/$27/$28`:

| Offset | Size | Field |
|---|---|---|
| `+0` | 1 | count: number of chunks; 0 = nothing to draw |
| `+1` | 1 | dataoff: offset from the metasprite start to the first chunk |
| `+dataoff` | 5 * count | chunks |

Chunk (5 bytes, stride applied at `$809106`):

| Byte | Field | Use |
|---|---|---|
| 0 | flags | bit 0: 0 = 8x8 path, 1 = 16x16 path; bit 6 H-flip, bit 7 V-flip; bits 1-3 palette; bits 4-5 masked out |
| 1 | x (i8) | sign-extended, plus DP `$02` = screen X (`$16`), culled off-screen |
| 2 | y (i8) | sign-extended, plus DP `$04` = screen Y (`$18`), culled if `>= $E0` |
| 3-4 | block (u16) | graphics block number in the table chosen by bit 0 |

Example: the party-boy metasprite `$CD3F03` has count 1, dataoff 2, one chunk with flags
`$11`, x 0, y 0, block `$07AB`.

### `sprite_compose` (`$809032`, bank `$80`)

- Entry `$809032` sets DP `$07 = $CE` (attribute mask). Re-entry `$80903F`, used by the
  display-list walker, only clears bit 0 of `$07` (`LDA #$01; TRB $07`). Both continue at the
  shared body `$809049`.
- Emit loop `$80910D`: flags to `$DF`; `$809117 ROR; BCC` selects the 8x8 path (`$80911D`) or
  the 16x16 path (`$8091FC`).
- Per chunk one OAM entry at `$7EAC42 + $D3`, then `$D3 += 4`:
  `+0 = X ($16)`, `+1 = Y ($18)`, `+2 = VRAM tile slot ($DB)`,
  `+3 = (flags AND [$07]) + [$06]`. With `$07 = $CE` the flip and palette bits pass.
- The high-table bits (X bit 8 and size) are collected in `$D5`/`$D7` (`$8091D6`).
- `$8092EA` is the on-screen emit and block-allocation part of the 16x16 path.

Common pitfalls: `$8091FF` (a `REP #$31` inside the 16x16 path) and `$80934D` (a `TXA`
inside block allocation) are not entry points; their apparent callers in bank `$C6` are
data. An exec trap on `$809032` alone misses every display-list node; trap `$80903F` too.

## Sprite graphics blocks

Two pointer tables, selected by chunk flags bit 0. The table index is the raw block
number times 3; no base is added.

| Path | Table | Entry | Bank rule | Block size | Loader |
|---|---|---|---|---|---|
| bit 0 = 0, 8x8 | `$D90000` (file `0x190000`) | 3 bytes | `(byte2 & 0x7F) + 0x52` | 32 bytes | `$80A4B4` |
| bit 0 = 1, 16x16 | `$EE0000` (file `0x2E0000`) | 3 bytes | `(byte2 & 0x7F) + 0x5A` | 128 bytes | `$8096FD` |

Entry: `offset = u16(byte0, byte1)`, `bank` as above, bit 7 of `byte2` = compressed with
the zero-word codec ([compression.md](compression.md)); otherwise raw. A 16x16 block is
four 8x8 4bpp tiles (top-left, top-right, bottom-left, bottom-right).

```asm
; $80973A (16x16 loader)
LDA $DD
ASL A
ADC $DD            ; X = block * 3
TAX
LDA $EE0001,X
BMI compressed     ; bit 7 of byte 2
LDA $EE0000,X
TAY
```

Example: block `$07AB` resolves to file `0x214A5A` (compressed, 128 bytes after decoding).
All boy blocks `$0795-$07F1` decode to valid 128-byte blocks in bank `$61`
(file `0x2146EA` to `0x214D26`).

Boy frames mix both paths: 8x8 chunks for hands, feet and head, 16x16 for the torso.

Common pitfall: SoETilesViewer's US addresses (`$EC0000` for 16x16 sprite blocks with a
data base, `$D80000` for 8x8) do not apply to the Europe ROM, and no base offset is added
in the Europe code.

### VRAM slot allocator

The block number is not a VRAM tile number. Each path keeps a cache from block to VRAM
slot; on a miss a slot is reassigned through an LRU-like list and the graphics are loaded:

| Path | Slot cache | Lookup | LRU lists | Reload |
|---|---|---|---|---|
| 8x8 | `$7D51,X` | `CMP $95AE,Y` | `$96AE`, `$9730`, `$972F` | `$80A4B4` |
| 16x16 | `$97B2,X` | `CMP $AABC,Y` | `$AB7C`, `$ABDE`, `$ABDD` | `$8096FD` |

The resulting tile slot goes to DP `$DB`. Because slots are assigned at run time, OAM
tile numbers change between frames for the same pose; OAM tile differences are useless
as an animation detector.

## OAM shadow and DMA

- Shadow buffer `$7EAC42`, 544 bytes (512-byte main table + 32-byte high table).
- The NMI handler (`$80823A`) transfers it inline at `$8082E9`: B-bus address `$04`
  (`$2104` OAMDATA), size `$220`.
- OBJ character base measured during gameplay: VRAM byte `$C000` (word `$6000`), second
  name table at byte offset `$2000` (word `$1000`).
- OBJ palettes are CGRAM rows 8-15. The boy uses OBJ palette 6, the dog OBJ palette 7.
- OBJ priority of boy and dog sprites is 3 (party-boy render: attribute base
  `$7E4E95 | $30`).

## Palettes

- Character data table `$8EB678` (file `0x0EB678`): 74-byte records (same layout as
  SoETilesViewer `characterdata.h`), 25 valid entries. A 16-bit palette pointer at
  `+0x09` resolves in bank `$10`: `file = (0x100000 | ptr) & 0x3FFFFF`. The referenced
  palettes lie on a 32-byte grid in `0x10AD10-0x10C06F`.
- The boy has 8 palette variants from `0x10AD10`. The in-game palette (CGRAM OBJ slot 6)
  is variant 3 at `0x10AD70`, verified word for word against CGRAM. Colors 1-5 are equal
  in all variants, 6-11 hold two clothing and hair sets, 12-13 are weapon colors
  (variant 0 has a green placeholder, variant 3 bone colors).
- Bosses do not use this table: at most 1 to 5 of 16 boss colors match any of the 25
  entries.

The record also holds 16-bit pointers at `+0x32` to `+0x46` (11 values). Reading them as
bank-`$07` animation pointers is a mistake. The boy record's `+0x32` value `$457E` resolves
to `$C8457E`, which holds a bank-`$C8` animation script using opcode `$23` (metasprite bank
`$CC`), apparently for a different actor. What these fields select is open.

## Z-order

From an OAM dump of the walking boy: layer 2 chunks 0-3 occupy OAM slots 14-17, layer 1
chunks slots 18-19. A lower OAM slot is drawn in front, so chunk 0 is on top and layer 2
(entity `+0x06`) is in front of layer 1 (entity `+0x09`). A composer must draw chunks in
reverse order (`soe/boysprites.py::compose_chunks`).

## Verification

Comparison of frames composed from ROM data against OAM + VRAM + CGRAM reconstructions of
emulator captures (`tools/verify_boy_atlas.py`):

- stand: 4 of 4 frames score 1.000; walk: 24 of 24 score 1.000.
- run: 14 of 16 score 1.000, plus 2 frames that match as silhouettes only (the capture is
  tinted); one frame (down, frame 3) scores 0.154 against a single isolated capture frame,
  unresolved.
- group 10 attack up: 3 of 4 score 1.000; frame 2 scores 0.235 because the capture shows 9
  sprites where the metasprite has 6 (possibly a hit effect in the same cluster),
  unresolved. Right, down and left have no capture data.

## Player input

- `$808471` reads the joypad: waits on `$4212`, reads `$4218`/`$421A` (auto-joypad),
  stores held buttons to `$0EC8` (16-bit) and newly pressed buttons to `$0104`.
- Bit layout of `$0EC8` is the standard auto-joypad layout. D-pad: right `$0100`, left
  `$0200`, down `$0400`, up `$0800`.
- Readers of `$0EC8` cluster in bank `$CF` (`$CFCD31`, `$CFCDF3`, `$CFCF1C`, `$CFCF37`,
  `$CFD064`, `$CFD071`). They update the direction field `+0x2E` of the controlled entity
  (boy `$7E4EB7`, dog `$7E4F65`). Individual roles are provisional.
- Jaguar Ring: charm flags at `$7E2261-$7E2263`; `$7E2262` bit 1 is the Jaguar Ring
  (found by bisection in the emulator). Without it, holding A does not change the boy's
  action.

## Large sprites and bosses

Non-boy actors use the same VM, display list, metasprite format and block tables, but their
action tables and scripts are not mapped. Two extraction routes are documented:

- Live capture (`soe/bigsprites.py`): run the map in the emulator and record OAM, VRAM and
  CGRAM per frame; group OAM entries spatially into actors and track them over frames by
  OAM slot. A large sprite is just a group of 8x8 and 16x16 OAM entries. Limit: bosses do
  not spawn when a map is loaded through the map-id hijack, because their spawn scripts do
  not run.
- Static search (`soe/bosses.py`): boss tiles are zero-word compressed 16x16 blocks in the
  file range `0x1E0000-0x2C0000`. They were located by decoding a block at every offset
  and matching its tiles, independent of palette, against external reference sprite sheets.
  Hits cluster in a narrow offset range per boss. Palettes are reconstructed from the match
  because bosses are not in the character table. This locates graphics, not the game's own
  metasprites or scripts.

Common pitfall: walking a sprite block chain sequentially (next block = offset + bytes
consumed) desynchronizes after a few blocks.

## Open points

- Names of action groups 0-4, 8, 11-17; the code that computes the action-table index.
- Action tables and scripts for the dog and all other actors (the dog's scripts likely use
  opcode `$23`, metasprite bank `$CC`).
- Character record fields `+0x32` to `+0x46`.
- Display-list node bytes `+0x02/+0x03`; entity fields marked open above.
- Which opcodes use the direct-render variant `$D0898B`/`$D089CD`.

## Address quick reference

| What | SNES | File |
|---|---|---|
| NMI handler | `$80823A` | `0x00823A` |
| OAM DMA inline in NMI | `$8082E9` | `0x0082E9` |
| joypad read | `$808471` | `0x008471` |
| sprite_compose | `$809032` | `0x009032` |
| sprite_compose re-entry | `$80903F` | `0x00903F` |
| compose emit loop | `$80910D` | `0x00910D` |
| compose 16x16 path | `$8091FC` | `0x0091FC` |
| compose on-screen emit (16x16) | `$8092EA` | `0x0092EA` |
| display-list insert | `$809609` | `0x009609` |
| display-list reset | `$809684` | `0x009684` |
| 16x16 graphics loader | `$8096FD` | `0x0096FD` |
| 8x8 graphics loader | `$80A4B4` | `0x00A4B4` |
| display-list walker | `$C096BA` | `0x0096BA` |
| action table | `$C4452E` | `0x04452E` |
| boy animation scripts | `$C811CE-$C814AF` | `0x0811CE` |
| boy metasprites | bank `$CB` | `0x0Bxxxx` |
| party-boy metasprite | `$CD3F03` | `0x0D3F03` |
| character data table | `$8EB678` | `0x0EB678` |
| party-boy / dog compose calls | `$8FC5DD` / `$8FC619` | `0x0FC5DD` / `0x0FC619` |
| display-list builder | `$CFC662` | `0x0FC662` |
| animation VM jump table | `$D08000` | `0x108000` |
| animation VM dispatcher | `$D080D2` | `0x1080D2` |
| 8x8 sprite block table | `$D90000` | `0x190000` |
| 16x16 sprite block table | `$EE0000` | `0x2E0000` |
| boy in-game palette | | `0x10AD70` |
| OAM shadow | `$7EAC42` | WRAM |
