# Methodology

How the formats in these docs were found, which assumptions turned out wrong, and
how results were verified. The wrong turns are kept on purpose: several of them
are traps that other SNES projects are likely to hit too.

## Approach

Three techniques carried most of the work.

1. **Let the game do it.** Run the real ROM in an emulator, make the game load the
   asset, read the result from emulated memory. This gave complete maps,
   animations and music before any codec was understood. See
   [emulator-techniques.md](emulator-techniques.md).
2. **Known plaintext.** An emulator dump of WRAM/VRAM/CGRAM is the decompressed
   truth. Find the compressed input in the ROM (by tracing the reads of the
   decompression call), then build a decoder until it reproduces the dump byte for
   byte. The map arrangement codec, the placement codec and the tileset codec were
   all closed this way.
3. **Cross-check against independent work.** Community tools for the US ROM
   (SoETilesViewer, SoEScriptDumper, SecretOfEverhack, soerominfo) and documentation
   of related Square games served as references. A reimplementation counts as
   correct only when it matches such a reference or the emulator exactly.

## Static analysis setup

- Ghidra has no built-in 65816 processor. The community SLEIGH module
  [ghidra-snes](https://github.com/joshleaves/ghidra-snes) (a maintained fork of
  [ghidra-65816](https://github.com/achan1989/ghidra-65816)) was installed as a
  processor module and its `.slaspec` compiled with Ghidra's sleigh tool. It models
  the 24-bit SNES bus as one address space.
- The ROM is loaded as a raw binary at base `0xC00000`. A pre-script
  (`tools/ghidra/scripts/SetupSnes.java`) adds the HiROM layout: the byte-mapped
  mirror `$80:8000-$BF:FFFF` -> `$C0:8000-$FF:FFFF` so that FastROM references
  resolve, an uninitialized WRAM block at `$7E0000-$7FFFFF`, and the reset vector.
- Recent Ghidra versions dropped Jython, so the scripts are Java (or PyGhidra).
  `tools/ghidra/ghdump.sh` dumps address ranges headless for quick inspection.
  The install location comes from `GHIDRA_HOME`.
- For quick checks a small standalone disassembler that tracks `REP`/`SEP` (the M
  and X flags decide operand widths) was often faster than Ghidra.
- Byte scans are cheap and effective: search for `JSL` (`22 lo hi bank`) to a
  candidate routine, for long-address operands of a known table, or for a pointer
  value as a literal. The decompressor entry `$8C9C22` was found because
  `JSL $8C9C22` occurs 11 times.

Static disassembly of 65816 code has a known weakness: without the M/X flag state,
instruction boundaries are ambiguous, and data decodes as plausible code. Several
leads were byte-scan false positives (see below). Confirm a suspected routine with
an exec trace before building on it.

## Dynamic analysis

- Work backwards from the effect: a write trap on the OAM shadow buffer, a DMA log
  on `$420B`, or a VRAM-side breakpoint finds the code that produces a graphic.
- Trap a routine entry and log its arguments (the decompressor's direct-page
  source/destination pointers) to get every call with its input and output.
- Log ROM reads in order during one load to get the compressed input exactly as
  the codec consumes it.
- Measure instead of guessing: frame counts of animation steps, which flag bit
  changes a behavior (bisection over candidate RAM bits found the Jaguar Ring flag,
  `$7E2262` bit 1), whether a field is written at all during a window.
- Some states need a human-made savestate plus scripted input, because the attract
  sequence does not exercise them (the attract-mode Boy never animates; zero writes
  to his frame field in 60 frames).

## Wrong assumptions that were corrected

### Maps

1. **Header pointer.** The bytes at map header `+2` looked like a graphics bank
   pointer. They are the map width and height. Byte `+4` is a value written to the
   PPU main screen register (TM), almost always `0x16`/`0x17`, which made it look
   like a bank number. Verified: `(+2, +3)` equals the dimensions in WRAM for maps
   16, 24 and 97.
2. **Arrangement as tilemap.** The decompressed arrangement at `$7FC300` was first
   rendered as raw PPU tilemap words and gave colored noise. It is a metatile index
   per cell, the running sum of signed 16-bit deltas from the LZSS output.
3. **Graphics set list.** A loop feeding `$90D532` looked like a tileset selection.
   It is a palette animation queue (drained by `$90D582` into `$7E6187`).
4. **Opcode 7.** The second codec of the decompressor dispatcher was assumed to be
   the tileset codec. It is the per-cell record pointer codec (a 16-bit word LZ
   with prediction from the cells above and to the left).
5. **Tileset codec.** After raw scans and single-blob attempts failed, the tileset
   turned out to use the 16-mode tile codec from SoETilesViewer's `tile.h`, which
   was already ported. The blocks are scattered across many banks and addressed
   individually, which is why contiguous scans found nothing. A whole-ROM scan
   (decompress at every offset, compare with the VRAM dump) matched 239 of 256
   metatiles of map 16 byte for byte. The lead came from research into related
   Square titles (Secret of Mana shares the engine family).
6. **Palette source.** Character/sprite palettes (bank `$10`) were used for map
   tiles and produced a green false-color image. Map BG palettes come from a
   per-map table in bank `$1D` (byte-exact against CGRAM).
7. **One layer.** Rendering only BG1 gave a dark, incomplete image. SoE maps use
   Mode 1 with two BG layers: BG2 for floors and walls, BG1 for foreground. The
   8-byte per-cell record holds word 0 = BG1, word 1 = BG2. Compositing BG2 then
   BG1 gives the clean result.
8. **Record words as quadrants.** The four record words were first read as four
   8x8 quadrants. On outdoor maps this produced an orange checkerboard. Words 2 and
   3 are an attribute/collision field and padding, not graphics; each of words 0
   and 1 is a 16x16 large tile.

### Text

- US codec offsets applied to the Europe ROM land in tile data; the Europe text
  engine is restructured, not shifted. A monotonic 3-byte table that looked like a
  text pointer table decoded to binary under every interpretation and is most
  likely event script data. Details: [text.md](text.md).
- The main font starts one byte later in Europe than the US documentation says.

### Scripts

- The 2-byte value at the end of a map trigger was read as a direct pointer into a
  behavior VM in bank `$CA`. A reported 55 of 56 "clean" decodes were coincidental
  byte patterns. The value is a script ID (an index into a pointer table at the
  start of the script bank), and the scripts run on a different, byte-oriented
  event VM. Verified by matching all 61018 instruction lengths of the reference
  disassembler SoEScriptDumper on the Europe ROM. Details:
  [scripts.md](scripts.md).

### Audio

- Decoding BRR from every end flag produced 3 ms fragments. Starting only at sample
  addresses referenced by the music data produced whole instruments.
- Forcing a song ID uploads its data but does not start it; the per-frame NMI
  sound handler has to run. Apparent successes were the title song still playing,
  exposed by comparing the current-song variable with the requested ID. Loading the
  area instead lets the game start its song. Details: [audio.md](audio.md).

### Sprites

- The player sprite was first cut from a fixed 16x32 grid of raw 4bpp tiles. The
  real sprite is a variable-size metasprite of up to 7 chunks with individual x/y
  offsets; the grid cut off legs on wide running poses.
- A matcher that searched the ROM for verbatim 4bpp action poses (run, attack,
  cast, hurt) was tested with a positive control: it reproduced the standing pose
  with a score of 0.975, while action poses only reached 0.44 to 0.79 and looked
  like tile salad. Conclusion: action poses are composed at run time, not stored
  as finished images. This negative result redirected the work to the metasprite
  and animation script engine.
- Animation pointers in bank `$07` (`$457E`, `$458E`, `$459E`) were a misreading.
  The scripts are in bank `$C8`; `$C8457E` is a script of another actor.
- A trap on the sprite composer entry `$809032` missed most actors. The display
  list walker enters at `$80903F`, a second entry into the same routine.
- Two "callers" found by byte scan were operands of `REP`/`SEP`, and two others sat
  in a bank that does not decode as code under any M/X combination.
- The first composer call per frame with the player's palette was a second Boy
  instance at a fixed screen position (metasprite `$CD3F03`), not the controlled
  player. The controlled Boy uses metasprites in bank `$CB`.
- An address used as a list head (`$5127`) has no store anywhere in the ROM. It is
  a fixed anchor, not a variable.
- Walking the display list from a `startFrame` callback found it already reset.
  The list has to be read at the composer entry.

Details for all sprite items: [sprites.md](sprites.md).

## Verification discipline

- **Byte-exact or not done.** A decoder is accepted when its output equals the
  emulator dump byte for byte, or equals a reference implementation instruction for
  instruction. Partial matches are reported with numbers (for example 239/256
  metatiles, 51/225 cells of a leading run), not rounded up.
- **Two independent paths.** Maps are produced both by the emulator hijack and by
  pure ROM decoding. Agreement between the two is the strongest check available.
- **Look at the picture.** Several renders were reported as clean while the image
  was still dark, noisy or incomplete. Every rendered PNG was inspected before it
  was accepted. Statistics such as `nonblack_frac` and `missing_tile_quadrants`
  catch some failures but pass on wrong-but-colorful images.
- **Compare against the screenshot.** The emulator's live frame is ground truth for
  the visible window; reconstructions of maps and sprite layers are compared with
  it. The player animation atlas is compared pixel by pixel against OAM+VRAM
  reconstructions of captured frames (`tools/verify_boy_atlas.py`); stand and walk
  frames score 1.000, and the few mismatches are listed as open.
- **Positive controls.** A search that finds nothing proves little. Run the same
  search on a case where the answer is known first.
- **Hard assertions in extractors.** Extractors assert known values (item names in
  the plain text block, known words in decoded dialogue, map 16 dimensions in the
  map caller self-test). A wrong offset fails loudly.
- **Diagnostics instead of garbage.** When a decoder cannot be verified (Europe
  dialogue), it writes a diagnostic report rather than plausible-looking output.
- **Measured vs read.** Animation timings were measured in the emulator and
  matched to the wait values in the animation script bytes (for example 8, 8, 7, 8,
  8, 6 frames per walk step), which confirmed both the script format and the
  timing.
- **Label provenance.** Docs keep "verified" separate from "US map, unverified" and
  "provisional". Emulator API field names were checked live by dumping the state
  table, not taken from secondary sources.

## Related work used as leads

- Data Crystal ROM and RAM maps (US): https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/ROM_map
- SoETilesViewer: https://github.com/black-sliver/SoETilesViewer
- SoEScriptDumper: https://github.com/black-sliver/SoEScriptDumper
- SecretOfEverhack: https://github.com/Gemini-Loboto3/SecretOfEverhack
- soerominfo: https://github.com/millanzarreta/soerominfo
- Super Famicom Development Wiki, Seiken Densetsu 2 (Square codec and event VM
  family): https://wiki.superfamicom.org/seiken-densetsu-2
- FF4 technical documentation (structure and Square engine comparison):
  https://ff4-documentation.readthedocs.io/
- everything8215 FF6 disassembly: https://github.com/everything8215/ff6
- General SNES reverse engineering: DiztinGUIsh (https://github.com/DizTools/DiztinGUIsh),
  bsnes-plus (https://github.com/devinacker/bsnes-plus), SNESdev wiki
  (https://snes.nesdev.org/wiki/)
