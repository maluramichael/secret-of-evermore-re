# Labels

Curated address-to-name table for Secret of Evermore (Europe), ROM SHA1
`ae17166919fdfdf26cc5771f83cfd19eaf71806c`, HiROM, no copier header,
`file_offset = snes_addr & 0x3FFFFF`.

This file is machine-readable. `tools/ghidra/apply_names.java` parses every table row of
the form `| $XXXXXX | 0xYYYYYY | name | ... |` and writes the name into the Ghidra program:
it renames an existing function, else creates a function at already disassembled code,
else places a plain label (data tables are never disassembled). Rows whose second column
is not a `0x` file offset (the RAM tables at the end) are ignored by the script.

Conventions:

- The SNES address is where the code executes and where the Ghidra memory map resolves
  it: banks `$80-$BF` through the byte-mapped mirror, banks `$C0-$FF` in the primary
  block.
- Names are lower_snake identifiers so they survive as Ghidra symbols unchanged.
- A trailing `?` marks a provisional name: behavior inferred from a short disassembly or
  a single observation, not byte-exact verified. `apply_names.java` turns `?` into the
  suffix `_q`.

Source column:

| Src | Meaning |
|---|---|
| `VEC` | ROM interrupt vector table (`$00FFE0-$00FFFF`) |
| `DIS` | static disassembly, checked against ROM bytes |
| `TRC` | observed in a Mesen2 execution trace (call target, writer PC or call frequency); behavior from a short disassembly |
| `DAT` | data layout verified by decoding ROM data |
| `EXT` | layout taken from a third-party tool (SoETilesViewer, SoEScriptDumper) and checked against the Europe ROM |

Combinations such as `DIS+TRC` mean both kinds of evidence exist.

## Interrupt vectors

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $808020 | 0x008020 | reset_boot | VEC | | emulation RESET vector `$00FFFC` -> `$8020` |
| $80823A | 0x00823A | nmi_handler | VEC+TRC | sprites.md | native NMI vector `$00FFEA` -> `$823A`; runs every frame |
| $8084EA | 0x0084EA | irq_handler | VEC | | native IRQ vector `$00FFEE` -> `$84EA` |

## Decompression codecs (bank `$8C`)

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $8C9382 | 0x0C9382 | sub_8c9382 | DIS | | function entry from Ghidra auto-analysis in the codec bank; not analysed |
| $8C9C22 | 0x0C9C22 | decompress_dispatch | DIS | compression.md | opcode dispatcher; `JMP ($9C36,X)` |
| $8C9C36 | 0x0C9C36 | decompress_jumptable | DIS | compression.md | opcode -> handler jump table (data, 8 words) |
| $8C9C46 | 0x0C9C46 | op0_blockcopy | DIS | compression.md | opcode 0, raw block copy |
| $8C9C5E | 0x0C9C5E | lzss_decompress | DIS | compression.md | opcode 3 LZSS, 4 KiB ring at `$7FA000` |
| $8C9C92 | 0x0C9C92 | lzss_symbol_loop | DIS | compression.md | per-symbol literal/match loop |
| $8C9D5E | 0x0C9D5E | lzss_match_copy | DIS | compression.md | match copy |
| $8C9D9F | 0x0C9D9F | lzss_match_copy_wrap | DIS | compression.md | match copy variant for tokens `>= $FEE0`, wraps the ring read pointer |
| $8C9DDB | 0x0C9DDB | lzss_bitmask_table | DIS | compression.md | 16 MSB-first bit masks (data) |
| $8C9EFA | 0x0C9EFA | op7_decompress | DIS+TRC | compression.md | opcode 7 record pointer table codec |
| $8C9F72 | 0x0C9F72 | op7_bitread | DIS | compression.md | bit reader |
| $8C9F88 | 0x0C9F88 | op7_context_update | DIS | compression.md | updates `$26` (above) / `$12` (left) contexts and history |
| $8C9FC5 | 0x0C9FC5 | op7_new_word | DIS | compression.md | new record word generator (`$0C`) |
| $8C9FEA | 0x0C9FEA | op7_copy_above | DIS | compression.md | copy cell-above pointer |
| $8CA00A | 0x0CA00A | op7_history_copy0 | DIS | compression.md | history copy |
| $8CA01D | 0x0CA01D | op7_history_copy1 | DIS | compression.md | history copy |
| $8CA030 | 0x0CA030 | op7_backref | DIS | compression.md | general back reference |
| $8CA080 | 0x0CA080 | op7_backref_wide | DIS | compression.md | back reference, wide index path |
| $8CA08C | 0x0CA08C | op7_prefix_table | DIS | compression.md | top-5-bit prefix jump table (32 words) |
| $8CA0F0 | 0x0CA0F0 | op7_bitreader_cascade | DIS | compression.md | bit-reader cascade table |
| $8CA134 | 0x0CA134 | op7_index_extract | DIS | compression.md | index extractor table |

