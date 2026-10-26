# Tools

Emulator scripts (Mesen2, Lua) and disassembler scripts (Ghidra, Java) used to
reverse engineer Secret of Evermore. The repo ships no ROM data. Everything here
runs against your own ROM (Europe/PAL is the primary target) and writes its output
under `assets/` (gitignored).

Run all commands from the repo root. Relative output paths in the scripts are
relative to the working directory.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `MESEN` | shell, `soe/*.py` wrappers | Path to the Mesen2 executable (on macOS `Mesen.app/Contents/MacOS/Mesen`) |
| `SOE_ROM` | shell, `soe/*.py` wrappers | Path to your ROM, `Secret of Evermore (Europe).sfc` |
| `SOE_OUT` | Lua scripts | Output directory, with trailing slash. Must exist. Each script has a default under `assets/dumps/` |
| `SOE_MAPID` | hijack-based scripts | Map id to force (decimal) |
| `SOE_MSS` | save-state scripts in `trace/` | Path to a Mesen2 save state taken in game (your own, not shipped) |
| `GHIDRA_HOME` | `ghdump.sh`, `dump_script.sh`, commands below | Ghidra install directory |
| `JAVA_HOME` | Ghidra | JDK 21 |

Other per-script knobs (`SOE_WAIT`, `SOE_MINFRAME`, `SOE_FRAMES`, `SOE_WINDOW`,
`SOE_HOLD`, `SOE_PEAK`, `SOE_PEAKMAX`, `SOE_OUTFILE`, `SOE_TAG`, `SOE_B1`..`SOE_B3`,
`SOE_PAL`, `SOE_RING`) are documented in the header comment of the script that
reads them.

## Mesen2 Lua scripts

### Headless

The scripts run the ROM until they call `emu.stop`. The command line used by the
Python wrappers (`soe/snescall.py`, `soe/anim.py`, `soe/soundcall.py`) is:

```sh
mkdir -p assets/dumps/snescall
SOE_MAPID=16 SOE_OUT=assets/dumps/snescall/ \
  "$MESEN" --testRunner --noAudio "$SOE_ROM" tools/mesen/map_hijack.lua
```

The output directory must exist before the script runs: Lua `io.open` does not
create directories. The wrappers create theirs. For `trace/` scripts that write to
a subdirectory of `SOE_OUT` (`boy_truth/`, `boy_truth_a/`, `boy_truth_a11/`,
`boy_truth_y/`, `boy_truth_force/`, `boy_truth_ring/`, `cam_edge/`, `cam_clamp/`),
create that subdirectory too.

Notes on the Mesen2 Lua API that the scripts rely on:

- `emu.getState()` raises an error inside a memory callback. Track the current PC
  with a global exec callback and read plain memory with `emu.read`.
- `emu.read(addr, memType)` reads one byte. Memory types used: `snesWorkRam`
  (128 KiB, `$7E0000` is offset 0 and `$7F0000` is offset `0x10000`), `snesVideoRam`,
  `snesCgRam`, `snesSpriteRam` (544 bytes), `snesMemory` (CPU bus),
  `spcRam`, `spcDspRegisters`, `spcRom`.
- `emu.takeScreenshot()` returns the PNG as a string.

### GUI

Scripts that load a save state (`SOE_MSS`) or need manual play are meant to run in
the Mesen2 GUI. Start Mesen2 from a shell so the environment variables are
inherited, load your ROM, then open and run the script from the Script Window:

```sh
SOE_MSS=/path/to/your.mss SOE_OUT=assets/dumps/trace/ "$MESEN"
```

Save-state scripts load the state from an exec callback on `$00823A` (the NMI
vector target), then drive the controller with `emu.setInput` from an
`inputPolled` callback. Most of them write their result file when their last phase
finishes and do not stop the emulator.

### Scripts

All outputs are relative to `SOE_OUT`. The default directory is given per group.

Top level (default `assets/dumps/<name>/`):

