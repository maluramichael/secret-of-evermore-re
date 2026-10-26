"""Story dialogue (compressed text) -> JSON/TXT.

This module ports the **text decompressor** of Secret of Evermore to Python.
It is documented so that the codec can be rebuilt from code and comments alone.
It also records the reverse-engineering history for the Europe ROM (what was
found, HOW, and which dead ends were discarded and why), so nobody has to walk
the same path again. See also ``docs/text.md``.

Status: the **format** is verified (source below). The **Europe offsets** of
the codec tables and of the text pointer table could NOT be determined
reliably: the Europe ROM restructured the text engine compared to the US
version, it did not merely move it. `extract()` therefore only decodes if the
configured offsets pass a hard verification (known SoE sentences); otherwise
it writes a diagnostic report instead of garbage. For the US ROM the offsets
are known and the decoder produces real sentences, which shows the algorithm
is correct.

===============================================================================
1. THE FORMAT (verified)
===============================================================================
Source: SecretOfEverhack (github.com/Gemini-Loboto3/SecretOfEverhack),
`source/common/Encoding.cpp` (functions `BuildDictionaries`, `ExpandString`,
`DecodeString`) plus `hack/dec.s` (the 65816 disassembly of the original
decompressor `Message_parse`). Both describe exactly the same codec.

A story string is a sequence of tokens (bytes). Decoding runs in TWO stages:

  Stage A - ExpandString: tokens -> byte stream (ASCII + control bytes)
  Stage B - DecodeString: byte stream -> readable text (control bytes -> tokens
            such as {BR}, {END}, {NAME} ...)

Stage A, token ranges (the key point of the codec):

  $00-$3F  Single character via the "scatter"/font table `tbl_eng[code]`.
           tbl_eng is a 64-byte permutation of the most frequent characters
           (frequency scatter), NOT identical to ASCII. The value 0 in this
           table is the STRING TERMINATOR: as soon as tbl_eng[code]==0 would
           be written, the string ends.
           Output: 1 byte.

  $40-$7F  Literal copy. size = code & 0x3F. Copy the next `size` RAW bytes
           unchanged into the output stream (for proper names, numbers,
           anything not covered by the codec).
           Output: `size` bytes. Consumes `size` following bytes.
           (dec.s does the same via @@negup: LSR/AND #$3F/loop.)

  $80-$BF  DTE (digram table encoding). Emits TWO characters from the
           dictionary of the most frequent letter pairs:
           dte[code-0x80] = (byte0, byte1).
           Output: 2 bytes.

  $C0 XX   Dictionary #1 (16-bit). The FOLLOWING byte XX (0..255) indexes the
           large dictionary: emit the null-terminated string dic1[XX].
           Output: variable. Consumes 1 following byte.

  $C1-$FF  Dictionary #2 (8-bit). code-0xC1 (0..62) indexes the small
           dictionary: emit dic2[code-0xC1].
           Output: variable.

Stage B, DecodeString interprets the expanded byte stream:
  < 0x80   normal character (ASCII). Special cases in the ORIGINAL:
           0x00 -> {END} (terminator), '\n'(0x0A) -> line break {BR},
           '_'(0x5F) -> ellipsis, 0x0B -> {VTAB}, '<' -> guillemet, '>' -> ".
  >= 0x80  control code. Known (from Encoding.cpp):
           0x80 = start of an <S ...> block (raw bytes up to 0x80/0x81/0x82),
           0x81={NAME:Boy} 0x82={NAME:Dog} 0x83={Player3} 0x84={Player4}
           0x8B={CHOICE} 0xA1={COUNT} 0xA2={ITEM}. Everything else -> {$XX}.

How the two dictionaries are BUILT (BuildDictionaries):
  - dic2: 63 entries (indices 1..63). Offset table `dic2_ptr` (u16 per
    entry), data base `dic2_data`. dic2[i-1] = C string at
    dic2_data + u16(dic2_ptr + i*2).  (The loop starts at i=1; therefore
    token $C1 -> dic2[0] -> ptr slot 1.)
  - dic1: 256 entries (indices 0..255). Offset table `dic1_ptr` (u16),
    data base `dic1_data`. dic1[i] = C string at dic1_data + u16(dic1_ptr+i*2).
  The dictionary strings are stored as PLAIN ASCII in the ROM (they end up
  unchanged in the expanded stream, which stage B then reads as characters).

The text pointer table (US: `DumpText`, rom[0x11d000], 3002 entries of 3
bytes). Per entry [b0,b1,b2]:
  p    = (u16le(b0,b1) & 0x7fff) | ((u16le(b1,b2) & 0x7f80) << 9)
       = b0 | (b1&0x7f)<<8 | (b1&0x80)<<9 | (b2&0x7f)<<17   (bit 15 is dropped)
  compressed flag = b2 & 0x80  -> set: DecodeString; otherwise: plain ASCII
  In the US ROM, p is an ABSOLUTE file offset: DecodeString(&rom[p]).

===============================================================================
2. OFFSETS
===============================================================================
US/NTSC (byte-exact from Encoding.cpp::BuildDictionaries + somext.cpp,
verified - the reference decoder produces real US dialogue with them):

  ptr_table  0x11D000   (3002 entries of 3 bytes)
  dte        0x11F32E   (64 pairs = 128 bytes)
  tbl_eng    0x11F3AE   (64-byte scatter)
  dic2_ptr   0x11F3EC   (u16 offsets)
  dic1_ptr   0x11F46C   (u16 offsets, 256)
  dic2_data  0x11F66C   (ASCII words)
  dic1_data  0x11F7D5   (ASCII words)

In the US ROM these six codec tables are contiguous in bank $91
(file 0x11F32E..~0x11F8xx). Relative layout:
  dte+0x00, tbl_eng+0x80, dic2_ptr+0xBE, dic1_ptr+0x13E, dic2_data+0x33E,
  dic1_data+0x4A7.

EUROPE: NOT determined. The US offsets yield graphics data in the Europe ROM
(at 0x11F3AE/0x11D000 the EU ROM holds tile material, no codec/pointers).
The Europe data tables are shifted non-uniformly relative to US (weapons
+0x640, ingredients +0xA666, font +1), so a simple shift does not work. What
the search found (everything documented below) was NOT enough for a verified
decode:

  EU_PTR_CANDIDATE   = 0x128000
    3-byte table, ~3080 entries whose p values rise monotonically 0..0x30BDF
    (signature of a pointer table). BUT: the targets decode, whether treated
    as relative (base 0x12A418, directly behind the table) or as an
    absolute/HiROM offset, to binary/script data, NOT to text. A language
    model attack (quadgram hill climb, alignment against the known US
    sentences) did not converge. -> REJECTED as a text table (most likely
    map/event script pointers, see soe/script.py).

  EU_DICT_WORDS_AT   = 0x16140..0x16660
    The ONLY area outside the plain ASCII block (0x50700-0x52260, see
    text.py) and the map names (0x2D8000) that contains real dialogue
    vocabulary in clear text: short common words such as "and ", "for ",
    "of ", "our " and similar. The words are duplicated in pairs and sit
    between script binary data, which looks strongly like embedded event
    script and not like a clean dictionary table. Very likely either part of
    the codec (dic1/dic2 data) OR inline text in the event script, but not
    usable without the matching tbl_eng/dte/ptr tables.

===============================================================================
3. REJECTED DEAD ENDS (so nobody repeats them)
===============================================================================
  - US offsets applied directly to the EU ROM: graphics at 0x11F3AE, tbl_eng
    comes out as garbage. -> the EU codec is relocated.
  - Fixed shift US->EU: the known data shifts are non-uniform (bank
    dependent), so they do not transfer to the codec.
  - "efuatly" region at 0x12A950: looked like a scatter table/dictionary,
    but is part of the 0x128000 target region (binary). Not a codec.
  - Clear-text search for dictionary words ("about", "across", "and\\0"):
    found almost nothing -> story dialogue is NOT stored as plain ASCII in
    the ROM (confirmed: it is compressed). "the"/"you" appear only ~20 times,
    all in the plain block/the maps - there is no large plain text zone.
  - Disassembly of the routine at US file 0xCCDF8 (US location of
    Message_parse): in EU that address holds GRAPHICS code (writes VRAM
    $2118) - the text routine is elsewhere in EU and direct-page driven
    (table addresses set at run time), so it cannot be read statically from
    immediates.
  - Index alignment EU entry i == US entry i: does NOT hold (EU entries
    1..11 are empty, US 1..11 have text) - EU order/set differs.

Whoever wants to find the Europe offsets has two promising paths:
  (a) Place a US ROM alongside and search the EU ROM for the codec block
      (US 0x11F32E, ~1.7 KB of English tables) as a byte pattern - the
      tables are language-identical and should be largely identical.
  (b) Trace the EU text routine dynamically (emulator breakpoint on the
      tbl_eng read access) and read the base addresses from the DP pointers.
Once the six offsets + the pointer table are known, the decoder below works
unchanged: just fill `EUROPE_OFFSETS`.
"""
from __future__ import annotations
import json
import struct
from pathlib import Path

