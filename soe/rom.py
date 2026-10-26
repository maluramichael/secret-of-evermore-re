"""Shared foundation for all SoE asset extractors.

A `Rom` instance loads the ROM, identifies the region by SHA1 and provides the
region-dependent offset table plus the shared low-level decoders (1bpp/4bpp
tiles, SNES colors, BRR audio). Each domain module (data/fonts/gfx/audio/text)
builds on it instead of duplicating decoders.
"""
from __future__ import annotations
import hashlib
import struct
from pathlib import Path

# Identify ROM by SHA1 -> region key. Extensible with further dumps.
KNOWN_ROMS = {
    "ae17166919fdfdf26cc5771f83cfd19eaf71806c": "europe",
    "79e7738630fff5699217ef58ecc421bc8fcbcd89": "usa",  # only used for story dialogue
}

# Region-dependent file offsets (verified against the Europe ROM, see docs/rom.md).
# Graphics/audio banks are usually region-independent; data tables shift
# because of the translated text. US values as reference from soerominfo.c.
OFFSETS = {
    "europe": {
        # Data tables (pointer tables; start..end of the pointer list)
        "weapon_ptr":     (0x43EB6, 0x43ED3),   # 2-byte ptr, 36-byte records
        "armor_ptr":      (0x43ED6, 0x43F25),   # 2-byte ptr, 10-byte records
        "ingredient":     (0x50176, 0x501A1),
        "alchemy":        (0x502A1, 0x502E6),
        "callbead":       (0x5055D, 0x5057C),
        "npc":            (0xEC536, 0xEDF84),
        "boy_levelup":    (0xC8F65, None),      # 99 entries of 3 bytes
        "dog_levelup":    (0xC9091, None),
        # Text (Europe: names/descriptions/menu = plain null-terminated ASCII)
        "text_plain":     (0x50700, 0x52260),
        "map_names":      (0x2D8000, None),      # records [flag M/m][0x2E][name\0], Europe (US was 0x2C8000)
        # Graphics / font (region-independent)
        "font_main":      (0x40003, 0x40C02),   # 1bpp, 8 B per 8x8 tile (Europe: 0x40003, verified by alignment search; the Datacrystal US value 0x40002 is wrong here)
        "font_small":     (0x40C84, 0x41883),
        "window_pattern": (0x41924, 0x419B3),
        "window_border":  (0x419B4, 0x41E83),
        # Audio (BRR sample banks, region-independent)
        "brr_banks": [
            (0x1A75C, 0x1CFFB), (0x48000, 0x4FA71),
            (0x58000, 0x6FFFF), (0x78000, 0xA9FFF),
        ],
    },
}



class Rom:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        # strip the SMC copier header (512 B) if present
        self.smc_header = len(raw) % 1024 == 512
        self.data = raw[512:] if self.smc_header else raw
        self.sha1 = hashlib.sha1(self.data).hexdigest()
        self.region = KNOWN_ROMS.get(self.sha1, "europe")  # default: Europe layout
        # OFFSETS only covers Europe (data/graphics/audio). The US ROM is only
        # needed for story dialogue (soe.dialogue uses its own US offsets),
        # so fall back to Europe here instead of keeping a separate US table.
        self.offsets = OFFSETS.get(self.region, OFFSETS["europe"])

    # --- Byte access -----------------------------------------------------
    def read(self, off: int, n: int) -> bytes:
        return self.data[off:off + n]

    def u16(self, off: int) -> int:
        return struct.unpack_from("<H", self.data, off)[0]

    def span(self, key: str):
        """(start, end) tuple of a data table. For brr_banks use offsets['brr_banks'] directly."""
        return self.offsets[key]

    # --- Tile decoders -----------------------------------------------------
    @staticmethod
    def decode_1bpp(tile: bytes) -> list[list[int]]:
        """8 bytes -> 8x8, values 0/1 (MSB = left)."""
        return [[(tile[y] >> (7 - x)) & 1 for x in range(8)] for y in range(8)]

    @staticmethod
    def decode_4bpp(tile: bytes) -> list[list[int]]:
        """32 bytes SNES 4bpp planar -> 8x8, values 0..15.

        Layout: rows 0-7 as bitplane pairs bp0/bp1 (16 B), then bp2/bp3 (16 B).
        """
        px = [[0] * 8 for _ in range(8)]
        for y in range(8):
            b0, b1 = tile[y * 2], tile[y * 2 + 1]
            b2, b3 = tile[16 + y * 2], tile[16 + y * 2 + 1]
            for x in range(8):
                s = 7 - x
                px[y][x] = (((b0 >> s) & 1)
                            | (((b1 >> s) & 1) << 1)
                            | (((b2 >> s) & 1) << 2)
                            | (((b3 >> s) & 1) << 3))
        return px

    @staticmethod
    def snes_color(word: int) -> tuple[int, int, int]:
        """15bit BGR (0bBBBBBGGGGGRRRRR) -> 8bit RGB."""
        r = (word & 0x1F) << 3
        g = ((word >> 5) & 0x1F) << 3
        b = ((word >> 10) & 0x1F) << 3
        return (r | r >> 5, g | g >> 5, b | b >> 5)

    def palette(self, off: int, colors: int = 16) -> list[tuple[int, int, int]]:
        return [self.snes_color(self.u16(off + i * 2)) for i in range(colors)]

    # --- BRR audio --------------------------------------------------------
    # Predictor from the previous 2 samples, canonical S-DSP forms (BRRtools brr.c).
    @staticmethod
    def _brr_predict(filt: int, p1: int, p2: int) -> int:
        if filt == 0:
            return 0
        if filt == 1:
            return p1 - (p1 >> 4)
        if filt == 2:
            return (p1 << 1) + ((-(p1 + (p1 << 1))) >> 5) - p2 + (p2 >> 4)
        return (p1 << 1) + ((-(p1 + (p1 << 2) + (p1 << 3))) >> 6) - p2 + ((p2 + (p2 << 1)) >> 4)

    @classmethod
    def decode_brr(cls, data: bytes, start: int) -> tuple[list[int], int]:
        """Decode a BRR sample from `start` up to the end flag (verified, _selftest in soe.audio).

        Returns (PCM16 samples, byte length). 9-byte blocks:
        header (shift<<4 | filter<<2 | loop<<1 | end) + 8 data bytes = 16 nibbles.
        """
        p1 = p2 = 0
        out: list[int] = []
        pos = start
        while pos + 9 <= len(data):
            header = data[pos]
            shift = header >> 4
            filt = (header >> 2) & 3
            end = header & 1
            for i in range(8):
                byte = data[pos + 1 + i]
                for nib in (byte >> 4, byte & 0x0F):
                    s = nib - 16 if nib >= 8 else nib               # 4-bit signed
                    a = ((s << shift) >> 1) if shift <= 0x0C else (2048 if s >= 0 else -2048)
                    a += cls._brr_predict(filt, p1, p2)
                    a = max(-0x8000, min(0x7FFF, a))
                    if a > 0x3FFF:                                  # wrap to signed 15-bit
                        a -= 0x8000
                    elif a < -0x4000:
                        a += 0x8000
                    p2, p1 = p1, a
                    out.append(2 * p1)
            pos += 9
            if end:
                break
        return out, pos - start