| Script | Purpose | Output |
|---|---|---|
| `map_hijack.lua` | Pin `$0ADB` at the map loader entry `$908F68` so the game builds the chosen map through its own code, then dump the result | `wram.bin`, `vram.bin`, `cgram.bin`, `oam.bin`, `shot.png`, `info.txt` in `assets/dumps/snescall/`. Driven by `soe/snescall.py` |
| `anim_capture.lua` | Same hijack, then let the map run and record successive frames | `vram.bin`, `info.txt`, `oam_NNN.bin`, `cgram_NNN.bin`, `shot_NNN.png` in `assets/dumps/anim/`. Driven by `soe/anim.py` |
| `spc_rip.lua` | Same hijack, wait for the area music to reach an envelope peak, dump the APU state | `aram.bin`, `dsp.bin`, `iplrom.bin`, `regs.txt`, `info.txt` in `assets/dumps/sound/`. Driven by `soe/soundcall.py` |

`ppu/` (boot with input mashing, no save state; default `assets/dumps/emulator/`):

| Script | Purpose | Output |
|---|---|---|
| `ppu/drive.lua` | Boot to the intro, dump WRAM/VRAM/CGRAM for the first loaded maps | `mapXX_fN_{wram,vram,cgram}.bin`, `mapXX_fN_state.txt`, `trace.txt` |
| `ppu/grab2.lua` | Minimal dump of the first map that stays stable for 60 frames | `grab_XX_{wram,vram,cgram}.bin`, `grab_XX_info.txt` |
| `ppu/ppudump.lua` | Dump the PPU BG configuration (char base, tilemap base, layers) plus memory | `cap_mapN_ppu.txt`, `cap2_mapN_{wram,vram,cgram}.bin` |
| `ppu/readtrace.lua` | Log ROM reads in the map-data banks in consumption order, plus a matching WRAM dump | `cap_mapN_reads.txt`, `cap_mapN_state.txt`, `cap_mapN_{wram,vram,cgram}.bin` |
| `ppu/trace3.lua` | From the first nonzero write into the `$7FC300` buffer, log work-buffer writes and ROM reads | `trace_c300src.txt` |
| `ppu/tsettrace.lua` | Log decompressor dispatcher calls (`$8C9C22`) and VRAM DMAs, to find the tileset source and codec | `tset_mapN_events.txt`, `tset_mapN_{wram,vram,cgram}.bin` |
| `ppu/tsrc.lua` | Trap the tileset DMA at `$9091C1` and dump the staged tileset | `tsrc_map16_staged.bin`, `tsrc_map16_{vram,wram}.bin`, `tsrc_map16_events.txt` |

`trace/` (routine identification; default `assets/dumps/trace/`). Scripts marked
"boot" pin a map or mash input and need only the ROM. Scripts marked "state" need `SOE_MSS`.