## Map loader (bank `$90`)

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $908F68 | 0x108F68 | map_loader | DIS+TRC | maps.md | entry, `LDA $0ADB` (current map id) |
| $908F85 | 0x108F85 | mapheader_parse | DIS | maps.md | reads dimensions (`+2/+3`) and PPU registers |
| $908E85 | 0x108E85 | prefixsum_expand | DIS | maps.md | in-place delta -> absolute prefix sum over `$7FC300` |
| $9090A2 | 0x1090A2 | palanim_list_loop | DIS | maps.md | palette-animation list -> registrar `$90D532` |
| $9091C1 | 0x1091C1 | tileset_dma_inline | DIS+TRC | maps.md | inline tileset DMA to VRAM char base (word `$2000`) |
| $909105 | 0x109105 | maploader_tail | DIS | maps.md | remaining decompression calls, hardware divide by 3 |
| $90A0B7 | 0x10A0B7 | maploader_sub_a0b7 | DIS | maps.md | `JSL` target of the loader, not analysed |
| $90A146 | 0x10A146 | maploader_sub_a146 | DIS | maps.md | `JSL` target of the loader, not analysed |
| $90CC1F | 0x10CC1F | maploader_sub_cc1f | DIS | maps.md | `JSL` target of the loader, not analysed |
| $90D043 | 0x10D043 | maploader_sub_d043 | DIS | maps.md | `JSL` target of the loader, not analysed |
| $9094D2 | 0x1094D2 | maploader_sub_94d2 | DIS | maps.md | `JSL` target of the loader, not analysed |
| $8CAED7 | 0x0CAED7 | maploader_sub_8caed7 | DIS | maps.md | `JSL` target of the loader, not analysed |
| $8CCC4F | 0x0CCC4F | maploader_sub_8ccc4f | DIS | maps.md | `JSL` target of the loader, not analysed |
| $90D532 | 0x10D532 | palqueue_register | DIS | maps.md | registers a palette-animation slot (`$1374,X` ...) |
| $90D582 | 0x10D582 | palqueue_drain | DIS+TRC | maps.md | drains the queue into `$7E6187`; runs once per frame |
| $E0FDE4 | 0x20FDE4 | map_ptr_table | DAT | maps.md | 127 x 4 bytes, `00` + 24-bit map data pointer (data) |

## Sprite composition (bank `$80`)

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $809032 | 0x009032 | sprite_compose | DIS+TRC | sprites.md | reads the metasprite at `[$26]` (count, dataoff, 5-byte chunks) -> OAM shadow `$7EAC42` |
| $80903F | 0x00903F | sprite_compose_reentry | DIS+TRC | sprites.md | re-entry used by the display-list walker: `TRB #1, $07` instead of `$07 = $CE`; shared body `$809049` |
| $80910D | 0x00910D | compose_emit_loop | DIS | sprites.md | per chunk: flags, x:i8, y:i8, block:u16 -> one OAM entry |
| $8091FC | 0x0091FC | compose_variant_16 | DIS | sprites.md | flags bit 0 = 1 path (16x16, slot cache `$97B2`) |
| $8092EA | 0x0092EA | compose_onscreen | DIS | sprites.md | on-screen emit and block allocation (16x16 path) |
| $8096FD | 0x0096FD | sprite_gfx_load_16x16 | DIS | sprites.md | block * 3 -> table `$EE0000`, bank = `(b2 & 0x7F) + 0x5A`, 128 bytes |
| $80A4B4 | 0x00A4B4 | sprite_gfx_load_8x8 | DIS | sprites.md | block * 3 -> table `$D90000`, bank = `(b2 & 0x7F) + 0x52`, 32 bytes |

## Display list

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $809609 | 0x009609 | displist_insert | DIS+TRC | sprites.md | `LDY $1278` new node, bucket via `$50AD,X`, insertion sort on node `+4`, `$1278 += 15` |
| $809684 | 0x009684 | displist_reset | DIS | sprites.md | rebuilds 17 bucket anchors `$50A7-$5127` (8 bytes apart), `$1278 = $512F` |
| $C096BA | 0x0096BA | displist_walk_render | DIS+TRC | sprites.md | DBR = `$7E`, `LDX $5127`; per node `+6 -> $02`, `+8 -> $04`, `+A -> $06`, `+C..+E -> $26..$28`, `JSL $80903F` |
| $CFC662 | 0x0FC662 | displist_build_entity | DIS+TRC | sprites.md | `LDX $4C` entity; entity `+9..+B` -> node `+C..+E` (layer 1), then entity `+6..+8` (layer 2, `$CFC69E`) |

