"""Asset loading: paths, JSON data tables, real game strings.

All read-only. Assets live in the repo's top-level ``assets/`` dir (extracted
from the Secret of Evermore Europe ROM by the ``soe`` library).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT_MAIN = ASSETS / "fonts" / "font_main.png"
FONT_SMALL = ASSETS / "fonts" / "font_small.png"


@lru_cache(maxsize=None)
def _load(rel: str):
    return json.loads((ASSETS / rel).read_text(encoding="utf-8"))


def data(table: str) -> list[dict]:
    """A data table from assets/data/<table>.json (weapon, armor, alchemy, ...)."""
    return _load(f"data/{table}.json")


def strings() -> dict[str, str]:
    """Real English strings, key = hex ROM offset."""
    return _load("text/strings.json")


def map_names() -> dict[str, str]:
    return _load("maps/map_names.json")


def _map_id(path: Path) -> int | None:
    """Map index from a path like .../screen_map_0016/map.png or rendered/map_0016.png."""
    m = re.search(r"map_(\d{3,4})", path.as_posix())
    return int(m.group(1)) if m else None


# Render sources, best first: the SNES caller (the game's own loader, authoritative),
# then the ROM renderer, then quality-checked baked maps.
_MAP_GLOBS = ["maps/snescall/map_*.png", "maps/rendered/map_*.png", "maps/baked/*/map.png"]


@lru_cache(maxsize=1)
def available_maps() -> list[dict]:
    """Playable rendered maps: [{id, name, path, w, h}], de-duplicated per map index.

    snescall renders come from the game's own loader and are authoritative:
    they are only discarded if practically empty (timeout/black) and always
    win the de-duplication. The other sources go through a strict quality
    filter (empty/streaky images are dropped). New renders are picked up
    automatically (clear the lru_cache to rescan).
    """
    from PIL import Image, ImageStat
    best: dict[int, tuple[float, dict]] = {}
    for pattern in _MAP_GLOBS:
        for p in sorted(ASSETS.glob(pattern)):
            mid = _map_id(p)
            if mid is None:
                continue
            try:
                im = Image.open(p).convert("RGB")
                var = sum(ImageStat.Stat(im).var) / 3
                px = list(im.getdata())
                nonblack = sum(1 for r, g, b in px if r + g + b > 30) / len(px)
            except Exception:
                continue
            authoritative = "snescall" in p.as_posix()
            if authoritative:
                if nonblack < 0.02:                # only drop real misses/timeouts
                    continue
                score = 1e9 + var * nonblack       # always wins against other sources
            else:
                if var < 1000 or nonblack < 0.25:  # empty/streaky -> drop
                    continue
                score = var * nonblack
            if mid not in best or score > best[mid][0]:
                name = map_names().get(str(mid), f"MAP {mid}")
                best[mid] = (score, {"id": mid, "name": name,
                                     "path": str(p), "w": im.width, "h": im.height})
    return [v[1] for _, v in sorted(best.items())]


def sample_string(index: int) -> str:
    """Pick one real string deterministically (for dialogue demos)."""
    vals = list(strings().values())
    return vals[index % len(vals)]


# --- story dialogues (decoded from the ROM, with SoE control codes) ---------

def format_dialogue(raw: str) -> str:
    """Convert SoE control codes into displayable text.

    {NAME:X} -> X, {BR} -> a space; all other codes
    ({END}, {$xx} portrait/color, {S:.. ..} pause, {ITEM}, {COUNT} ...) are removed.
    """
    s = raw.replace("{BR}", " ")
    s = re.sub(r"\{NAME:([^}]*)\}", r"\1", s)   # keep name placeholders
    s = re.sub(r"\{[^}]*\}", "", s)             # drop remaining control codes
    return " ".join(s.split())


# System/menu lines that are not real NPC dialogue
_SYSTEM_PREFIX = ("gain item", "Found ", "unknown ", "Learned ", "Got ")


@lru_cache(maxsize=1)
def story_lines() -> list[str]:
    """Formatted story dialogue (sentences) from assets/text/dialogue.json.

    Filtered to real sentences (enough letters, spaces), de-duplicated, in ROM
    order. Empty if dialogue.json is missing or unconfigured.
    """
    try:
        raw = _load("text/dialogue.json")
    except (FileNotFoundError, ValueError):
        return []
    if not isinstance(raw, dict) or raw.get("status"):   # diagnostic report -> no dialogue
        return []
    seen, out = set(), []
    for _, v in sorted(raw.items(), key=lambda kv: int(kv[0])):
        t = format_dialogue(v)
        if len(t) < 12 or " " not in t or sum(c.isalpha() for c in t) < 8:
            continue
        if not re.search(r"[.!?]", t):        # real sentences only, no item/status lines
            continue
        if t in seen or t.startswith(_SYSTEM_PREFIX):
            continue
        seen.add(t)
        out.append(t)
    return out
