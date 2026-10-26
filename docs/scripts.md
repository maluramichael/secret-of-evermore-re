# Event scripts

Secret of Evermore drives cutscenes, map transitions, NPC dialogue, shops and story text
with a byte-oriented event script VM. This document covers how scripts are located, the
instruction encoding and the opcode set. The per-entity animation VM in bank `$D0` is a
different interpreter, see [sprites.md](sprites.md).

Address convention: SNES addresses are written `$BBAAAA`. The ROM is HiROM without a copier
header; for the ROM banks used here the file offset is `snes & 0x3FFFFF` (equivalently
`snes & ~0xC00000` for banks `$C0-$FF` and `$80-$BF`).

The resolution rules and opcode names come from the third-party SoEScriptDumper project
(`list-rooms.cpp`, `data.h`). This repo reimplements them in `soe/script.py` and verifies
them against the Europe ROM.

## Status

- Script lookup: verified.
- Instruction lengths: verified. `soe/script.py::instr_len` agrees with SoEScriptDumper on
  all 61018 instructions it decodes from the Europe ROM (address, opcode and length). The
  script walker reproduces its instruction stream exactly (the length dump omits `END`
  instructions; that is the only difference).
- Opcode semantics: names follow SoEScriptDumper. Some opcodes are marked as untraced
  there; they carry a `?` below. Their lengths are still verified, so disassembly stays in
  sync.
- Text references and map warps resolve for every occurrence (756 text opcodes, 525 warps).

## Locating scripts

Map trigger zones (see [maps.md](maps.md)) are 6 bytes: `[x1][y1][x2][y2][scriptid:u16]`.
The last two bytes are a script id, a byte offset into a pointer table, not a pointer.

```
scripts_start          Europe $938000 (file 0x138000), USA $928000
mapscriptptr         = scripts_start + read16(scripts_start)
script address       = script2romaddr(read24(mapscriptptr + scriptid))
map enter script     = script2romaddr(read24(scripts_start + 0x1B + 5 * mapid))
script2romaddr(sa)   = scripts_start + (sa & 0x7FFF) + ((sa & 0xFF8000) << 1)
```

Notes:

- Script pointers are stored in a packed 24-bit form; `script2romaddr` converts them to a
  ROM address relative to `scripts_start`.
- The map list address used by SoEScriptDumper is `$A0FDE5` for Europe (`$9FFDE7` for
  USA). For Europe this is the pointer field of the map pointer table described in
  [maps.md](maps.md).
- The second trigger list of a map (called B-triggers in the tooling) is presumably
  activated by the B button (interaction); the distinction is not verified.

Common pitfall: an earlier hypothesis treated the trigger bytes as a direct pointer into a
"behavior VM" in bank `$CA` with the jump table `$D08000`. That VM is the animation VM
documented in [sprites.md](sprites.md); map triggers do not run it.

## Instruction encoding

Every instruction is `[opcode][operands]`. Operand templates per opcode use these tokens:

| Token | Meaning |
|---|---|
| `B` | 1 byte |
| `W` | 2 bytes, little-endian |
| `T` | 3 bytes (24-bit address) |
| `S` | sub-instruction expression, variable length |

### Expressions (`S`)

An expression is a self-terminating byte chain: bytes are read until one has bit 7 set.
Each byte is one of:

| Byte (bit 7 ignored) | Meaning | Extra bytes |
|---|---|---|
| `$50`, `$51`, `$52`, `$53`, `$2D`, `$2E` | entity reference: boy, dog, player, npc, last entity, attacking entity | 0 |
| `(b & 0x70) == 0x30` | constant `b & 0x0F` | 0 |
| `(b & 0x70) == 0x40` | constant `-16 + (b & 0x0F)` | 0 |
| `(b & 0x70) == 0x60` | constant `0x10 + (b & 0x0F)` | 0 |
| `$01`, `$02`, `$0F-$13` | operator with a 1-byte argument | 1 |
| `$03-$0E` | operator with a 2-byte argument | 2 |
| `$00`, `$14-$2C`, `$54-$5C` | operator without argument | 0 |

The semantics of the operator bytes are not decoded in this repo. Reference:
`soe/script.py::parse_sub`.

### Special-length opcodes

| Opcode | Encoding |
|---|---|
| `$2E` | one token byte; `$84`, `$88`, `$8D` are followed by 2 bytes, `$92` by 1 byte; an entity reference or final constant ends the instruction; one longer special form exists (see `_end_2e`) |
| `$3F` | a final constant byte or an expression, then 4 bytes |
| `$9E`, `$AC` | three expressions, then expressions until one evaluates to 0 |
| `$AF-$B4` | count byte n, n expressions, then 3, 1, 2, 1, 2, 3 trailing bytes for `$AF`, `$B0`, `$B1`, `$B2`, `$B3`, `$B4` |

### Branches

- `$04`, `$08`, `$09`, `$0A`, `$0B`, `$8E`, `$8F`: the last operand word is a signed
  offset; target = end of instruction + offset.