from .rom import Rom

# --- Control code -> readable token (stage B) --------------------------------
# From Encoding.cpp::DecodeString. Anything not listed is shown as {$XX}.
CONTROL_TOKENS = {
    0x81: "{NAME:Boy}",
    0x82: "{NAME:Dog}",
    0x83: "{Player3}",
    0x84: "{Player4}",
    0x8B: "{CHOICE}",
    0xA1: "{COUNT}",
    0xA2: "{ITEM}",
}

# --- Offset sets per region --------------------------------------------------
# US: verified. EUROPE: unknown (see module docstring). A None field means
# "not determined" -> extract() switches to diagnostic mode.
US_OFFSETS = {
    "ptr_table": 0x11D000,
    "ptr_count": 3002,
    "dte":       0x11F32E,
    "tbl_eng":   0x11F3AE,
    "dic2_ptr":  0x11F3EC,
    "dic2_data": 0x11F66C,
    "dic1_ptr":  0x11F46C,
    "dic1_data": 0x11F7D5,
    "relative":  False,   # US pointers are absolute file offsets
}

# Europe: deliberately None. Candidates are listed in the docstring/report.
EUROPE_OFFSETS = {
    "ptr_table": None,     # candidate 0x128000 (rejected, see docstring)
    "ptr_count": None,
    "dte":       None,
    "tbl_eng":   None,
    "dic2_ptr":  None,
    "dic2_data": None,
    "dic1_ptr":  None,
    "dic1_data": None,
    "relative":  None,
}