## Animation VM (bank `$D0`)

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $D080D2 | 0x1080D2 | anim_vm_step | DIS+TRC | sprites.md | entity `+0` cursor, `+2` bank, opcode at `[$5D]`, `JSR ($8000,X)`, `DEC` entity `+5` |
| $D08000 | 0x108000 | anim_vm_optable | DIS | sprites.md | 128-word jump table, index `op & 0x7F` (data) |
| $D08371 | 0x108371 | anim_op_wait | DIS+TRC | sprites.md | ops `$01-$1E`: entity `+5` = N frames, cursor persisted |
| $D08381 | 0x108381 | anim_op_wait_computed | DIS | sprites.md | op `$1F`: 2-byte operand, wait computed with the hardware multiplier |
| $D0841D | 0x10841D | anim_op_set_layer2_ptr | DIS+TRC | sprites.md | ops `$22-$2B`: bank = op + `$A9`, 2-byte literal -> entity `+0x06..+0x08` |
| $D08434 | 0x108434 | anim_op_set_layer1_ptr | DIS+TRC | sprites.md | op `$2C`: 3-byte literal -> entity `+0x09..+0x0B` |
| $D08458 | 0x108458 | anim_op_script_reset | DIS | sprites.md | op `$52` (first byte of every script): clears speed, layer pointers and other fields |
| $D0847E | 0x10847E | anim_clear_layer_ptrs | TRC | sprites.md | writer PC that zeroes entity `+0x06..+0x0B` before new pointers are set (inside the op `$52` handler) |
| $D0848A | 0x10848A | anim_op_set_param16 | DIS | sprites.md | op `$4D`: 2 bytes -> entity `+0x16` (speed: walk 4, run 12) |
| $D0849A | 0x10849A | anim_op_dir_clear | DIS | sprites.md | op `$4E`: direction = 0 |
| $D084AC | 0x1084AC | anim_op_flag_check? | DIS | sprites.md | op `$4F`: flag test, no operand |
| $D083B1 | 0x1083B1 | anim_op_loop | DIS+TRC | sprites.md | ops `$53`/`$D3`: tests entity `+0x12`, loop jump at `$D08412` (cursor = entity `+3/+4`) |
| $D085C6 | 0x1085C6 | anim_op_trigger | DIS | sprites.md | op `$5B`: entity `+0x22` indexes `$9085E1`, entity `+0x1A/+0x1C` -> `$0FCC/$0FCE/$0FD0` |
| $D08671 | 0x108671 | anim_op_move | DIS | sprites.md | ops `$42`/`$C2`: signed 1-byte operand, `JSL $8FAD02` |
| $D086AE | 0x1086AE | anim_op_move_stop | DIS | sprites.md | ops `$41`/`$C1`, no operand |
| $D086C8 | 0x1086C8 | anim_op_counter_inc | DIS | sprites.md | ops `$43`/`$C3`: counter + 1 |
| $D08790 | 0x108790 | anim_op_nop | DIS | sprites.md | op `$21`: bare `RTS`, no operand |
| $D087BF | 0x1087BF | anim_op_move_arc? | DIS | sprites.md | op `$47`: 4-byte operand, arc movement |
| $D08815 | 0x108815 | anim_op_collision_check? | DIS | sprites.md | op `$48`: collision check at the layer 2 sprite, no operand |
| $D088C1 | 0x1088C1 | anim_op_dir_effect? | DIS | sprites.md | op `$3F`: 2-byte operand, reads boy direction `$7E4EB7` |
| $D08926 | 0x108926 | anim_op_effect? | DIS | sprites.md | op `$2E`: 1-byte sound/effect index into `$8C8700` |
| $D08AE5 | 0x108AE5 | anim_op_set_loop_mark | DIS | sprites.md | op `$30`: entity `+3/+4` = cursor |
| $D08C0E | 0x108C0E | anim_op_cond_jump | DIS | sprites.md | op `$54`: conditional jump, 2-byte target |
| $8C8700 | 0x0C8700 | anim_effect_table | DIS | sprites.md | table indexed by anim op `$2E` (data) |
| $9085E1 | 0x1085E1 | anim_trigger_table | DIS | sprites.md | table indexed by entity `+0x22` in anim op `$5B` (data) |