- `$05`: 1-byte backward skip; target = instruction start + (byte - 256).

## Text and warps

- Story text is inline in the event scripts. Opcodes `$50`, `$51`, `$52`, `$54`, `$7F`
  and `$8C` load text through `address = $91D000 + word` (`$50` has a leading byte, so its
  word is the second and third operand byte). `$91D000` (file `0x11D000`) is the text
  pointer table with 3 bytes per entry, so text id = `word / 3`. Example: map 56 (`$38`)
  contains `SHOW_TEXT` with word `$063F`, which is text id 533. Text format: see
  [text.md](text.md).
- Opcode `$22` CHANGE_MAP: `[x:1][y:1][mapid:u16]`, map id in the low byte (0 to 126).

## Opcode table

Length template as described above; "special" see the section on special-length opcodes.

| Op | Name | Operands |
|---|---|---|
| `$00` | END | |
| `$04` | SKIP | `W` |
| `$05` | SKIP_BACK | `B` |
| `$07` | CALL_ABS24 | `T` |
| `$08` | IF | `S W` |
| `$09` | IF_NOT | `S W` |
| `$0A` | IF_MONEY_GE | `S T W` |
| `$0B` | IF_MONEY_LT | `S T W` |
| `$0C` | SETBIT_2258 | `W S` |
| `$0D` | SETBIT_2834 | `W S` |
| `$0E` | SETBIT_ARG | `B S` |
| `$10` | WRITE_B_2258 | `W S` |
| `$11` | WRITE_B_2834 | `W S` |
| `$14` | WRITE_B_2258b | `W S` |
| `$15` | WRITE_B_2834b | `W S` |
| `$17` | SET_WORD_FAST | `W W` |
| `$18` | WRITE_W_2258 | `W S` |
| `$19` | WRITE_W_2834 | `W S` |
| `$1A` | WRITE_ARG | `B S` |
| `$1B` | SET_TWO | `W W B B` |
| `$1C` | WRITE_W_2258b | `W S` |
| `$1D` | WRITE_W_2834b | `W S` |
| `$1E` | WRITE_ARGb | `B S` |
| `$20` | TELEPORT_BOTH | `B B` |
| `$22` | CHANGE_MAP | `B B W` |
| `$26` | ?VRAM_WRITE | |
| `$27` | FADE_OUT | |
| `$29` | CALL_ABS24b | `T` |
| `$2A` | (unnamed) | `S` |
| `$2B` | (unnamed) | `S` |
| `$2C` | ?CALLER_INFO | `B` |
| `$2D` | ?CALLER_ALT | `B` |
| `$2E` | WAIT_DEST | special |
| `$30` | SFX | `B` |
| `$31` | SFX2 | `B` |
| `$32` | SFX3 | length not in the table |
| `$33` | MUSIC | `B` |
| `$38` | YIELD | |
| `$39` | SLEEP_SUB | `B` |
| `$3A` | YIELD2 | |
| `$3B` | SLEEP_SUBb | `S` |
| `$3C` | LOAD_NPC | `W W B B` |
| `$3D` | SET_NPC_TALK | `S W` |
| `$3F` | SET_NPC_SCRIPT | special |
| `$42` | TP_ENT_BYTE | `S W` |
| `$43` | TP_ENT_SUB | `S S S` |
| `$44-$47` | MSGBOX | `B B B B B` |
| `$48-$4B` | MSGBOX_DEF | |
| `$4D` | NOP | |
| `$4E` | ATTACH_ENT | `S` |
| `$50` | SHOW_TEXT_UNWIN | `B W` |
| `$51` | SHOW_TEXT | `W` |
| `$52` | SHOW_TEXT_UNWIN2 | `W` |
| `$54` | CLEAR_TEXT_VRAM | `B` |
| `$55` | CLEAR_TEXT | |
| `$58` | FADEIN_VOL | |
| `$59` | FADEOUT_VOL | |
| `$5A` | ?MSG_TIMER | |
| `$5B` | ?MSG_TIMER2 | |
| `$5C` | SET_OBJ_STATE | `S S` |
| `$5D` | UNLOAD_OBJ_IF | `S W` |
| `$62` | ?COPY_DATA | `B W W` |
| `$63` | ALCHEMY_SCREEN | |
| `$6C` | ?ENT_OP | `S B B` |
| `$6D` | WALK_REL | `S S S` |
| `$6E` | WALK_REL_BYTE | `S B B` |
| `$6F` | WALK_REL_SUB | `S S S` |
| `$70` | FACE_ENT | `S S` |
| `$71` | FACE_EACH | `S S` |
| `$73` | WALK_ABS | `S S S` |
| `$74` | FACE_N | `S` |
| `$75` | FACE_S | `S` |
| `$76` | FACE_W | `S` |
| `$77` | FACE_E | `S` |
| `$78` | SET_SPRITE | `S W S` |
| `$79` | SET_SPRITE2 | `S W S` |
| `$7A` | WRITE_DEREF | `S S` |
| `$7C` | GIVE_MONEY | `S T` |
| `$7D` | TAKE_MONEY | `S T` |
| `$7E` | EXCHANGE_MONEY | `S S S S` |
| `$7F` | NAME_INPUT | `W` |
| `$80` | UNHIDE_TEXT | |
| `$81` | HIDE_TEXT | |
| `$82` | ?LAYERS | |
| `$83` | UPD_LAYERS | |
| `$84` | GIVE_MONEY_SUB | `S S` |
| `$85` | TAKE_MONEY_SUB | `S S` |
| `$86` | ?AUDIO_VOL | `S` |
| `$87` | ?AUDIO_SPD | `S` |
| `$88` | SHOP_CLEAR | |
| `$89` | SHOP_ADD | `S S` |
| `$8A` | SHOP_MOVE | `S` |
| `$8C` | SAVE_MENU | `W` |
| `$8D` | SCREEN_SHAKE | `B` |
| `$8E` | IF_MONEY_GE_SUB | `S S W` |
| `$8F` | IF_MONEY_LT_SUB | `S S W` |
| `$91` | SET_BRIGHTNESS | `S` |
| `$92-$95` | DAMAGE | `S S` |
| `$96` | TP_SCREENS | `S S` |
| `$97` | ?OP_7SUB | `S S S S S S S` |
| `$98` | SWITCH_CHAR | `S` |
| `$99` | MODE7_MAP | `S S S S S S` |
| `$9A` | SET_FONT | `S` |
| `$9B` | ?DEALLOC | `S` |
| `$9C` | ?DEC_SCRIPTS | `S` |
| `$9D` | WALK_ABS_BARRIER | `S S S` |
| `$9E` | CAST_SPELL | special |
| `$9F` | CURR_PREP | |
| `$A0` | CURR_SHOW | |
| `$A1` | CURR_HIDE | |
| `$A2` | SPAWN_NPC | `W W S S` |
| `$A3` | CALL_SUB | `B` |
| `$A4` | CALL_16 | `W` |
| `$A5` | CALL_8_NEG | `B` |
| `$A6` | CALL_16_REL | `W` |
| `$A7` | SLEEP | `B` |
| `$A8` | SLEEP16 | `W` |
| `$A9` | ?OP_2SUB | `S S` |
| `$AA` | ?OP_AA | |
| `$AC` | CAST_SPELL_ALIVE | special |
| `$AD` | STORE_2834 | `W W B B` |
| `$AE` | ?MOD_SCRIPT | `B B B B` |
| `$AF` | ?CALL_MULTI | special |
| `$B0` | CALL_MULTI_G8 | special |
| `$B1` | CALL_MULTI_N16 | special |
| `$B2` | CALL_MULTI_R8 | special |
| `$B3` | CALL_MULTI_R16 | special |
| `$B4` | CALL_MULTI_A24 | special |
| `$B5` | ?DRAW_LIGHTNING | `S S S S S S S S` |
| `$B6` | TILE_FLASH | `S S S S` |
| `$B7` | TILE_FLASH_STOP | `S` |
| `$B9` | (unnamed) | `S S S` |
| `$BA` | LOAD_NPC_B | `B B B` |
| `$BB` | (unnamed) | `S S` |
| `$BC-$C1` | ?OP_BC to ?OP_C1 | |
| `$C2` | ?OP_C2 | `B B B` |