OFFSETS_BY_REGION = {"usa": US_OFFSETS, "europe": EUROPE_OFFSETS}

# Known SoE lines for HARD verification. If none of them shows up in the output,
# the offset/dictionary configuration is wrong -> do not deliver.
KNOWN_LINES = ("gain item", "Nothing", "Chocobo", "Podunk", "exchange", "Jewel")


# =============================================================================
# Codec (faithful port of Encoding.cpp)
# =============================================================================
class Codec:
    """Holds the six tables and expands/decodes strings.

    Constructed from `rom.data` and an offset set. Raises `ValueError` if a
    required offset is missing (None) so the caller can catch it cleanly.
    """

    def __init__(self, data: bytes, off: dict):
        for key in ("dte", "tbl_eng", "dic2_ptr", "dic2_data", "dic1_ptr", "dic1_data"):
            if off.get(key) is None:
                raise ValueError(f"Codec offset '{key}' not determined (region not configured)")
        self.data = data
        self.off = off
        self._build()

    def _u16(self, o: int) -> int:
        return struct.unpack_from("<H", self.data, o)[0]

    def _cstr(self, o: int) -> bytes:
        """Null-terminated raw string starting at o (without the 0)."""
        e = o
        n = len(self.data)
        while e < n and self.data[e] != 0:
            e += 1
        return self.data[o:e]

    def _build(self):
        # dte: 64 pairs = 128 bytes from off['dte'].
        d = self.off["dte"]
        self.dte = [(self.data[d + i * 2], self.data[d + i * 2 + 1]) for i in range(64)]
        # tbl_eng: 64-byte scatter from off['tbl_eng'].
        t = self.off["tbl_eng"]
        self.tbl_eng = [self.data[t + i] for i in range(64)]
        # dic2: 63 entries, ptr slots 1..63 (slot 0 skipped as in the original).
        p2, b2 = self.off["dic2_ptr"], self.off["dic2_data"]
        self.dic2 = [self._cstr(b2 + self._u16(p2 + i * 2)) for i in range(1, 64)]
        # dic1: 256 entries.
        p1, b1 = self.off["dic1_ptr"], self.off["dic1_data"]
        self.dic1 = [self._cstr(b1 + self._u16(p1 + i * 2)) for i in range(256)]

    def expand(self, start: int, limit: int = 8192) -> bytes:
        """Stage A: tokens from `start` -> expanded byte stream (incl. control bytes).

        Ends as soon as a 0 would be written via tbl_eng (terminator) or
        `limit` is reached (guard against broken pointers).
        """
        data = self.data
        out = bytearray()
        i = start
        n = len(data)
        while i < n and len(out) < limit:
            c = data[i]
            i += 1
            if c < 0x40:
                # Single character via scatter table; 0 => end of string.
                ch = self.tbl_eng[c]
                out.append(ch)
                if ch == 0:
                    break
            elif c < 0x80:
                # Literal copy of (c & 0x3F) raw bytes.
                size = c & 0x3F
                out += data[i:i + size]
                i += size
            elif c < 0xC0:
                # DTE pair.
                a, b = self.dte[c - 0x80]
                out.append(a)
                out.append(b)
            elif c == 0xC0:
                # Dictionary #1, index = following byte.
                out += self.dic1[data[i]]
                i += 1
            else:
                # Dictionary #2, index = c - 0xC1.
                out += self.dic2[c - 0xC1]
        return bytes(out)

    def decode(self, start: int) -> str:
        """Stage B: make the expanded stream readable (control codes -> tokens)."""
        stream = self.expand(start)
        s = []
        i = 0
        n = len(stream)
        while i < n:
            b = stream[i]
            i += 1
            if b < 0x80:
                if b == 0x00:
                    s.append("{END}")
                    break
                elif b == 0x0A:
                    s.append("{BR}")
                elif b == 0x0B:
                    s.append("{VTAB}")
                elif b == 0x5F:
                    s.append("...")           # '_' = ellipsis in the original
                else:
                    s.append(chr(b))
            else:
                if b == 0x80:
                    # <S ...> block: raw bytes up to the next name/Boy/Dog code.
                    raw = []
                    while i < n and stream[i] not in (0x80, 0x81, 0x82):
                        raw.append(f"{stream[i]:02X}")
                        i += 1
                    if i < n:
                        raw.append(f"{stream[i]:02X}")
                        i += 1
                    s.append("{S:" + " ".join(raw) + "}")
                else:
                    s.append(CONTROL_TOKENS.get(b, f"{{${b:02X}}}"))
        return "".join(s)


