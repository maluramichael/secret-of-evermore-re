"""soe: extraction library for the Secret of Evermore ROM.

Each domain module (data, text, fonts, gfx, audio, palettes, sprites, maps)
exports `extract(rom: Rom, out: Path) -> dict` with a uniform signature.
`python -m soe` calls them through the DOMAINS registry. `lz` is not an asset
domain, it is the shared graphics decompressor used by sprites/maps.
"""
from .rom import Rom
from . import data, text, fonts, gfx, audio, palettes, sprites, maps, lz

# Order = execution order in the CLI. name -> (module, needs_pillow)
# palettes before sprites (sprites uses character palettes).
DOMAINS = {
    "data":     (data,     False),
    "text":     (text,     False),
    "fonts":    (fonts,    True),
    "palettes": (palettes, True),
    "gfx":      (gfx,      True),
    "sprites":  (sprites,  True),
    "audio":    (audio,    False),
    "maps":     (maps,     False),
}

__all__ = ["Rom", "DOMAINS", "lz"]