Lengths are known for 149 opcodes. `$32` has a name but no length entry (it does not occur
in the decoded instruction stream). Opcodes not listed have no known length; the
disassembler stops when it meets one.

Control-flow summary:

- `$00` ends the script (return).
- `$04`/`$05` unconditional skips.
- `$08`/`$09` conditional skip on an expression; `$0A`/`$0B`/`$8E`/`$8F` conditional skip
  on a money comparison.
- Calls: `$07`, `$29` (absolute 24-bit), `$A3`-`$A6` (sub/global/relative), `$AF`-`$B4`
  (multiple calls).

The names `..._2258` and `..._2834` presumably refer to WRAM bases `$7E2258` and `$7E2834`
used as flag and variable storage. This comes from the names only and is not verified
here (see [memory-map.md](memory-map.md)).

## Other bytecode interpreters

- Animation VM, bank `$D0` (dispatcher `$D080D2`, jump table `$D08000`): per-entity
  animation and movement, documented in [sprites.md](sprites.md).
- An interpreter at `$8CEE44` (`LDA [$82]; INC $82; JMP ($8CF442,X)`) was the most
  frequently called routine in an emulator call-target trace (about 1300 calls). What it
  runs is not identified.

## Tools

- `soe/script.py`: disassembler (`instr_len`, `parse_sub`, `decode`, opcode tables) with
  text and warp resolution.
- `soe/mapdata.py`: combines trigger zones with collision data.