## Animation and sprite data

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $C4452E | 0x04452E | boy_action_table | DAT+TRC | sprites.md | 16 bytes per action group: 4 directions x {addr:u16, bank `$C8`, flag}; stand 5, walk 6, run 7, attack standing 9, attack moving 10 |
| $C811CE | 0x0811CE | boy_anim_stand_up | DAT+TRC | sprites.md | starts with `$52`; group 5 |
| $C811DC | 0x0811DC | boy_anim_stand_right | DAT | sprites.md | group 5 |
| $C811EA | 0x0811EA | boy_anim_stand_down | DAT | sprites.md | group 5 |
| $C811F8 | 0x0811F8 | boy_anim_stand_left | DAT | sprites.md | group 5 |
| $C81206 | 0x081206 | boy_anim_walk_up | DAT+TRC | sprites.md | group 6, 6 frames |
| $C81233 | 0x081233 | boy_anim_walk_right | DAT+TRC | sprites.md | group 6, 6 frames |
| $C81260 | 0x081260 | boy_anim_walk_down | DAT+TRC | sprites.md | group 6, 6 frames |
| $C8128D | 0x08128D | boy_anim_walk_left | DAT+TRC | sprites.md | group 6, 6 frames |
| $C812BA | 0x0812BA | boy_anim_run_up | DAT+TRC | sprites.md | group 7, 4 frames |
| $C812DB | 0x0812DB | boy_anim_run_right | DAT | sprites.md | group 7, 4 frames |
| $C812FC | 0x0812FC | boy_anim_run_down | DAT | sprites.md | group 7, 4 frames |
| $C8131D | 0x08131D | boy_anim_run_left | DAT | sprites.md | group 7, 4 frames |
| $C8142E | 0x08142E | boy_anim_attack_move_up | DAT+TRC | sprites.md | group 10, 4 frames |
| $C81459 | 0x081459 | boy_anim_attack_move_right | DAT | sprites.md | group 10, 4 frames |
| $C81484 | 0x081484 | boy_anim_attack_move_down | DAT+TRC | sprites.md | group 10, 4 frames |
| $C814AF | 0x0814AF | boy_anim_attack_move_left | DAT | sprites.md | group 10, 4 frames |
| $CD3F03 | 0x0D3F03 | partyboy_metasprite | DAT+TRC | sprites.md | one-chunk metasprite of the static party/HUD boy |
| $8EB678 | 0x0EB678 | character_table | EXT+DAT | sprites.md | 74-byte character records, palette pointer at `+0x09` (bank `$10`) |
| $D90000 | 0x190000 | spriteblock_table_8x8 | DIS+DAT | sprites.md | 3 bytes per block, see `$80A4B4` (data) |
| $EE0000 | 0x2E0000 | spriteblock_table_16x16 | DIS+DAT | sprites.md | 3 bytes per block, see `$8096FD` (data) |

## Event scripts and text

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $938000 | 0x138000 | scripts_start | EXT+DAT | scripts.md | event script pointer region (Europe) |
| $91D000 | 0x11D000 | text_ptr_table | EXT+DAT | scripts.md | text pointer table, 3 bytes per entry |

## Input and player control

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $808471 | 0x008471 | joypad_read | DIS | sprites.md | waits on `$4212`, reads `$4218`/`$421A`; held -> `$0EC8`, pressed -> `$0104` |
| $CFCDF3 | 0x0FCDF3 | player_move_v_boy? | DIS | sprites.md | reads held `$0EC8` and boy direction `$4EB7`, tests d-pad up `$0800` / down `$0400` |
| $CFCF1C | 0x0FCF1C | player_move_v_dog? | DIS | sprites.md | as above for dog direction `$4F65` |
| $CFD064 | 0x0FD064 | player_move_h? | DIS | sprites.md | reads `$0EC8`, tests `$30` (L/R) |

## NMI, DMA and math primitives (bank `$80`)

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $8082E9 | 0x0082E9 | oam_dma_inline | DIS+TRC | sprites.md | inside the NMI handler: B-bus `$04` (`$2104`), size `$220`, source `$7EAC42` |
| $8085FA | 0x0085FA | cgram_dma | DIS+TRC | maps.md | CGADD `$2121`, B-bus `$22` (CGDATA); direct DMA or enqueue |
| $808650 | 0x008650 | vram_dma | DIS+TRC | maps.md | VMADD `$2116` from DP `$2E`, B-bus `$18`; frequently called |
| $8086C0 | 0x0086C0 | vram_dma_word | DIS+TRC | maps.md | sibling VRAM DMA (B-bus `$18`, DMAP `$01`) with enqueue path |
| $80AEAB | 0x00AEAB | hw_divide_signed | DIS+TRC | | WRDIV `$4204`/`$4206`, RDDIV `$4214`, sign table `$808B25`; frequently called |
| $808B25 | 0x008B25 | hw_divide_sign_table | DIS | | sign table used by `$80AEAB` (data) |