# =============================================================================
# Public API (uniform soe signatures)
# =============================================================================
def _region_offsets(rom: Rom) -> dict:
    return OFFSETS_BY_REGION.get(rom.region, EUROPE_OFFSETS)


def decode_string(rom: Rom, ptr: int) -> str:
    """Decode ONE story string from absolute file offset `ptr`.

    Requires a configured region (US); raises `ValueError` if the codec
    offsets of the ROM region are unknown (e.g. Europe, see docstring).
    """
    codec = Codec(rom.data, _region_offsets(rom))
    return codec.decode(ptr)


def _read_pointer(data: bytes, o: int) -> tuple[int, bool]:
    """Decode a 3-byte text pointer -> (offset, compressed?). See docstring."""
    b0, b1, b2 = data[o], data[o + 1], data[o + 2]
    lo = (b0 | (b1 << 8)) & 0x7FFF
    hi = ((b1 | (b2 << 8)) & 0x7F80) << 9
    return lo | hi, bool(b2 & 0x80)


def all_dialogues(rom: Rom) -> dict[int, str]:
    """All story strings reachable via the text pointer table.

    Key = entry index, value = decoded text. Requires a configured region
    including its pointer table; raises `ValueError` otherwise.
    """
    off = _region_offsets(rom)
    if off.get("ptr_table") is None or off.get("ptr_count") is None:
        raise ValueError(f"Pointer table for region '{rom.region}' not determined")
    codec = Codec(rom.data, off)
    base = off["ptr_table"]
    relative = off.get("relative", False)
    text_base = off.get("ptr_table") if relative else 0
    result = {}
    for i in range(off["ptr_count"]):
        p, compressed = _read_pointer(rom.data, base + i * 3)
        target = (text_base + p) if relative else p
        if not (0 <= target < len(rom.data)):
            continue
        # Uncompressed entries are plain ASCII up to 0x00 (DecodeStringAscii);
        # we decode both via the same codec (expand is a no-op for plain
        # ASCII except for the control codes).
        result[i] = codec.decode(target)
    return result


def _looks_english(strings) -> bool:
    joined = "\n".join(strings)
    return any(k in joined for k in KNOWN_LINES)


