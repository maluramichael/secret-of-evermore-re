# Audio: sound engine, BRR samples, SPC ripping

Secret of Evermore uses Square's SPC700 sound driver, commonly called AKAO after
Square's sound programmer Minoru Akao. The community uses the name for the whole
family of Square SNES sound drivers, which went through several revisions. Which
revision SoE uses has not been determined. The Secret of Mana sequence format
(documented on the Super Famicom Development Wiki) is the closest public reference
for a sequence opcode comparison, but it has not been checked against SoE.

Two extraction paths exist:

- `soe/audio.py`: static extraction of instrument samples (BRR) from the ROM to WAV.
- `soe/soundcall.py` + `tools/mesen/spc_rip.lua`: let the game play each area's
  song in the emulator and snapshot the sound chip into standard `.spc` files.

All offsets are Europe file offsets. The audio areas did not move between the US
and Europe releases.

## ROM layout

| Data | File offset | SNES | Status |
|---|---|---|---|
| Song pointer table | `0x19903` | `$C1:9903`, read as `$81:9903` | verified |
| Music sequence and instrument data | `0xAA7BE-0xB8EF1` | `$CA-$CB` | verified |
| BRR sample bank 1 | `0x1A75C-0x1CFFB` | `$C1` | Data Crystal (US); `soe.audio` scans `0x18000-0x1FFFF` |
| BRR sample bank 2 | `0x48000-0x4FA71` | `$C4` | Data Crystal (US) |
| BRR sample bank 3 | `0x58000-0x6FFFF` | `$C5-$C6` | Data Crystal (US) |
| BRR sample bank 4 | `0x78000-0xA9FFF` | `$C7-$CA` | Data Crystal (US) |

### Song pointer table

3 bytes per entry, a 24-bit SNES pointer to the song's sequence data in bank `$8A`.
Entry 0 points to `$8AA874` (file `0xAA874`), inside the music data region. 59
consecutive entries point into bank `$8A`. Data Crystal gives the range as
`0x19903-0x199D7`, which would hold 70 entries, and the area rip has observed song
IDs above 58. Entries past 58 therefore probably exist and point elsewhere. Not
verified.

The music data region also contains 3-byte pointers to the BRR start of every
instrument a song uses. `soe.audio` relies on these references.

## Play-song routine

Traced and disassembled on the Europe ROM. The general play-song routine is at
`$8C8581` (file `0x0C8581`):

```
$8C8581  REP #$30
$8C8586  TAX                 ; new song id arrives in A
$8C8587  BEQ exit            ; id 0: do nothing
$8C8589  AND #$00FF
$8C858C  CMP $0E4D           ; already playing? skip
$8C858F  BEQ exit
$8C8591  STA $0E4D           ; current song := id
$8C8595  LDA $0E4D           ; index = id * 3
$8C8598  ASL A
$8C859A  ADC $0E4D
$8C859D  TAX
$8C859E  LDA $819903,X       ; pointer from the song table
$8C85A3  LDA $819905,X
...      JSL $8C8527 (APU command $0E), JSR $835A, JSL $8C8527 (command $02)
$8C85E6  RTL
```

- WRAM `$7E0E4D` holds the current song ID.
- Song ID 0 means "no music / stop". The routine returns immediately for it.
- `$8C8527` sends a command to the APU. The routine sends `$0E`, runs the upload
  (`JSR $835A`), then sends `$02`. The exact meaning of each command has not been
  traced.
- A second, hard-coded path at `$8C8320` plays song 0 or 1 directly
  (`LDA $819903`). The attract sequence uses it.

The game selects music by area: loading a map starts that area's song through its
normal flow.

## BRR samples (static extraction)

BRR is the S-DSP sample format: 9-byte blocks, one header byte
(`shift << 4 | filter << 2 | loop << 1 | end`) plus 8 data bytes holding 16 signed
4-bit samples. Filters 1 to 3 predict from the previous two output samples.
`Rom.decode_brr` in `soe/rom.py` implements the decoder with the canonical S-DSP
predictor formulas (as in BRRtools `brr.c`), including the 15-bit wrap.

The first approach decoded from every end flag in the sample banks. It produced
thousands of 3 ms fragments: an end flag tells where a sample stops, not where it
starts.

The current approach (`soe.audio.extract`) only decodes sample starts that the
music data actually references:

1. Scan the music data region for 3-byte values that, converted HiROM to file
   (`((snes >> 16) & 0x3F) << 16 | (snes & 0xFFFF)`), land inside a sample bank.
2. Keep a candidate only if its first block uses filter 0 (a fresh sample must not
   depend on previous output), it runs block by block to an end flag inside its
   bank, and it is at least 16 blocks long.
3. Sort by start and drop overlapping candidates. Real samples are disjoint; on
   overlap the candidate with more references wins.
4. Drop near-silent results (RMS below 20).

Output: `inst_XXXX.wav` (mono, 16-bit, 32 kHz) and `samples.json` with ROM offset,
block count, duration, RMS, an autocorrelation score (rough tonality), the loop
flag of the end block, and the reference count.

