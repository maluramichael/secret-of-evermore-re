"""Game loop, state machine and the individual states.

States: title -> mapselect -> mapview -> (DialogueBox overlay | menu).
Maps are real, ROM-rendered images (see soe.mapbake); the player walks on them.
Everything renders to a 256x224 (SNES) logical surface scaled to the window.
"""
from __future__ import annotations

import pygame

from . import assets
from .font import BitmapFont

LOGICAL_W, LOGICAL_H = 256, 224
SCALE = 3
FPS = 60
TILE = 16

# --- palette ---------------------------------------------------------------
C_BG = (16, 16, 24)
C_GRASS = (56, 104, 56)
C_GRASS2 = (64, 116, 64)
C_TREE = (28, 66, 34)
C_WATER = (40, 72, 152)
C_PATH = (168, 148, 108)
C_WALL = (96, 96, 112)
C_PLAYER = (216, 96, 64)
C_PLAYER_D = (150, 56, 40)
C_BOX = (24, 28, 72)
C_BOX_BORDER = (232, 232, 248)
C_WHITE = (240, 240, 248)
C_DIM = (150, 160, 180)
C_SEL = (248, 216, 96)


def _camera(center: int, viewport: int, mapsize: int) -> int:
    """Camera offset for one axis. Smaller than the viewport -> center the map
    (negative offset); otherwise center on the focus and clamp to the edge."""
    if mapsize <= viewport:
        return -(viewport - mapsize) // 2
    return max(0, min(center - viewport // 2, mapsize - viewport))


def _load_player_frames():
    """Boy sprites from the ROM (assets/sprites/player, extracted at 0x1A0000).

    Per direction [stand, walk1] as a 16x32 surface. None if the assets are
    missing (the map view then falls back to the placeholder block).
    """
    d = assets.ASSETS / "sprites" / "player"
    try:
        frames = {}
        for face in ("down", "up", "left", "right"):
            imgs = []
            for name in ("stand", "walk1"):
                img = pygame.image.load(str(d / f"boy_{face}_{name}.png"))
                imgs.append(img.convert_alpha())
            frames[face] = imgs
        return frames
    except Exception:
        return None


def _load_blip():
    """Short UI sound from a real ROM instrument (assets/audio).

    None if there is no audio device (e.g. headless); the viewer then stays
    silent instead of crashing.
    """
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception:
        return None
    d = assets.ASSETS / "audio"
    for name in ("inst_0009.wav", "inst_0000.wav", "inst_0010.wav"):
        p = d / name
        if p.exists():
            try:
                s = pygame.mixer.Sound(str(p))
                s.set_volume(0.4)
                return s
            except Exception:
                continue
    return None


class MapView:
    """Walk on a real map (PNG) rendered from the ROM.

    Edge collision (at the image borders), camera follows the boy. Per-tile
    collision from SoE is not decoded yet, so only the image bounds apply.
    """

    def __init__(self, map_info: dict):
        self.name = map_info["name"]
        self.surf = pygame.image.load(map_info["path"]).convert()
        self.w, self.h = self.surf.get_size()
        self.px, self.py = self.w / 2, self.h / 2
        self.speed = 1.6
        self.size = 14
        self.frames = _load_player_frames()
        self.facing = "down"
        self.anim = 0.0

    def move(self, dx: float, dy: float) -> None:
        if dx or dy:
            if abs(dx) >= abs(dy):
                self.facing = "right" if dx > 0 else "left"
            else:
                self.facing = "down" if dy > 0 else "up"
            self.anim += 0.15
        m = self.size
        self.px = max(m, min(self.px + dx * self.speed, self.w - m))
        self.py = max(m, min(self.py + dy * self.speed, self.h - m))

    def draw(self, surf: pygame.Surface, font: BitmapFont) -> None:
        vw, vh = surf.get_size()
        cam_x = _camera(int(self.px), vw, self.w)
        cam_y = _camera(int(self.py), vh, self.h)
        surf.fill(C_BG)
        surf.blit(self.surf, (-cam_x, -cam_y))
        px, py = int(self.px) - cam_x, int(self.py) - cam_y
        if self.frames:
            frame = self.frames[self.facing][1 if int(self.anim) % 2 else 0]
            surf.blit(frame, (px - frame.get_width() // 2,
                              py - frame.get_height() + self.size // 2))
        else:
            pygame.draw.rect(surf, C_PLAYER, (px - 7, py - 7, 14, 14))
        w = font.text_width(self.name)
        pygame.draw.rect(surf, C_BOX, (2, 2, w + 8, 12))
        font.draw(surf, self.name, 6, 3, C_WHITE)


class MapSelect:
    """Selection list of the rendered maps (name + index)."""

    def __init__(self, font: BitmapFont):
        self.font = font
        self.maps = assets.available_maps()
        self.sel = 0
        self.top = 0
        self.rows_visible = 16

    def move(self, d: int) -> None:
        if not self.maps:
            return
        self.sel = max(0, min(self.sel + d, len(self.maps) - 1))
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.rows_visible:
            self.top = self.sel - self.rows_visible + 1

    def chosen(self) -> dict | None:
        return self.maps[self.sel] if self.maps else None

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(C_BG)
        self.font.draw(surf, f"SELECT MAP  ({len(self.maps)})", 8, 6, C_SEL)
        self.font.draw(surf, "UP/DOWN  ENTER load  X back", 8, 16, C_DIM)
        if not self.maps:
            self.font.draw(surf, "no rendered maps yet", 8, 40, C_DIM)
            return
        y = 32
        for i in range(self.top, min(self.top + self.rows_visible, len(self.maps))):
            m = self.maps[i]
            col = C_SEL if i == self.sel else C_WHITE
            if i == self.sel:
                pygame.draw.rect(surf, (40, 44, 88), (4, y - 1, LOGICAL_W - 8, 10))
            self.font.draw(surf, f"{m['id']:3} {m['name']}"[:30], 10, y, col)
            y += 11


class DialogueBox:
    """SNES-style bottom textbox with word-wrap + typewriter effect."""

    def __init__(self, font: BitmapFont, text: str):
        self.font = font
        self.max_chars = (LOGICAL_W - 24) // 8
        self.lines = font.wrap(text, self.max_chars)[:3]
        self.full = "\n".join(self.lines)
        self.shown = 0
        self.done = False

    def advance(self) -> bool:
        """Return True if the box wants to close."""
        if self.shown < len(self.full):
            self.shown = len(self.full)   # reveal all on button press
            return False
        return True

    def update(self) -> None:
        if self.shown < len(self.full):
            self.shown += 2  # 2 chars/frame typewriter
            self.done = self.shown >= len(self.full)

    def draw(self, surf: pygame.Surface) -> None:
        box = pygame.Rect(8, LOGICAL_H - 68, LOGICAL_W - 16, 60)
        pygame.draw.rect(surf, C_BOX, box)
        pygame.draw.rect(surf, C_BOX_BORDER, box, 2)
        shown_text = self.full[: self.shown]
        y = box.y + 8
        for line in shown_text.split("\n"):
            self.font.draw(surf, line, box.x + 8, y, C_WHITE)
            y += self.font.height + 4
        if self.shown >= len(self.full):
            self.font.draw(surf, "+", box.right - 16, box.bottom - 12, C_SEL)


class DataMenu:
    """Scrollable listing of a real data table (weapons / alchemy)."""

    TABS = [("weapon", "Weapon Name", "Attack Power", "ATK"),
            ("alchemy", "Alchemy Name", "Spell Might Value", "MGT")]

    def __init__(self, font: BitmapFont):
        self.font = font
        self.tab = 0
        self.sel = 0
        self.top = 0
        self.rows_visible = 10

    def _rows(self):
        table, name_k, val_k, _ = self.TABS[self.tab]
        return assets.data(table), name_k, val_k

    def move(self, d: int) -> None:
        rows, *_ = self._rows()
        self.sel = max(0, min(self.sel + d, len(rows) - 1))
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.rows_visible:
            self.top = self.sel - self.rows_visible + 1

    def switch_tab(self) -> None:
        self.tab = (self.tab + 1) % len(self.TABS)
        self.sel = self.top = 0

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill(C_BG)
        rows, name_k, val_k = self._rows()
        _, _, _, val_label = self.TABS[self.tab]
        title = self.TABS[self.tab][0].upper()
        self.font.draw(surf, f"{title}  ({len(rows)})", 8, 6, C_SEL)
        self.font.draw(surf, "TAB switch  UP/DOWN  X close", 8, 16, C_DIM)
        y = 32
        for i in range(self.top, min(self.top + self.rows_visible, len(rows))):
            r = rows[i]
            col = C_SEL if i == self.sel else C_WHITE
            if i == self.sel:
                pygame.draw.rect(surf, (40, 44, 88), (4, y - 1, LOGICAL_W - 8, 10))
            name = str(r.get(name_k, "?"))[:22]
            self.font.draw(surf, name, 10, y, col)
            self.font.draw(surf, f"{val_label} {r.get(val_k, '-')}", 180, y, col)
            y += 16
        # detail line for selection
        r = rows[self.sel]
        desc = str(r.get("Description") or r.get("Alchemy Description") or "")
        for j, line in enumerate(self.font.wrap(desc, 30)[:2]):
            self.font.draw(surf, line, 10, 206 - (1 - j) * 10, C_DIM)


class Game:
    """Owns the window, the logical surface and the state stack."""

    # Zoom limits (pixel magnification); + / - step in whole levels.
    ZOOM_MIN, ZOOM_MAX = 1, 8

    def __init__(self, headless: bool = False):
        pygame.init()
        self.headless = headless
        self.zoom = SCALE                       # pixel magnification, changed by + / -
        self.fullscreen = False
        self._windowed_size = (LOGICAL_W * SCALE, LOGICAL_H * SCALE)
        # Headless also needs a display surface (convert_alpha); with the dummy
        # SDL driver set_mode does not create a real window.
        flags = 0 if headless else pygame.RESIZABLE
        self.screen = pygame.display.set_mode(self._windowed_size, flags)
        if not headless:
            pygame.display.set_caption("Secret of Evermore - Viewer")
        # canvas = logical render surface; its size depends on the state (dynamic
        # for the map view, fixed 256x224 for the menu/UI states). Recreated in
        # draw() when needed.
        self.canvas = pygame.Surface((LOGICAL_W, LOGICAL_H))
        self.clock = pygame.time.Clock()
        self.font = BitmapFont()
        self.running = True
        # state stack: strings identify states; overlays stack on top
        self.state = "title"          # title | mapselect | mapview | menu
        self.dialogue: DialogueBox | None = None
        self.menu: DataMenu | None = None
        self.mapselect: MapSelect | None = None
        self.mapview: MapView | None = None
        # real story dialogue from the ROM (dialogue.json), in order
        self.story = assets.story_lines()
        self._story_i = 0
        self._dialogue_idx = 200      # fall back to item strings if there is no dialogue
        self.blip = _load_blip()      # short sound effect (real ROM instrument) or None

    # -- input ------------------------------------------------------------
    def _open_dialogue(self) -> None:
        if self.story:
            text = self.story[self._story_i % len(self.story)]
            self._story_i += 1
        else:
            text = assets.sample_string(self._dialogue_idx)
            self._dialogue_idx += 37
        self.dialogue = DialogueBox(self.font, text)
        if self.blip:
            self.blip.play()

    _CONFIRM = (pygame.K_RETURN, pygame.K_z, pygame.K_SPACE)
    _BACK = (pygame.K_x, pygame.K_ESCAPE)

    # Zoom/display keys act globally, in every state.
    _ZOOM_IN = (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS)
    _ZOOM_OUT = (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_UNDERSCORE)

    def set_zoom(self, z: int) -> None:
        self.zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, z))

    def toggle_fullscreen(self) -> None:
        if self.headless:
            return
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self._windowed_size = self.screen.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self._windowed_size, pygame.RESIZABLE)

    def handle_key(self, key: int) -> None:
        if key in self._ZOOM_IN:
            self.set_zoom(self.zoom + 1)
            return
        if key in self._ZOOM_OUT:
            self.set_zoom(self.zoom - 1)
            return
        if key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        if self.dialogue is not None:
            if key in self._CONFIRM and self.dialogue.advance():
                self.dialogue = None
            return
        getattr(self, f"_key_{self.state}", lambda _k: None)(key)

    def _key_title(self, key: int) -> None:
        if key in self._CONFIRM:
            self.mapselect = MapSelect(self.font)
            self.state = "mapselect"

    def _key_mapselect(self, key: int) -> None:
        if key == pygame.K_UP:
            self.mapselect.move(-1)
        elif key == pygame.K_DOWN:
            self.mapselect.move(1)
        elif key in self._CONFIRM and self.mapselect.chosen():
            self.mapview = MapView(self.mapselect.chosen())
            self.state = "mapview"
        elif key in self._BACK:
            self.state = "title"

    def _key_mapview(self, key: int) -> None:
        if key in self._CONFIRM:
            self._open_dialogue()
        elif key == pygame.K_m:
            self.menu = DataMenu(self.font)
            self.state = "menu"
        elif key in self._BACK:
            self.state = "mapselect"

    def _key_menu(self, key: int) -> None:
        if key == pygame.K_UP:
            self.menu.move(-1)
        elif key == pygame.K_DOWN:
            self.menu.move(1)
        elif key == pygame.K_TAB:
            self.menu.switch_tab()
        elif key in (pygame.K_x, pygame.K_ESCAPE, pygame.K_m):
            self.state = "mapview"

    # -- per-frame --------------------------------------------------------
    def update(self) -> None:
        if self.dialogue is not None:
            self.dialogue.update()
            return
        if self.state == "mapview" and self.mapview is not None:
            keys = pygame.key.get_pressed()
            dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
            dy = keys[pygame.K_DOWN] - keys[pygame.K_UP]
            if dx or dy:
                self.mapview.move(dx, dy)

    # States that use the full viewport (window/zoom); the rest renders at a
    # fixed SNES resolution and is scaled up to fill the window.
    _DYNAMIC_STATES = ("mapview",)

    def _canvas_for(self, state: str) -> pygame.Surface:
        """Logical render surface for the state. Map view: window//zoom (so
        maximizing + zooming out shows more map); UI: fixed 256x224."""
        if state in self._DYNAMIC_STATES:
            ww, wh = self.screen.get_size()
            cw = max(LOGICAL_W, ww // self.zoom)
            ch = max(LOGICAL_H, wh // self.zoom)
        else:
            cw, ch = LOGICAL_W, LOGICAL_H
        if self.canvas.get_size() != (cw, ch):
            self.canvas = pygame.Surface((cw, ch))
        return self.canvas

    def draw(self) -> None:
        c = self._canvas_for(self.state)
        if self.state == "title":
            c.fill(C_BG)
            self.font.draw_centered(c, "SECRET OF", LOGICAL_W // 2, 60, C_WHITE)
            self.font.draw_centered(c, "EVERMORE", LOGICAL_W // 2, 76, C_SEL)
            self.font.draw_centered(c, "pygame viewer", LOGICAL_W // 2, 110, C_DIM)
            self.font.draw_centered(c, "ENTER  MAP VIEWER", LOGICAL_W // 2, 160, C_DIM)
        elif self.state == "mapselect":
            self.mapselect.draw(c)
        elif self.state == "menu":
            self.menu.draw(c)
        else:  # mapview (also base for dialogue overlay)
            self.mapview.draw(c, self.font)
            self.font.draw(c, "Z talk  M menu  X back  +/- zoom  F11 fullscreen",
                           6, c.get_height() - 12, C_DIM)
            if self.dialogue is not None:
                self.dialogue.draw(c)
        self._present(c)
        pygame.display.flip()

    def _present(self, c: pygame.Surface) -> None:
        """Put the canvas on the window. Dynamic states: integer x zoom
        (sharp pixels), centered, black border. UI states: fill the window."""
        self.screen.fill((0, 0, 0))
        ww, wh = self.screen.get_size()
        if self.state in self._DYNAMIC_STATES:
            cw, ch = c.get_size()
            scaled = pygame.transform.scale(c, (cw * self.zoom, ch * self.zoom))
            self.screen.blit(scaled, ((ww - scaled.get_width()) // 2,
                                      (wh - scaled.get_height()) // 2))
        else:
            pygame.transform.scale(c, (ww, wh), self.screen)

    # -- loops ------------------------------------------------------------
    def run(self) -> None:
        while self.running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.running = False
                elif e.type == pygame.VIDEORESIZE and not self.fullscreen:
                    self.screen = pygame.display.set_mode((e.w, e.h), pygame.RESIZABLE)
                elif e.type == pygame.KEYDOWN:
                    self.handle_key(e.key)
            self.update()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()

    def selftest(self, out_path: str, ticks: int = 90) -> None:
        """Headless: drive a scripted session, render frames, save a proof frame."""
        script = {2: pygame.K_RETURN,          # title -> mapselect
                  6: pygame.K_RETURN,          # load first map -> mapview
                  55: pygame.K_z}              # open dialogue on the real map
        for t in range(ticks):
            if t in script:
                self.handle_key(script[t])
            # walk across the loaded map a few frames
            if 12 <= t <= 40 and self.state == "mapview" and self.mapview is not None:
                self.mapview.move(1, 1)
            self.update()
            self.draw()
        pygame.image.save(self.canvas, out_path)
        pygame.quit()
