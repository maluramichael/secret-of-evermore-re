"""BitmapFont: draws text with the original SNES Secret of Evermore font.

Glyph->ASCII mapping (derived empirically from the extracted sheet). The PNG sheet ``font_main.png`` is 256x384, 16 glyphs
per row, each glyph a 16x16 (2x-scaled) cell. Only every 3rd tile carries a
glyph, so the mapping is:

    tile_index = 3 * (ord(char) - 0x20)

Verified against known ROM strings: tile 48='0', 99='A', 102='B', 105='C',
33='+' (ASCII 43). Rendering item names from
strings.json comes out cleanly legible. Space (0x20 -> tile 0) is drawn as a
blank gap. ASCII 0x20..0x7E covers tiles 0..282; the sheet's tiles beyond that
are accented Latin glyphs we don't map yet.
"""
from __future__ import annotations

import pygame

from . import assets

GLYPH = 8          # native glyph size (px); the PNG is 2x, we halve it
SHEET_COLS = 16
_ASCII_LO, _ASCII_HI = 0x20, 0x7E


class BitmapFont:
    def __init__(self, sheet_path=assets.FONT_MAIN):
        raw = pygame.image.load(str(sheet_path)).convert_alpha()
        # Sheet is a clean 2x nearest upscale; halving with plain scale
        # recovers the exact 8x8 glyphs.
        self.sheet = pygame.transform.scale(raw, (raw.get_width() // 2, raw.get_height() // 2))
        self.height = GLYPH
        self._tinted: dict[tuple[int, int, int], pygame.Surface] = {}

    def _src_rect(self, ch: str) -> pygame.Rect | None:
        o = ord(ch)
        if o < _ASCII_LO or o > _ASCII_HI or ch == " ":
            return None
        tile = 3 * (o - 0x20)
        col, row = tile % SHEET_COLS, tile // SHEET_COLS
        return pygame.Rect(col * GLYPH, row * GLYPH, GLYPH, GLYPH)

    def _sheet_for(self, color) -> pygame.Surface:
        if color is None:
            return self.sheet
        key = tuple(color)
        s = self._tinted.get(key)
        if s is None:
            s = self.sheet.copy()
            # Glyphs are white; multiply to tint while keeping alpha shape.
            s.fill((*key, 255), special_flags=pygame.BLEND_RGBA_MULT)
            self._tinted[key] = s
        return s

    def text_width(self, text: str) -> int:
        return len(text) * GLYPH

    def draw(self, surface: pygame.Surface, text: str, x: int, y: int, color=None) -> None:
        sheet = self._sheet_for(color)
        cx = x
        for ch in text:
            r = self._src_rect(ch)
            if r is not None:
                surface.blit(sheet, (cx, y), r)
            cx += GLYPH

    def draw_centered(self, surface, text, cx, y, color=None) -> None:
        self.draw(surface, text, cx - self.text_width(text) // 2, y, color)

    @staticmethod
    def wrap(text: str, max_chars: int) -> list[str]:
        """Greedy word-wrap to a character budget per line."""
        lines: list[str] = []
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split(" "):
                if line and len(line) + 1 + len(word) > max_chars:
                    lines.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            lines.append(line)
        return lines