Limit: exact loop points are not stored next to the sample. They live in the S-DSP
sample directory (DIR) that the driver builds in audio RAM per song. `loop_point`
is therefore `null`. Reading the DIR from an SPC dump would give exact loop
offsets. The 32 kHz rate is the base rate at pitch `0x1000`; real pitch is per note.

## SPC ripping

A `.spc` file is a snapshot of the complete sound subsystem: 64 KiB audio RAM, 128
DSP registers, the 64-byte IPL ROM, and the SPC700 CPU registers. Any SPC player
resumes from that state and plays the song exactly as the console does, without
knowing the sequence format.

### Method

`tools/mesen/spc_rip.lua`, driven by `soe/soundcall.py`:

1. Reuse the map loader hijack (see
   [emulator-techniques.md](emulator-techniques.md)): an exec callback on
   `$908F68` writes the target map ID into `$0ADB`/`$0ADC` before the loader reads
   it. The game loads that area and starts its music through its own code.
2. Let the area run for `SOE_WAIT` frames (default 240).
3. Wait for a loud moment: sum the envelope registers (ENVX, DSP register
   `voice * 0x10 + 8`) of all 8 voices and dump only when the sum reaches
   `SOE_PEAK` (default 700), or after `SOE_PEAKMAX` extra frames.
4. Dump the APU via Mesen memory types `spcRam` (64 KiB), `spcDspRegisters` (128
   bytes), `spcRom` (64 bytes). Read SPC700 registers from `emu.getState()` (flat
   keys `spc.pc`, `spc.a`, `spc.x`, `spc.y`, `spc.ps`, `spc.sp`). Read the playing
   song ID from WRAM `$0E4D`.
5. `soundcall.assemble_spc` writes a v0.30 SPC file with an ID666 tag.

SPC file layout (`0x10200` bytes):

| Offset | Size | Content |
|---|---|---|
| `0x00000` | 33 | `SNES-SPC700 Sound File Data v0.30` |
| `0x00021` | 2 | `0x1A 0x1A` |
| `0x00023` | 1 | 26 (ID666 tag present) |
| `0x00024` | 1 | 30 (minor version) |
| `0x00025` | 2 | SPC700 PC |
| `0x00027` | 5 | A, X, Y, PSW, SP |
| `0x0002E` | | ID666 text tag (song title, game title, dumper) |
| `0x00100` | 65536 | audio RAM |
| `0x10100` | 128 | DSP registers |
| `0x10180` | 64 | unused |
| `0x101C0` | 64 | IPL ROM |

`python -m soe.soundcall all` rips every map (0..126), de-duplicates by song ID,
and writes one `song_XX.spc` per song plus a WAV preview and a README that maps
song IDs to maps. `python -m soe.soundcall selftest` rips map 16 and checks the
result.

### Verification

`soundcall.render_spc` plays the `.spc` through libgme (Blargg's `snes_spc` core)
and measures RMS per 0.5 s window. A rip counts as music only if it is clearly
non-silent and its loudness varies over time (a held tone or DC offset is flat).
The APU dump happens at a frame boundary, so occasionally the SPC700 sits in the
driver's idle loop and the `.spc` is valid but silent.
`rip_area_playing` re-runs the rip (up to 5 tries, usually 1 or 2) until the
rendered audio passes.

### Coverage

Area rips cover the field and town music. Battle, boss, event and menu cues that
no map plays as area music are not captured this way. The ripper reports the
song table IDs it did not see.

### Why not force a song ID

Forcing an arbitrary song was investigated in detail and does not produce a
playing song:

- Pinning `$0E4D` at the index computation (`$8C8595`) makes the routine upload
  the data of any song. This works deterministically for every ID, but uploaded
  data is not a playing song: the voices stay at envelope 0.
- Calling the routine through a trampoline (`JSL $8C8581 ; BRA self`, PC and A set
  via `emu.setState`) has two outcomes. With NMI enabled, the main loop re-asserts
  the area song. With NMI disabled, the per-frame NMI sound handler that actually
  starts the sequencer never runs, and the song stays silent.
- Several apparent successes were the title song still ringing. Comparing `$0E4D`
  with the requested ID at capture time exposed them.

Loading an area avoids all of this, because the game starts the song itself, and
`$0E4D` then reports the real playing ID.

## References

- Data Crystal ROM map (audio ranges): https://datacrystal.tcrf.net/wiki/Secret_of_Evermore/ROM_map
- Super Famicom Development Wiki, Seiken Densetsu 2 (Square SPC sequence format): https://wiki.superfamicom.org/seiken-densetsu-2
- SPC file format and players: libgme / Game_Music_Emu, https://github.com/libgme/game-music-emu
- BRRtools (BRR decoder reference): https://github.com/Optiroc/BRRtools
- Mesen2 Lua API (`spcRam`, `spcDspRegisters`, `spcRom`): https://www.mesen.ca/docs/apireference.html
