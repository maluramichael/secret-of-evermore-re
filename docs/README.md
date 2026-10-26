# Documentation

Technical documentation for the Europe/PAL ROM of Secret of Evermore. Offsets are
Europe file offsets unless marked otherwise; see [rom.md](rom.md) for address
conventions.

- [rom.md](rom.md): ROM identity, HiROM address conversion, Europe vs US offsets, bank layout, adding a region.
- [memory-map.md](memory-map.md): WRAM, direct page and hardware addresses used by the engine.
- [compression.md](compression.md): the decompressor dispatcher and its codecs (LZSS, record pointer codec, tile and sprite codecs).
- [maps.md](maps.md): map loader, map data format, arrangement, records, tilesets, palettes, collision.
- [sprites.md](sprites.md): sprite composition, metasprites, sprite blocks, animation VM and scripts, OAM.
- [text.md](text.md): fonts, plain text tables, story dialogue codec, map names.
- [scripts.md](scripts.md): event script VM, script tables, opcodes.
- [audio.md](audio.md): sound engine, BRR samples, play-song routine, SPC ripping.
- [emulator-techniques.md](emulator-techniques.md): extracting assets by running the real game in Mesen2 (map loader hijack, memory dumps, animation capture, SPC rip, tracing).
- [methodology.md](methodology.md): how the formats were found, corrected assumptions, verification practice.
- [labels.md](labels.md): named routines and data labels.
