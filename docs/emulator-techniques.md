# Emulator techniques: let the real game do the work

Most of the hard parts of an SNES game (compressed graphics, map assembly, sound
sequencing) are implemented by the game's own code. Instead of reimplementing
every codec before seeing a single result, this project runs the real ROM in an
emulator, makes the game perform the work, and reads the finished result out of
emulated memory. The emulator is a build-time tool: it runs once per asset, on the
user's own ROM, and its output is plain files.

This produced all 127 Secret of Evermore maps as full images, per-frame sprite and
palette animation, and playable `.spc` music. The same dumps later served as
known plaintext for reimplementing the codecs in Python (see
[methodology.md](methodology.md)), so both paths check each other.

Nothing here is specific to SoE except the addresses. The recipe in
[Applying this to another game](#applying-this-to-another-game) lists what to find
in a new ROM.

## Tooling

- [Mesen2](https://github.com/SourMesen/Mesen2): accurate SNES emulator with a
  debugger and a Lua API. Lua API reference: https://www.mesen.ca/docs/apireference.html,
  machine-readable source:
  https://github.com/SourMesen/Mesen2/blob/master/UI/Debugger/Documentation/LuaDocumentation.json
- Headless mode: `Mesen --testRunner --noAudio <rom> <script.lua>` runs at full
  speed without a window until the script calls `emu.stop(exitCode)`. The exit code
  becomes the process exit code.
- Environment variables used by this repo: `MESEN` (path to the Mesen2
  executable), `SOE_ROM` (ROM path), `SOE_OUT` (output directory, trailing slash),
  plus per-script parameters such as `SOE_MAPID`, `SOE_WAIT`, `SOE_FRAMES`.
- The Python modules in `soe/` start Mesen as a subprocess, pass parameters
  through the environment, and parse the dump files the Lua script writes.

| Lua script | Python driver | Purpose |
|---|---|---|
| `tools/mesen/map_hijack.lua` | `soe/snescall.py` | load any map, dump WRAM/VRAM/CGRAM/OAM |
| `tools/mesen/anim_capture.lua` | `soe/anim.py` | record OAM/CGRAM/screenshots over N frames |
| `tools/mesen/spc_rip.lua` | `soe/soundcall.py` | load an area, dump the APU as `.spc` |
| `tools/mesen/ppu/*.lua` | | early map tracers: PPU config, decompressor and DMA traps, ROM read-order traces |
| `tools/mesen/trace/*.lua` | | routine identification, sprite/Boy traces, savestate-driven probes |

Generated dumps go to `assets/dumps/<name>/` (not tracked).

## Step 1: find a "pending level" variable and its first reader

Many SNES games keep the ID of the current or next room in a RAM variable, and
the loader reads it near its start. If the script overwrites that variable at the
right moment, the game builds the chosen room through its normal code path, with
the correct register widths, banks, and setup. No calling convention has to be
reverse engineered.

For SoE:

- WRAM `$7E0ADB` holds the current map ID (listed in the Data Crystal RAM map,
  confirmed by watching it change on map transitions). `$7E0ADC` is the high byte.
- The bank `$90` map loader starts at `$908F68` with `LDA $0ADB` (bytes
  `AD DB 0A`). It was located by disassembling the map load path in Ghidra and
  confirmed by those bytes.

General ways to find the pair:

- Check community RAM maps first (Data Crystal, TASVideos game resources).
- Watch candidate RAM cells across room transitions in the debugger's memory
  viewer.
- Search the ROM for absolute loads of the candidate (`AD lo hi`, `AF lo hi 7E`).
- Put a read breakpoint on the variable and look at the call stack during a
  transition.

## Step 2: hijack the loader with an exec callback

`tools/mesen/map_hijack.lua`, simplified:

```lua
local WR = emu.memType.snesWorkRam

local function onExec()                       -- runs before the instruction at $908F68
  if frame < MINFRAME then return end         -- ignore early boot-time hits
  emu.write(0x0ADB, TARGET & 0xFF, WR)        -- pin the map id ...
  emu.write(0x0ADC, 0, WR)                    -- ... before LDA $0ADB reads it
  if not loadedAt then loadedAt = frame end
end
emu.addMemoryCallback(onExec, emu.callbackType.exec, 0x908F68, 0x908F68)
```

- An exec callback fires when the CPU fetches the instruction at that address,
  before it executes. A write to `$0ADB` from inside the callback is therefore seen
  by the `LDA`.
- The value is pinned on every loader entry. If the intro or attract sequence
  triggers another load, the same map is rebuilt and the decoded structures stay
  consistent.
- From power-on, the attract sequence calls the loader by itself (first hit near
  frame 389). `MINFRAME` (default 300) skips earlier hits. The script also presses
  Start/A/B in a pattern to get past the logos.
- After `SOE_WAIT` frames (default 180) the map is fully built: arrangement
  decompressed to `$7FC300`, per-cell records to `$7F0000`, tileset DMA'd to VRAM
  `$4000`, BG palette in CGRAM.

Alternatives that were considered:

- Synthetic call via `emu.setState`: setting PC/K/A/X/Y/SP/D/DBR/PS works (field
  names verified live: `cpu.a`, `cpu.x`, `cpu.y`, `cpu.sp`, `cpu.pc`, `cpu.k`,
  `cpu.dbr`, `cpu.d`, `cpu.ps`, `cpu.emulationMode`), and a trampoline
  (`JSL target ; BRA self`, or `STP`) in free RAM gives a clean return point. The
  SoE loader normally runs in the middle of a warp and depends on surrounding
  setup, so hijacking the natural entry was more robust.
- One savestate per map: works for any game but needs manual play to every map.

## Step 3: dump memory

Mesen2 memory types used by this project:

| Memory | `emu.memType` | Size |
|---|---|---|
| WRAM (`$7E0000-$7FFFFF`) | `snesWorkRam` | 128 KiB, `$7E0000` -> offset `0x00000`, `$7F0000` -> `0x10000` |
| VRAM | `snesVideoRam` | 64 KiB |
| CGRAM (palette) | `snesCgRam` | 512 bytes, 256 BGR555 colors |
| OAM | `snesSpriteRam` | 544 bytes (512 + 32 high table) |
| CPU bus (ROM, I/O registers) | `snesMemory` | 24-bit address space |
| Audio RAM | `spcRam` | 64 KiB |
| DSP registers | `spcDspRegisters` | 128 bytes |
| IPL ROM | `spcRom` | 64 bytes |

There is no bulk read. Dumps loop over `emu.read(i, memType)` and buffer the
characters before writing, which is fast enough for a one-time 128 KiB dump:

```lua
local function dumpMem(mt, start, len, path)
  local h, b = io.open(path, "wb"), {}
  for i = 0, len - 1 do
    b[#b + 1] = string.char(emu.read(start + i, mt))
    if #b >= 8192 then h:write(table.concat(b)); b = {} end
  end
  if #b > 0 then h:write(table.concat(b)) end
  h:close()
end
```

Also captured per dump:

- `emu.takeScreenshot()` returns the current 256x224 frame as a PNG string. It is
  the ground truth for checking a reconstruction.
- `emu.getState().ppu` holds the PPU configuration: `bgMode`, main/sub screen
  layers, and per layer `layers[i].chrAddress`, `tilemapAddress`, `largeTiles`,
  scroll values; for sprites `oamBaseAddress`, `oamAddressOffset`, `oamMode`.
  VRAM addresses in the state are word addresses (multiply by 2 for bytes).

The map dump writes `wram.bin`, `vram.bin`, `cgram.bin`, `oam.bin`, `shot.png`
and `info.txt` (map ID, dimensions from `$7E08EE`/`$7E08F0`, PPU layer config).

## Step 4: render from the dump

The SNES BG tilemap in VRAM only covers the visible scroll window. A full SoE map
is larger, so `soe.snescall.render_map` renders from the loader's decoded WRAM
structures and the VRAM tileset instead:

```
for each 16x16 cell (cx, cy) in width x height:
    ptr = u16 at $7F0000 + 2*cell            # byte offset of this cell's record
    rec = 4 words at $7F0000 + ptr           # BG1 tile, BG2 tile, attributes, 0
    draw BG2 (word 1), then BG1 (word 0) on top, skipping color index 0
```

Each word is a 16x16 "large tile" in SNES tilemap format (`vhopppcc cccccccc`).
It expands to the 8x8 tiles `n`, `n+1`, `n+16`, `n+17` at char base `$4000`,
4bpp, with the word's palette row and flips (a horizontal flip also swaps the left
and right quadrants). Colors come from CGRAM. Details of the record format are in
[maps.md](maps.md).

The renderer reports `missing_tile_quadrants` (tile indices beyond the VRAM dump)
and `nonblack_frac`. All 127 maps render with zero missing quadrants, including
the largest (127x96 and 114x82 cells), because the loader stages the full tileset
at once. A single capture per map is enough.

Usage:

```python
from soe import snescall
img = snescall.render_map(16)     # also writes the PNG
print(img.stats)
```

`python -m soe.snescall selftest` renders map 16 and asserts its grid size and
coverage.

## Animation capture

`tools/mesen/anim_capture.lua` and `soe/anim.py` use the same hijack, but after
the map has settled the script stops pressing buttons and records `SOE_FRAMES`
consecutive frames (default 64):

- `oam_NNN.bin`: OAM, the source of sprite motion.
- `cgram_NNN.bin`: CGRAM, the source of palette animation.
- `shot_NNN.png`: the live frame, ground truth.
- once: `vram.bin` (OBJ tile sheet) and the OBJ base/offset/size from the PPU state.

OAM decoding (`soe.anim._parse_oam`): 4 bytes per sprite (X low, Y, tile low,
attributes `vhoopppN`), plus 2 bits per sprite in the 32-byte high table (X bit 8,
size select). OBJ tile `n` is at `objBase + n*32` for `n < 256`, and at
`objBase + objOffset + (n-256)*32` above. Drawing sprites from index 127 down to 0
puts lower indices on top. The per-frame sprite layers are written as an APNG.

Water, torches and glows in SoE do not swap tiles. They rotate a few palette
entries. The per-frame palette queue (`$90D582`) rewrites the palette buffer at
`$7E6187`, which is uploaded to CGRAM. Diffing the CGRAM snapshots finds the
cycling entries without decoding the queue.

Limit: the sprites present are whatever the engine has live during the attract
sequence on the pinned map. For specific actor animations (for example the
player walking in each direction), drive the game from a savestate, see below.

## SPC ripping

The same hijack loads an area so that the game starts its music, then the script
dumps audio RAM, DSP registers, IPL ROM and SPC700 registers into a standard
`.spc` file. Forcing a song ID directly does not work in SoE, because the song only
starts when the NMI sound handler runs in the game's normal flow. Full details,
including verification by rendering the `.spc` with libgme, are in
[audio.md](audio.md).

## Savestates and input

Some states cannot be reached from power-on in a reasonable time (a specific
room, the player in control). Those scripts start from a savestate made by hand in
the Mesen2 GUI.

- `emu.loadSavestate(data)` only works inside a callback. The scripts read the
  `.mss` file with `io.open` and load it from an exec callback on the NMI handler
  (`$00823A` in SoE), which fires once per frame:

  ```lua
  local function onLoad()
    if loaded then return end
    local f = io.open(os.getenv("SOE_MSS"), "rb"); local d = f:read("*a"); f:close()
    pcall(function() emu.loadSavestate(d) end)
    loaded = true
  end
  emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
  ```

- Inject input from an `inputPolled` event callback with `emu.setInput`. Values
  apply until the next poll, so set them every frame. Mesen2's documented
  signature is `emu.setInput(input, port)`; some scripts here use the older
  `(port, input)` order. When input matters, confirm it arrives by reading the
  auto-joypad register `$4218` through `snesMemory`
  (`tools/mesen/trace/inp_test.lua`).
- A phase table (button set plus frame count per phase: stand, walk up/right/
  down/left, run in each direction) drives the player through every animation
  while the script records OAM, CGRAM and the actor's current metasprite pointer
  (`tools/mesen/trace/boy_truth*.lua`).
- Writing RAM every frame is a quick way to probe behavior. Writing the controlled
  character's position (`$7E4EA3`/`$7E4EA5`) teleports it, and the camera
  (`$7E0059`/`$7E005B`) follows and clamps at the map edges
  (`tools/mesen/trace/cam_clamp.lua`).

## Hardware tracing

The Lua API also works as a programmable tracer. Patterns used here:

**Track the current PC.** Inside memory callbacks `emu.getState()` raises an
error. To know which instruction caused a read or write, register an exec callback
over the whole address space that stores the address, and read that variable in
the read/write callback:

```lua
local curPC = -1
emu.addMemoryCallback(function(a) curPC = a end, emu.callbackType.exec, 0x000000, 0xFFFFFF)
emu.addMemoryCallback(function(a, v) writers[curPC] = (writers[curPC] or 0) + 1 end,
                      emu.callbackType.write, 0x7EAC42, 0x7EAC42 + 0x21F)
```

This found the code that fills the OAM shadow buffer `$7EAC42`
(`trace/oamwrite_trace.lua`) and the routine that writes an actor's animation
frame field (`trace/boy_drive_gui.lua`). The whole-space exec callback is slow, so
add it only for the recording window.

**List called subroutines.** In the same exec callback, look at the previous
instruction's opcode. If it was `JSL` (`$22`), `JSR` (`$20`) or `JSR (abs,X)`
(`$FC`), the current address is a subroutine entry. Split the counts by whether
the NMI handler ran this frame (exec callback on the NMI entry, reset at
`startFrame`) to separate vblank code from game logic (`trace/hwtrace.lua`).

**Log every DMA.** A write callback on `$420B` (MDMAEN) reads the channel
registers `$43x0-$43x6` for each enabled channel. The B-bus target tells the
destination (`$04` OAM, `$22` CGRAM, `$18` VRAM, `$40` APU). The A-bus source is
the shadow buffer or decompression output that feeds the PPU. `trace/hwtrace.lua`
also logs `$2116/$2117` (VRAM address), but those PPU registers are write-only on
hardware, so the value read through the CPU bus is not reliable; use
`emu.getState().ppu` or trap the code that writes them instead.

**Trap a known routine and read its arguments.** SoE's decompressor dispatcher
`$8C9C22` takes source and destination in direct page (`$36/$38` source offset and
bank, `$3A/$3C` destination). An exec callback at the entry logs every
decompression call with its opcode (first source byte) and size
(`ppu/tsettrace.lua`). An exec callback on the inline tileset DMA `$9091C1` links
the VRAM tileset to its WRAM staging area (`ppu/tsrc.lua`).

**Read-order traces for codec work.** A read callback over the ROM banks that hold
map data logs every ROM byte the CPU consumes, in order, into a ring buffer, and
dumps it together with WRAM when the map is stable (`ppu/readtrace.lua`). A
variant starts logging at the first non-zero write into the output buffer, so the
zero-fill is skipped (`ppu/trace3.lua`). The result is the exact compressed input
and the exact decompressed output of one call: a known-plaintext pair.

**Detect "stable".** Without a hijack, wait until the map ID and dimensions in WRAM
are valid and unchanged for N frames before dumping (`ppu/grab2.lua`,
`ppu/drive.lua`).

## Mesen2 notes

Confirmed on the version used for this project. The API is not guaranteed stable
across versions; dump `emu.getState()` once to check field names.

- `emu.getState()` errors inside memory callbacks. Use it in event callbacks
  (`startFrame`, `endFrame`) only. Inside memory callbacks use `emu.read`/`emu.write`.
- `emu.loadSavestate` only works inside a callback.
- Memory reads are single-address; buffer the output.
- Read with `snesMemory` (CPU bus) to see ROM through the SNES address map and to
  read readable I/O registers such as `$4218` or the DMA channel registers. Use the
  dedicated memory types for VRAM/CGRAM/OAM/WRAM. Mesen also offers a `snesDebug`
  type documented as side-effect free, which this project did not need.
- `emu.getState()` returns SPC700 registers as flat keys (`spc.pc` etc.).
- In headless mode always end with `emu.stop(code)` and add a frame limit with a
  `TIMEOUT` marker file, so a missed hook does not hang the batch.

## Applying this to another game

1. Identify the ROM and mapping (LoROM/HiROM) so ROM addresses can be translated.
2. Find the room/level ID variable and the first instruction of the loader that
   reads it (Step 1).
3. Write an exec-callback hijack that pins the ID (Step 2). Ignore hits during
   boot; let the game reach a point where it loads rooms by itself (attract mode,
   or a savestate just before a door).
4. Wait until the room is stable, then dump WRAM, VRAM, CGRAM, OAM, a screenshot
   and the PPU state (Step 3).
5. Render from the dump. If the room is larger than one screen, find the decoded
   full-room structures in WRAM rather than relying on the BG tilemap window. Check
   the render against the screenshot.
6. For animation, keep the emulator running after the load and dump OAM and CGRAM
   every frame.
7. For music, check whether loading a room starts its song; if so, dump the APU
   after the song is audibly playing and write a `.spc`.
8. Use the dumps as known plaintext to reimplement codecs, if a standalone decoder
   is needed.

## References

- Mesen2: https://github.com/SourMesen/Mesen2, API docs https://www.mesen.ca/docs/apireference.html
- Precedent for emulator-driven extraction: Matt Greer, "Discerning the Super
  Metroid Map with BizHawk and Lua",
  https://www.mattgreer.dev/blog/discerning-the-super-metroid-map-with-bizhawk-and-lua/
- TASVideos Lua scripting: https://tasvideos.org/LuaScripting
- SNES DMA registers: https://snes.nesdev.org/wiki/DMA_registers
- SNES PPU memory access: https://snes.nesdev.org/wiki/Reading_and_writing_PPU_memory
- SNES sprites/OAM: https://wiki.superfamicom.org/snes-sprites
- 65816 subroutine conventions: https://ersanio.gitbook.io/assembly-for-the-snes/the-basics/subroutine
- Data Crystal RAM map: https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/RAM_map