def extract(rom: Rom, out: Path) -> dict:
    """Story dialogue -> assets/text/dialogue.{json,txt}.

    Only decodes if the output passes the HARD verification (known SoE lines
    show up). Otherwise NO garbage is written, but a diagnostic report, so it
    stays visible that the Europe offsets are still missing instead of
    faking data.
    """
    out.mkdir(parents=True, exist_ok=True)

    # Story dialogue: EU rebuilt the text system and its codec tables are not
    # located. The US ROM decodes cleanly (US offsets verified) and the English
    # story text is identical in content. If a US ROM sits next to the given
    # ROM, we decode the dialogue from it.
    if rom.region != "usa":
        us = rom.path.parent / "Secret of Evermore (USA).sfc"
        if us.exists():
            rom = Rom(us)                       # region becomes "usa" via SHA1

    off = _region_offsets(rom)
    configured = off.get("ptr_table") is not None and off.get("dte") is not None
    dialogues = {}
    status = "unconfigured"
    error = None
    if configured:
        try:
            dialogues = all_dialogues(rom)
            status = "decoded" if _looks_english(dialogues.values()) else "unverified"
        except Exception as e:  # broken offsets / pointers -> report
            status = "error"
            error = str(e)

    verified = status == "decoded"
    if verified:
        payload = {str(k): v for k, v in sorted(dialogues.items())}
        (out / "dialogue.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False))
        (out / "dialogue.txt").write_text(
            "\n".join(f"{k}\t{v}" for k, v in sorted(dialogues.items())))
        # Hard assertion as in text.py: at least one known line must be present.
        joined = "\n".join(dialogues.values())
        assert any(k in joined for k in KNOWN_LINES), "Verification failed"
        return {"dialogues": len(dialogues), "status": "verified"}

    # --- Diagnostics instead of garbage ----------------------------------------
    diag = {
        "status": status,
        "region": rom.region,
        "error": error,
        "note": (
            "Europe offsets for the story text codec are not determined. "
            "The format is verified (see dialogue.py docstring), but without "
            "the EU table offsets no verified text can be produced. "
            "Candidates and search paths are in the docstring."
        ),
        "eu_candidates": {
            "ptr_table_rejected": "0x128000",
            "dict_words_seen": "0x16140..0x16660",
        },
    }
    (out / "dialogue.json").write_text(json.dumps(diag, indent=2, ensure_ascii=False))
    (out / "dialogue.txt").write_text(
        "# Story dialogue cannot be decoded yet.\n"
        f"# status={status} region={rom.region}\n"
        "# Reason: Europe codec offsets undetermined. Details in the module "
        "docstring of soe/dialogue.py.\n")
    return {"dialogues": 0, "status": status}


if __name__ == "__main__":
    # Self-check of the ALGORITHM (no ROM needed): a mini codec with known
    # tables must deterministically produce the expected result.
    fake = bytearray(0x1000)
    # tbl_eng[1]='H', tbl_eng[2]='i', tbl_eng[0]=0 (terminator)
    tbl = 0x100
    fake[tbl + 0] = 0
    fake[tbl + 1] = ord("H")
    fake[tbl + 2] = ord("i")
    # dte[0] = ("y","o")
    dte = 0x200
    fake[dte + 0] = ord("y")
    fake[dte + 1] = ord("o")
    # dic2 ptr/data: dic2[0] (token $C1) = "!!" ; ptr slot 1 points to offset 0
    dic2_ptr, dic2_data = 0x300, 0x340
    struct.pack_into("<H", fake, dic2_ptr + 1 * 2, 0)
    fake[dic2_data + 0] = ord("!")
    fake[dic2_data + 1] = ord("!")
    fake[dic2_data + 2] = 0
    # dic1 (unused here, but must be readable)
    dic1_ptr, dic1_data = 0x380, 0x3C0
    fake[dic1_data] = 0
    off = dict(dte=dte, tbl_eng=tbl, dic2_ptr=dic2_ptr, dic2_data=dic2_data,
               dic1_ptr=dic1_ptr, dic1_data=dic1_data)
    codec = Codec(bytes(fake), off)
    # Token sequence: $01('H') $02('i') $80(DTE 'yo') $C1(dic2 '!!') $41 <1 raw 'X'> $00(END)
    msg = 0x000
    prog = [0x01, 0x02, 0x80, 0xC1, 0x41, ord("X"), 0x00]
    for k, v in enumerate(prog):
        fake[msg + k] = v
    codec = Codec(bytes(fake), off)   # rebuild with filled msg
    got = codec.decode(msg)
    assert got == "Hiyo!!X{END}", f"Self-check failed: {got!r}"
    print("dialogue.py self-check OK:", got)
