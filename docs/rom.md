# ROM identity, address mapping, region offsets

This repo targets the English Europe/PAL release of Secret of Evermore. Most public
documentation (Data Crystal, SoETilesViewer, SoEScriptDumper) targets the US/NTSC
release. Many data tables sit at different file offsets in the two releases, so
every US offset must be re-checked before use. This file collects the identity of
the supported ROM, the HiROM address conversion, and the verified offsets.

## ROM identity

### Europe (primary, verified)

| Field | Value |
|---|---|
| File | `Secret of Evermore (Europe).sfc` |
| Size | 3,145,728 bytes (3 MiB, 24 Mbit), no 512-byte copier header |
| MD5 | `1c02824bdd165bacb52597551c3c87c5` |
| SHA1 | `ae17166919fdfdf26cc5771f83cfd19eaf71806c` |
| Internal title | `SECRET OF EVERMORE` |
| Mapping | HiROM + FastROM, map mode byte `0x31` |
| Country | `0x02` (Europe/PAL) |
| Version | 1.0 |
| Game code | `AEOP` |
| SRAM | 8 KiB (64 Kbit) |
| Checksum | `0xF4E3`, matches the computed value (clean dump) |

The internal header sits at file offset `0xFFC0` (SNES `$00FFC0`, mirrored at
`$C0FFC0`). `tools/romdecode.py <rom>` reads both candidate header locations
(LoROM `0x7FC0`, HiROM `0xFFC0`), picks the one with a valid checksum, and prints
title, map mode, sizes, version, checksum, interrupt vectors, and padding banks.
The checksum follows the SNES convention for non-power-of-two sizes: the first
2 MiB are summed once, the remaining 1 MiB is mirrored up to 2 MiB (summed twice).

### USA (secondary)

| Field | Value |
|---|---|
| SHA1 | `79e7738630fff5699217ef58ecc421bc8fcbcd89` |
| CRC32 | `A5C0045E` |
| Size | 3 MiB, HiROM |

The US ROM is only used for the story dialogue (see [text.md](text.md)). All other
extraction runs on the Europe ROM.

`soe/rom.py` identifies the ROM by SHA1 of the header-stripped data. A 512-byte
copier header (file size `% 1024 == 512`) is removed automatically.

## HiROM address conversion

SoE is HiROM. Every 64 KiB bank of the file maps to a full SNES bank.

| SNES range | File offset | Notes |
|---|---|---|
| `$C0:0000-$EF:FFFF` | `(bank - $C0) << 16 \| addr` | Full banks, the canonical data view |
| `$40:0000-$6F:FFFF` | `(bank - $40) << 16 \| addr` | Same data, slow-ROM mirror |
| `$80:8000-$BF:FFFF` | `(bank & $3F) << 16 \| addr` | Upper halves only. FastROM mirror, where the code runs |
| `$00:8000-$3F:FFFF` | `(bank & $3F) << 16 \| addr` | Upper halves only, slow-ROM mirror |
| `$7E:0000-$7F:FFFF` | none | 128 KiB WRAM |

For any ROM address in those windows the conversion collapses to:

```
file = snes & 0x3FFFFF
```

Examples: the map LZSS dispatcher `$8C9C22` is file `0x0C9C22`; the sprite block
table `$EE0000` is file `0x2E0000`; the song table read as `$819903` is file
`0x019903`, the same bytes as `$C19903`.

Going the other way, use `0xC00000 | file` for data references and
`0x800000 | file` for code in the upper half of a bank (FastROM code executes from
`$80-$BF`, so disassemblies and traces show `$8x`/`$9x` addresses).

Conventions in the wild differ, which is a common source of confusion:

- Data Crystal lists plain file offsets ("PC offsets") for an unheadered US ROM.
- SoETilesViewer and SoEScriptDumper write SNES addresses (`0x91D000` means file
  `0x11D000`).
- evermizer lists some offsets relative to `0x800000`.
- A headered ROM adds `0x200` to every file offset.

Some ROM data is stored with LoROM-style packed 24-bit pointers even though the
cartridge is HiROM. The text pointer table and the event script table both use
`hirom = 0xC00000 + (p & 0x7FFF) + ((p & 0x7F8000) << 1)`. See
[text.md](text.md) and [scripts.md](scripts.md).

## Why US documentation has different offsets

The European English release is not a byte-shifted copy of the US ROM:

- Data tables in banks that also hold text moved because the translated or
  re-edited strings have different lengths.