## Provisional hot routines

Found as frequently executed call targets in an execution trace; behavior inferred from a
short disassembly.

| SNES addr | file | name | Src | Doc | Evidence |
|-----------|------|------|-----|-----|----------|
| $8CEE44 | 0x0CEE44 | vm_dispatch_82? | TRC | scripts.md | `LDA [$82]; INC $82; JMP ($8CF442,X)` bytecode interpreter; most frequent call target |
| $80859B | 0x00859B | rng_rotate? | TRC | memory-map.md | 4-byte rotate and add feedback on `$133/$135/$137/$139` |
| $91CA90 | 0x11CA90 | vector_to_target? | TRC | | dx = `$3E - $46`, dy = `$40 - $48`; calls `hw_divide_signed` and `rng_rotate` (aim/seek) |
| $909DED | 0x109DED | angle_normalize? | TRC | | direction/angle quadrant logic on `$50`/`$4C`; runs during NMI |
| $8FA8C5 | 0x0FA8C5 | flags44_update? | TRC | | state flag update on `$44` (`BIT $2040` / `$40`); runs during NMI |

## RAM anchors

Reference only. `apply_names.java` does not apply these rows. Full list with sizes:
[memory-map.md](memory-map.md).

| addr | name | Src | Doc | Evidence |
|------|------|-----|-----|----------|
| $7E0059 | camera_x | TRC | maps.md | camera top-left X in map pixels |
| $7E005B | camera_y | TRC | maps.md | camera top-left Y in map pixels |
| $7E0104 | pressed_buttons | DIS | sprites.md | newly pressed (edge) mask |
| $7E08EE | map_width | DIS+TRC | maps.md | width in cells |
| $7E08F0 | map_height | DIS+TRC | maps.md | height in cells |
| $7E0ADB | cur_map_id | DIS+TRC | maps.md | current map id (byte) |
| $7E0EC8 | held_buttons | DIS | sprites.md | 16-bit held mask; d-pad right `$0100`, left `$0200`, down `$0400`, up `$0800` |
| $7E1278 | displist_alloc | DIS | sprites.md | display-list node allocator |
| $7E2262 | charms_flags_1 | TRC | sprites.md | charm bit flags; bit 1 (`$02`) = Jaguar Ring (enables run, action group 7) |
| $7E4E89 | boy_entity | DIS+TRC | sprites.md | controlled boy entity: `+0` cursor, `+2` bank, `+3/4` loop mark, `+5` wait, `+6..8` layer 2, `+9..B` layer 1, `+0x12` flags, `+0x16` speed |
| $7E4E95 | boy_base_attr | DIS | sprites.md | boy entity `+0x0C`, OAM attribute base (palette) |
| $7E4EA3 | boy_x | TRC | sprites.md | boy entity `+0x1A`, X in map pixels |
| $7E4EA5 | boy_y | TRC | sprites.md | boy entity `+0x1C`, Y in map pixels |
| $7E4EAB | boy_facing | TRC | sprites.md | boy entity `+0x22`, direction * 4 |
| $7E4EB7 | boy_dir | DIS | sprites.md | boy entity `+0x2E`, direction |
| $7E4EF7 | partyboy_metasprite_ptr | DIS+TRC | sprites.md | boy entity `+0x6E`: metasprite of the static party/HUD boy (`$CD3F03`), not the walking boy |
| $7E4F37 | dog_entity | DIS+TRC | sprites.md | dog entity block |
| $7E4F65 | dog_dir | DIS | sprites.md | dog entity `+0x2E`, direction |
| $7E5127 | displist_head | DIS | sprites.md | display-list head (last bucket anchor) |
| $7E6187 | palette_buffer | DIS | maps.md | 512-byte palette buffer transferred to CGRAM |
| $7EAC42 | oam_shadow_buffer | DIS+TRC | sprites.md | source of the NMI OAM DMA (544 bytes) |
| $7F0000 | record_ptr_table | DIS+TRC | maps.md | per-cell record pointers followed by the records |
| $7FA000 | lzss_ring_buffer | DIS | compression.md | 4 KiB LZSS dictionary |
| $7FC300 | arrangement_buffer | DIS+TRC | maps.md | metatile index per cell |
