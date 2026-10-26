# Text: fonts, plain text, dialogue codec, map names

Secret of Evermore stores text in three different ways:

1. Item, weapon, armor, alchemy and monster names, their descriptions, and menu
   text: plain null-terminated ASCII.
2. Map names: a separate table of plain ASCII records.
3. Story dialogue: a token-compressed stream with a character table, a digram
   table and two dictionaries.

Glyphs come from 1bpp fonts. File offsets below are for the Europe ROM unless
marked US. See [rom.md](rom.md) for the address conventions.

## Fonts

| Font | Europe offset | Format | Status |
|---|---|---|---|
| Main font | `0x40003-0x40C02` | 1bpp, 8 bytes per 8x8 glyph, MSB = leftmost pixel | verified |
| Small font | `0x40C84-0x41883` | 1bpp, same layout | US offset, used unchanged |
| Text window pattern | `0x41924-0x419B3` | | US offset, used unchanged |
| Text window border | `0x419B4-0x41E83` | | US offset, used unchanged |

Data Crystal lists the main font at `0x40002` (US). In the Europe ROM the glyphs
only line up at `0x40003`: starting one byte early shifts every row of every glyph
and the sheet renders as garbage. The correct start was found by an alignment
search (render the sheet at each candidate start and keep the one where the glyph
rows are coherent).

Decoder: `Rom.decode_1bpp` in `soe/rom.py`. `soe/fonts.py` renders both fonts to
PNG sheets, 16 glyphs per row.

## Plain text block

Europe `0x50700-0x52260` holds the names and descriptions of items, weapons,
armor, alchemy formulas and monsters, plus menu and UI strings, as plain
null-terminated ASCII. No dictionary is involved.

`soe/text.py` extracts every printable run of at least 2 characters that ends in
`0x00`, keyed by file offset. As a hard check it asserts that known item names
(for example `Bone Crusher`) appear in the output. A wrong offset fails loudly
instead of producing an empty or garbled file.

## Map names

Europe `0x2D8000` (US `0x2C8000`). Records follow each other directly:

```
[flag] [0x2E] [name bytes] [0x00]
```

- `flag` is `'M'` (`0x4D`) or `'m'` (`0x6D`). Its meaning is not known.
- `0x2E` is a literal `'.'`.
- The table ends at the first record that does not match this signature or has an
  empty name.

The list index is the map name index. How map IDs map to name indices is
documented in [maps.md](maps.md).

## Story dialogue codec

The codec is known from two independent sources that agree:

- SecretOfEverhack (Gemini-Loboto3): `source/common/Encoding.cpp`
  (`BuildDictionaries`, `ExpandString`, `DecodeString`) and `hack/dec.s`, a 65816
  disassembly of the original decompressor (`Message_parse`).
- SoETilesViewer (black-sliver): `text.h`.

`soe/dialogue.py` is a faithful Python port and documents the format in its
module docstring. Decoding runs in two stages.

### Stage A: tokens to byte stream

Each input byte is a token. The top two bits select the token class:

| Token | Meaning | Output | Consumes |
|---|---|---|---|
| `$00-$3F` | Single character via the 64-byte character table `tbl_eng[code]`. The table is a frequency-ordered permutation, not ASCII. If the looked-up value is `0x00`, the string ends. | 1 byte | 0 |
| `$40-$7F` | Literal copy: the next `code & 0x3F` bytes are copied unchanged. Used for names, numbers, anything the tables do not cover. | n bytes | n |
| `$80-$BF` | Digram (DTE): `dte[code - 0x80]` is a pair of characters. | 2 bytes | 0 |
| `$C0 xx` | Dictionary 1: the following byte `xx` (0..255) selects a null-terminated word `dic1[xx]`. | variable | 1 |
| `$C1-$FF` | Dictionary 2: `dic2[code - 0xC1]` (63 entries). | variable | 0 |

Dictionary words are stored as plain ASCII and are copied into the stream
unchanged.

Dictionary construction:

- `dic1`: 256 entries. `dic1[i]` is the C string at
  `dic1_data + u16(dic1_ptr + 2*i)`.
- `dic2`: 63 entries. `dic2[i-1]` is the C string at
  `dic2_data + u16(dic2_ptr + 2*i)` for `i = 1..63`. Slot 0 of the offset table is
  skipped, so token `$C1` maps to slot 1. SoETilesViewer expresses the same thing
  as index `(b << 1) & 0x7E`.

### Stage B: byte stream to text

The expanded stream contains ASCII plus control bytes:

| Byte | Meaning |
|---|---|
| `0x00` | end of string |
| `0x0A` | line break |
| `0x0B` | vertical tab (exact effect not traced) |
| `0x5F` (`_`) | ellipsis glyph |
| other `< 0x80` | character |
| `0x80` | starts a raw block; the bytes up to the next `0x80`, `0x81` or `0x82` are parameters (Encoding.cpp renders this as `<S ...>`; SoETilesViewer treats paired `0x80` around a duration byte as a pause) |
| `0x81` | Boy's name |
| `0x82` | Dog's name |
| `0x83`, `0x84` | third and fourth name slot |
| `0x8B` | choice prompt |
| `0xA1` | count value |
| `0xA2` | item name |
| other `>= 0x80` | unknown control code, `soe.dialogue` prints it as `{$XX}` |