- The shifts are not uniform. Weapons moved by `+0x640`, ingredients by
  `+0xA666`, level-up tables by `+0x395`, the main font by `+1`, map names by a
  whole bank. A single global shift does not work.
- The story text engine was restructured. At the US text pointer table offset
  (`0x11D000`) the Europe ROM holds tile data. The Europe text codec tables have
  not been located yet.
- Code moved as well. The US location of the text decompressor (`0xCCDF8`) holds a
  VRAM upload routine in the Europe ROM.

Some areas did not move: the NPC/monster table, the audio banks, the song table,
and the sprite block pointer table at `$EE0000`.

## Verified data tables, Europe vs US

File offsets. "Verified" means checked against the Europe ROM bytes (pointer stride,
known strings, CSV round trip, or emulator dumps).

| Data | US offset | Europe offset | Shift | Format, verification |
|---|---|---|---|---|
| NPC/monster records | `0xEC536` | `0xEC536` | 0 | up to `0xEDF84`, same in all regions |
| Weapon pointers | `0x43876` | `0x43EB6` | `+0x640` | 2-byte pointers, 36-byte records (pointer stride `0x24` verified) |
| Armor pointers | `0x43896` | `0x43ED6` | `+0x640` | 2-byte pointers, 10-byte records (stride `0x0A` verified) |
| Ingredients | `0x45B10` | `0x50176` | `+0xA666` | up to `0x501A1` |
| Alchemy | `0x45C3B` | `0x502A1` | `+0xA666` | up to `0x502E6` |
| Call bead spells | `0x45EF7` | `0x5055D` | `+0xA666` | up to `0x5057C` |
| Boy level-up | `0xC8BD0` | `0xC8F65` | `+0x395` | 99 entries, 3 bytes each |
| Dog level-up | `0xC8CFC` | `0xC9091` | `+0x395` | 99 entries, 3 bytes each |
| Main font (1bpp) | `0x40002` | `0x40003` | `+1` | found by glyph alignment search, see [text.md](text.md) |
| Item/menu plain text | n/a | `0x50700-0x52260` | | null-terminated ASCII, asserted by known strings |
| Map names | `0x2C8000` | `0x2D8000` | `+0x10000` | records `[M/m] '.' name\0` |
| Text pointer table | `0x11D000` | not located | | 3002 entries in US |
| Event script table start | `$928000` | `$938000` | | from SoEScriptDumper, verified by instruction-length match |
| Song pointer table | `0x19903` | `0x19903` | 0 | verified live in the emulator, see [audio.md](audio.md) |
| Music data | `0xAA7BE-0xB8EF1` | same | 0 | |
| Sprite block table 16x16 | `$EE0000` | `$EE0000` | 0 | verified by disassembly of `$8096FD` |

The authoritative Europe anchor for the data tables is
[soerominfo](https://github.com/millanzarreta/soerominfo) (`soerominfo.c`, plus
its pre-extracted CSVs for six releases: USA, Europe, Germany, France, Spain,
Spain Rev 2). `soe/data.py` converts its Europe CSVs to JSON and cross-checks the
weapon pointer count against the ROM.

Values taken from the US map and used unchanged on the Europe ROM, without
separate verification: small font `0x40C84-0x41883`, text window pattern
`0x41924-0x419B3`, text window border `0x419B4-0x41E83`.

## Bank layout overview

Europe file offsets. Entries marked "US" come from the Data Crystal US ROM map and
have not been confirmed at the same offset in Europe.

