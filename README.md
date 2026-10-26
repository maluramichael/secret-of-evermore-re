# Secret of Evermore: reverse engineering

Notes, labels and extraction tools for **Secret of Evermore** (Squaresoft, SNES, 1995).

This is not a disassembly that rebuilds the ROM. It documents how the game stores its
maps, graphics, sprites, text, scripts and sound, names the routines that handle them,
and ships Python code that decodes those formats from your own ROM. The primary target
is the **Europe/PAL** release; US offsets are noted where known.

No game data is included. Everything under `assets/` is generated locally from a ROM
you supply and is ignored by git.

## What is covered

| Area | State | Docs |
|---|---|---|
| ROM layout, regions, data tables | verified for Europe | [rom.md](docs/rom.md) |
| Compression (LZSS, record pointer codec, 16-mode tile codec, sprite codec) | verified against emulator dumps | [compression.md](docs/compression.md) |
| Maps: loader, header, arrangement, per-cell records, BG1/BG2, collision, palettes | all 127 maps render via the emulator path; pure ROM decode verified on sample maps | [maps.md](docs/maps.md) |
| Sprites: animation VM, metasprites, OAM, the player character | walk/run/attack frames rebuilt from ROM, pixel-checked against OAM captures | [sprites.md](docs/sprites.md) |
| Text: fonts, item/menu text, story dialogue codec | verified | [text.md](docs/text.md) |
| Event script VM | instruction lengths match a reference dumper on all 61018 instructions; some opcode semantics open | [scripts.md](docs/scripts.md) |
| Audio: BRR samples, SPC capture | partial | [audio.md](docs/audio.md) |
| RAM map | mixed, every row marked verified or external | [memory-map.md](docs/memory-map.md) |
| Routine and data labels (Ghidra-ready) | 114 entries | [labels.md](docs/labels.md) |

Two methods carry most of the work, both described in detail:
[emulator-techniques.md](docs/emulator-techniques.md) (run the real game code in Mesen2
and read the result) and [methodology.md](docs/methodology.md) (how formats were found,
including the wrong assumptions that had to be corrected).

## Requirements

- Your own Secret of Evermore ROM. Tested with the Europe release, headerless,
  SHA1 `ae17166919fdfdf26cc5771f83cfd19eaf71806c`.
- Python 3.11+ and Pillow. [uv](https://docs.astral.sh/uv/) is the easiest way to run it.
- Optional: [Mesen2](https://github.com/SourMesen/Mesen2) for the emulator-driven
  extractors and trace scripts, [Ghidra](https://ghidra-sre.org/) with a 65816 module
  for the disassembly, [soerominfo](https://github.com/millanzarreta/soerominfo) for the
  item and stat tables.

## Usage

```sh
# put "Secret of Evermore (Europe).sfc" in the repo root, or set SOE_ROM
uv run python -m soe                 # extract all domains to assets/
uv run python -m soe text fonts      # selected domains only
uv run python -m soe.mapdata 56      # collision grid and triggers for map 56
uv run python -m soe.script          # walk the event scripts of all maps (self-check)
uv run python tools/romdecode.py "Secret of Evermore (Europe).sfc"   # header check
```

Emulator-driven extractors (map renders, animation and SPC capture) need the path to the
Mesen2 binary in `MESEN`. See [tools/README.md](tools/README.md) for the Lua scripts,
environment variables and the Ghidra setup.

A small pygame viewer shows the extracted maps, the player sprite and the original font:

```sh
uv run --extra viewer python -m viewer
```

## Repository layout

```
docs/      format documentation, RAM map, labels
soe/       Python library: ROM access, codecs, extractors (python -m soe)
viewer/    pygame map and sprite viewer for the extracted assets
tools/     Mesen2 Lua scripts, Ghidra scripts, verification helpers
```

## How this was made

Most of the reverse engineering, code and documentation was done by Claude (Anthropic)
working as several parallel agents, with me setting direction and checking results.
Every format claim was checked against emulator memory dumps or rendered images before
it went into the docs. The process, including what went wrong, is written up in two
blog posts:

- [I cracked open Secret of Evermore and let the game render for me](https://malura.de/en/blog/i-cracked-open-secret-of-evermore-and-let-the-game-render-for-me)
  ([Deutsch](https://malura.de/blog/secret-of-evermore-aufgemacht-und-das-spiel-selbst-rendern-lassen))
- [Secret of Evermore: The Boy Now Comes Entirely From the ROM](https://malura.de/en/blog/secret-of-evermore-the-boy-now-comes-entirely-from-the-rom)
  ([Deutsch](https://malura.de/blog/secret-of-evermore-der-junge-aus-dem-rom))

## Credits

This work stands on earlier community research:

- [SoETilesViewer](https://github.com/black-sliver/SoETilesViewer), [SoEScriptDumper](https://github.com/black-sliver/SoEScriptDumper) and [evermizer](https://github.com/black-sliver/evermizer) by black-sliver: tile and sprite codecs, script opcode table, map and script names
- [SecretOfEverhack](https://github.com/Gemini-Loboto3/SecretOfEverhack) by Gemini-Loboto3: dialogue codec
- [soerominfo](https://github.com/millanzarreta/soerominfo) by millanzarreta: Europe data table offsets
- [everscript](https://github.com/r-bin/everscript) by r-bin: script opcode semantics
- [Data Crystal ROM and RAM maps](https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/ROM_map) (US)
- [SRAM document](http://games.technoplaza.net/soesrame/sram-doc.txt) by John David Ratliff, [RAMsetta Stone](https://www.romhacking.net/documents/831/) by Phonymike
- [Mesen2](https://github.com/SourMesen/Mesen2) by Sour, [ghidra-snes](https://github.com/joshleaves/ghidra-snes) by joshleaves

More Secret of Evermore resources: [awesome-secret-of-evermore](https://github.com/maluramichael/awesome-secret-of-evermore).

## Legal

Secret of Evermore is © 1995 Square Co., Ltd. This project is not affiliated with or
endorsed by Square Enix. It contains no ROM data, graphics, text or audio from the game.
Do not open issues or pull requests that include game data or links to ROMs.

Code and documentation are released under the [MIT License](LICENSE).