Encoding.cpp also renders `<` and `>` as special glyphs. `soe.dialogue` passes
them through as characters.

### Text pointer table

US: `0x11D000`, 3002 entries of 3 bytes. For an entry `[b0, b1, b2]`:

```
p          = b0 | (b1 & 0x7F) << 8 | (b1 >> 7) << 16 | (b2 & 0x7F) << 17
compressed = b2 & 0x80
```

`p` is a LoROM-style packed address. In the US ROM it is directly the file offset
of the string. The equivalent form in SoETilesViewer is
`hirom = 0xC00000 + (p & 0x7FFF) + ((p & 0x7F8000) << 1)` on the raw 24-bit value.
Entries without the compressed flag are plain ASCII up to `0x00`; the codec handles
both, because plain ASCII passes through stage A unchanged except for control
codes.

Event scripts refer to dialogue by a word offset into this table, so the text ID
is `word / 3`. See [scripts.md](scripts.md).

### Codec table offsets

US, byte-exact from Encoding.cpp, verified by decoding real dialogue:

| Table | US offset | Size |
|---|---|---|
| `ptr_table` | `0x11D000` | 3002 x 3 bytes |
| `dte` | `0x11F32E` | 64 pairs, 128 bytes |
| `tbl_eng` | `0x11F3AE` | 64 bytes |
| `dic2_ptr` | `0x11F3EC` | u16 offsets |
| `dic1_ptr` | `0x11F46C` | 256 x u16 offsets |
| `dic2_data` | `0x11F66C` | ASCII words |
| `dic1_data` | `0x11F7D5` | ASCII words |

The six codec tables are contiguous in US bank `$91`. Relative layout: `dte` +0,
`tbl_eng` +`0x80`, `dic2_ptr` +`0xBE`, `dic1_ptr` +`0x13E`, `dic2_data` +`0x33E`,
`dic1_data` +`0x4A7`.

Europe: not located. The Europe text engine is restructured, not shifted. At
`0x11D000` and `0x11F3AE` the Europe ROM holds tile data. `EUROPE_OFFSETS` in
`soe/dialogue.py` is left as `None` on purpose.

### Current pipeline

`soe.dialogue.extract` looks for `Secret of Evermore (USA).sfc` next to the Europe
ROM and decodes the dialogue from it. It only writes `dialogue.json` if a hard
check passes (a set of known words must appear in the output). Without a US ROM,
or if the check fails, it writes a diagnostic report instead of garbled text.

The Europe event scripts reference dialogue by text IDs that resolve to
contextually correct lines in the US table (all text opcodes resolve; individual
lines spot-checked against their scenes). Byte identity of the Europe dialogue with the US dialogue
has not been verified.

`python -m soe.dialogue` runs a self-test of the codec on a synthetic table set
(no ROM needed).

### Europe search: what was tried

These attempts did not produce the Europe codec tables. They are listed so they
are not repeated.

- US offsets applied to the Europe ROM: tile data at both the pointer table and the
  character table offsets.
- A fixed US-to-Europe shift: the known data shifts are bank-dependent
  (`+0x640`, `+0xA666`, `+1`), so no single shift carries over.
- A 3-byte table at `0x128000` with about 3080 monotonically increasing entries
  looked like a text pointer table. Its targets decode to binary data, both as
  relative and as absolute offsets, and a quadgram language-model hill climb
  against known US sentences did not converge. It is most likely event script
  pointer data (`0x128000` is the US script table start `$928000` as a file
  offset).
- A region near `0x12A950` that looked like a character table is part of the same
  script data.
- Plain-text search for dictionary words found almost nothing outside the plain
  text block and map names, which confirms the dialogue is compressed.
- Europe `0x16140-0x16660` contains plain dialogue vocabulary (short words with a
  trailing space), duplicated in pairs and interleaved with binary data. It may be
  dictionary data or inline script text. Without the matching character, digram
  and pointer tables it is not usable.
- Disassembling the Europe ROM at the US decompressor location (`0xCCDF8`) shows a
  VRAM upload routine (writes `$2118`). The Europe text routine is elsewhere and
  reads its table addresses from direct-page pointers set at run time, so the
  addresses are not visible as immediates.
- Index alignment: Europe entries 1..11 are empty where US entries 1..11 have
  text, so the entry order differs.

Two approaches are expected to work:

1. Byte-pattern search: the US codec block (about 1.7 KiB of English tables at
   `0x11F32E`) should exist nearly unchanged in the Europe ROM.
2. Dynamic trace: break on reads of the character table while a text box opens,
   then read the table base addresses from the direct-page pointers.

Once the six offsets and the pointer table are known, filling `EUROPE_OFFSETS` is
enough; the decoder needs no change.

## References

- SecretOfEverhack: https://github.com/Gemini-Loboto3/SecretOfEverhack
- SoETilesViewer (`text.h`): https://github.com/black-sliver/SoETilesViewer
- Data Crystal ROM map: https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/ROM_map