| Script | Mode | Purpose | Output |
|---|---|---|---|
| `trace/hwtrace.lua` | boot | Record call targets (JSL/JSR) in NMI versus main loop, and every `$420B` DMA | `targets_nmi.txt`, `targets_main.txt`, `dma.txt`, `info.txt` |
| `trace/oamwrite_trace.lua` | boot | Log the PCs that write the OAM shadow buffer `$7EAC42` (the sprite composer) | `oamwriters.txt` |
| `trace/compose_caller.lua` | boot, map pin | Find callers of `sprite_compose` (`$809032`) and the entity field holding the metasprite pointer | `compose_caller.txt` |
| `trace/anim07_trace.lua` | boot | Log metasprite pointers at compose entry and the PC reading the bank `$07` animation scripts | `anim07.txt` |
| `trace/anim07_pin56.lua` | boot, map pin | Same as `anim07_trace.lua` with map 56 forced so the Boy is present | `anim07_pin56.txt` |
| `trace/anim_tick.lua` | boot, map pin | Find the writers of the Boy metasprite pointer field `$7E4EF7` (animation tick) | `anim_tick.txt` |
| `trace/boy_locate.lua` | boot, map pin | Record the Boy metasprite pointers and their first bytes (OBJ palette row 6) | `boy_locate.txt` |
| `trace/boy_record.lua` | manual | Log the PCs writing the Boy OAM shadow slots while you walk | `boy_record.txt` |
| `trace/boy_drive.lua` | state, headless | Walk each direction, record the metasprite pointer sequence and the animation-tick writers | `boy_drive.txt` |
| `trace/boy_drive_gui.lua` | state, GUI | GUI variant of `boy_drive.lua` | `boy_drive.txt` |
| `trace/boy_cap.lua` | state, GUI | Drive the Boy on map 56, log pointer sequence per direction with `$4218` and world X | `boy_cap.txt` |
| `trace/boy_cap2.lua` | state, GUI | Record the metasprite the compositor renders for palette row 6, per direction and run | `boy_cap2.txt` |
| `trace/boy_cap3.lua` | state, GUI | Same as `boy_cap2.lua` from a free-roam state | `boy_cap3.txt` |
| `trace/boy_list_trace.lua` | state | Log every compose call per frame with phase, pointer and positions, then aggregate per phase | `boy_list_calls.txt`, `boy_list.txt` |
| `trace/boy_entity_trace.lua` | state | Trap the shared Insert routine `$809609` and log its caller and node fields | `boy_entity.txt` |
| `trace/boy_script_trace.lua` | state | Trace the Boy entity script cursor (`$7E4E89`..`$7E4E8D`) and its writer PCs | `boy_script.txt` |
| `trace/boy_table_trace.lua` | state | Read-trap the Boy action table `$C4452E` with a PC ring buffer | `boy_table.txt` |
| `trace/boy_action_probe.lua` | state | Log action-table reads with map, group and entity state while driving or playing manually | `boy_action_probe.txt` (`SOE_OUTFILE`) |
| `trace/boy_truth.lua` | state, GUI | Ground-truth capture of OAM, CGRAM and VRAM per driven frame, tied to the active metasprite pointer (run on B) | `boy_truth/index.txt`, `oam_NNNN.bin`, `cgram_NNNN.bin`, `vram_NNNN.bin` |
| `trace/boy_truth_a.lua`, `boy_truth_a11.lua`, `boy_truth_y.lua` | state, GUI | Same capture with run on A, A from another state, and Y. Negative results: none of A, B or Y started the run script | `boy_truth_a/`, `boy_truth_a11/`, `boy_truth_y/` |
| `trace/boy_truth_force.lua` | state, GUI | Same capture, forcing the Boy script cursor into the run script (bank `$C8`) once per phase | `boy_truth_force/` |
| `trace/boy_truth_ring.lua` | state, GUI | Same capture with the Jaguar Ring flag bytes `$7E2261`..`$7E2263` forced | `boy_truth_ring/` |
| `trace/boy_truth_ring_bisect.lua` | state | Bisect which of those bytes unlocks run (`SOE_B1`..`SOE_B3`, `SOE_TAG`) | `boy_truth_ring/bisect_<tag>.txt` |
| `trace/cam_clamp.lua` | state, GUI | Pin the entity position on map 56, log the camera (`$7E0059`/`$7E005B`) to find the clamp | `cam_clamp/cam_clamp.txt`, `clamp_h400_X_Y.png` |
| `trace/cam_edge.lua` | state, GUI | Hold directions at the map edge, log BG1 scroll, save screenshots and WRAM | `cam_edge/cam_edge.txt`, `shot_NNNN.png`, `wram_NNNN.bin` |

`boy_cap.lua`, `boy_cap2.lua`, `boy_cap3.lua`, `boy_drive.lua` and `boy_drive_gui.lua`
are successive versions of the same experiment. `boy_truth_a.lua`, `boy_truth_a11.lua`
and `boy_truth_y.lua` differ from `boy_truth.lua` only in the dash button and
save state.

## Ghidra

### Install the 65816 processor module

Ghidra ships no 65816 processor. A community SLEIGH module is used.

1. Clone `joshleaves/ghidra-snes` (MIT, maintained fork of `achan1989/ghidra-65816`)
   into `third_party/ghidra-snes`. It defines the language `65816:LE:24:snes`: one
   24-bit `bus` address space that maps the whole SNES address space.
2. Copy its language files (`658xx.sinc`, `658xx_memaccess*.sinc`, `65816.slaspec`,
   `65816-snes.pspec`, `65816.cspec`, `65816.ldefs`, `65816.opinion`) to
   `$GHIDRA_HOME/Ghidra/Processors/65816/data/languages/` and add an empty
   `Module.manifest` in the `65816` processor directory.