| File range | SNES | Contents | Status |
|---|---|---|---|
| `0x000000-0x00FFFF` | `$C0` / `$80` | Engine core: NMI handler `$00823A`, joypad read `$808471`, OAM DMA `$8082E9`, sprite composer `$809032`. Header at `0xFFC0` | verified |
| `0x019903` | `$C1:9903` | Song pointer table, 3-byte pointers into bank `$8A` | verified |
| `0x01A75C-0x01CFFB` | `$C1` | BRR samples | US, audio scan covers `0x18000-0x1FFFF` |
| `0x040003-0x041E83` | `$C4` | Fonts, text window tiles | verified (main font) |
| `0x043EB6-0x043F25` | `$C4` | Weapon/armor pointer tables | verified |
| `0x048000-0x04FA71` | `$C4` | BRR samples | US |
| `0x050176-0x05057C` | `$C5` | Ingredients, alchemy, call beads | verified |
| `0x050700-0x052260` | `$C5` | Plain ASCII names, descriptions, menu text | verified |
| `0x058000-0x06FFFF` | `$C5-$C6` | BRR samples | US |
| `0x078000-0x0A9FFF` | `$C7-$CA` | BRR samples | US |
| `0x0AA7BE-0x0B8EF1` | `$CA-$CB` | Music sequences and instrument references | verified |
| `0x0C8000-0x0C9FFF` | `$8C` | Play-song `$8C8581`, decompressor dispatcher `$8C9C22`, LZSS `$8C9C5E`, opcode 7 `$8C9EFA` | verified |
| `0x0C8F65-0x0C91B9` | `$CC` | Boy and dog level-up tables | verified |
| `0x0D3F03` | `$CD` | Actor metasprites (party Boy stand frame) | verified |
| `0x0EC536-0x0EDF84` | `$CE` | NPC/monster records | verified |
| `0x0FC5DD` | `$8F` | Boy/dog render callers | verified |
| `0x108000-0x10FFFF` | `$90` / `$D0` | Engine code: map loader `$908F68`, palette queue `$90D532/$90D582`. Data Crystal (US) lists behavior-script, spell and camera code from `0x108000` | verified (loader) |
| `0x10AD10` | `$D0` | 8 Boy palette variants, 32 bytes each | verified |
| `0x11D000-0x11F8xx` | `$D1` | US: text pointer table and text codec tables. Europe: tile data | US only |
| `0x138000` | `$93` | Event script table start (Europe) | verified |
| `0x190000` | `$D9` | 8x8 sprite block pointer table | verified |
| `0x1DCC63`, `0x1DE6C3` | `$DD` | Map BG palettes (maps 16, 97), see [maps.md](maps.md) | verified |
| `0x1D8000-0x2EFFFF` | `$DD-$EE` | Map data (all 127 map pointers resolve here). Data Crystal (US) gives `0x1C8000-0x2DCEE5` | verified |
| `0x20FDE4` | `$E0:FDE4`, read as `$A0:FDE4` | Map data pointer table, 4 bytes per map | verified |
| `0x2D8000` | `$ED` | Map names | verified |
| `0x2E0000` | `$EE` | 16x16 sprite block pointer table | verified |

Graphics are compressed and scattered: map tileset blocks were found in banks
`0x05`, `0x06`, `0x07`, `0x12`, `0x1C`, `0x2F` and others. See
[compression.md](compression.md), [maps.md](maps.md), [sprites.md](sprites.md).

## Supporting another region

`soe/rom.py` is the single place for region handling:

- `KNOWN_ROMS` maps the SHA1 of the header-stripped ROM to a region key.
- `OFFSETS[region]` holds the file offsets per data table (`span(key)` returns
  `(start, end)`).
- An unknown SHA1 falls back to the Europe layout. The US entry exists only so
  that `soe.dialogue` can recognize the US ROM. `OFFSETS` has no US table yet.

To add a region:

1. Add its SHA1 to `KNOWN_ROMS`.
2. Add an `OFFSETS` entry. Start from soerominfo for the data tables (it covers
   six releases) and from the US Data Crystal map for everything else.
3. Verify each table, do not trust a shift. Useful checks: pointer stride (weapons
   `0x24`, armor `0x0A`), the plain-text assertion in `soe/text.py` (known item
   names must appear), font glyph alignment (render the sheet), map name record
   signature (`'M'` or `'m'` followed by `'.'`).
4. Re-check hard-coded constants outside `rom.py`: `soe/audio.py` (song table,
   sample banks), `soe/dialogue.py` (`US_OFFSETS`, `EUROPE_OFFSETS`), and the
   code addresses used by the emulator scripts (`$908F68`, `$0ADB`, `$0E4D`, see
   [emulator-techniques.md](emulator-techniques.md)). Code addresses were verified
   only on the Europe ROM. Translated releases (German, French, Spanish) are
   expected to differ in code layout as well.

## References

- Data Crystal ROM map (US): https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/ROM_map
- Data Crystal RAM map: https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/RAM_map
- soerominfo (Europe offsets, CSVs): https://github.com/millanzarreta/soerominfo
- SoETilesViewer (US formats): https://github.com/black-sliver/SoETilesViewer
- SoEScriptDumper (script table addresses per region): https://github.com/black-sliver/SoEScriptDumper
- TCRF page (prototype, debug menu): https://tcrf.net/Secret_of_Evermore