3. Compile the SLA with Ghidra's own sleigh compiler (JDK 21):
   `$GHIDRA_HOME/support/sleigh $GHIDRA_HOME/Ghidra/Processors/65816/data/languages/65816.slaspec`.
   It produces `65816.sla`. Two "NOP constructor" warnings are harmless.

Tested with Ghidra 12.1.3. Ghidra 12 dropped Jython, so all scripts are Java.

### Import the ROM

The ROM is imported as a raw binary at base `0xC00000`. `scripts/SetupSnes.java`
then builds the HiROM layout:

- primary ROM block, file `0x000000-0x2FFFFF` at `$C00000-$EFFFFF`;
- byte-mapped mirror `$808000-$BFFFFF` onto `$C08000-$FFFFFF`, so bank `$80-$BF`
  references resolve (`$8C9DDD` maps to `$CC9DDD`, file offset `0x0C9DDD`);
- uninitialized WRAM `$7E0000-$7FFFFF`;
- the reset vector as entry point, disassembled.

Command (import options as documented in Ghidra's `support/analyzeHeadlessREADME.md`):

```sh
mkdir -p build/ghidra
"$GHIDRA_HOME/support/analyzeHeadless" build/ghidra/proj_snes SoE_SNES \
  -import "/path/to/Secret of Evermore (Europe).sfc" \
  -loader BinaryLoader -loader-baseAddr 0xC00000 \
  -processor 65816:LE:24:snes \
  -scriptPath tools/ghidra/scripts -preScript SetupSnes.java
```

`ghdump.sh` expects project `build/ghidra/proj_snes`, program `SoE_SNES`, and the
imported file name `Secret of Evermore (Europe).sfc`. `dump_script.sh` uses the same
layout with project `build/ghidra/proj_script` and program `SoE_Script`, a second
import kept separate for the script interpreter work.

### Dump code

`ghdump.sh` runs `scripts/DumpRange.java`: a raw listing for each window plus the
decompiled function. Addresses and lengths are hex SNES addresses (default length
`0x120`).

```sh
tools/ghidra/ghdump.sh build/ghidra/dump.txt 8C9C22:200 909000
```

### Apply labels

`apply_names.java` reads the table in `docs/labels.md` (rows of the form
`| $8C9C22 | 0x0C9C22 | name | ...`). For each address it renames an existing
function, else creates a function if the bytes are already disassembled, else adds a
plain label. A trailing `?` in a name (provisional) becomes the suffix `_q`.

```sh
"$GHIDRA_HOME/support/analyzeHeadless" build/ghidra/proj_snes SoE_SNES \
  -process "Secret of Evermore (Europe).sfc" -noanalysis \
  -scriptPath tools/ghidra -postScript apply_names.java docs/labels.md
```

The path argument is optional and defaults to `docs/labels.md`.

### Ghidra scripts

| Script | Purpose | Output |
|---|---|---|
| `scripts/SetupSnes.java` | Pre-script: HiROM layout, WRAM block, reset vector | Program memory map |
| `scripts/DumpRange.java` | Disassemble and decompile given `addr[:len]` windows (used by `ghdump.sh`, `dump_script.sh`) | Text file (first argument) |
| `scripts/DumpRoutine.java` | Disassemble and decompile the map decompressor at `$8C9C22` and its handlers (hard-coded seed addresses) | Text file (first argument, default `routine_dump.txt`) |
| `scripts/ListFunctions.java` | List all function entry points as `<image addr> <file offset> <name>` | Text file (first argument, default `functions.txt`) |
| `scripts/DumpAll.java` | Decompile every function into chunked `.c` files with an `index.txt` manifest | Directory (first argument, default `assets/dumps/ghidra/decompiled`), optional chunk size as second argument |
| `apply_names.java` | Apply `docs/labels.md` as function names and labels | Program symbols |
| `ghdump.sh` | Wrapper around `DumpRange.java` for `proj_snes` | Text file, also printed |
| `dump_script.sh` | Same for `proj_script` | Text file, also printed |
