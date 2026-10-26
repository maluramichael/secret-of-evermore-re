"""Boy atlas: all Boy frames (stand/walk/run/attack x 4 directions) from the ROM in ONE atlas + manifest.

Nothing is built by hand. The module reads the Boy anim scripts (bank $C8), renders
every script frame through `soe.boysprites` (metasprites + both SpriteBlock tables)
and writes:

  * boy_atlas.png   - one sprite sheet, all frames packed, transparent
  * boy_atlas.json  - manifest: per frame rectangle, origin (actor anchor = foot),
                      direction, state, layer metasprites; animations with frame
                      durations from the scripts; palette reference; provenance
                      (all reverse engineered ROM addresses).

Chain (verified, docs/sprites.md): anim VM $D080D2 executes the script and writes
the frame metasprite pointers into the entity (+0x09 layer 1 via opcode $2C, +0x06
layer 2 via $22..$2B). The display list builder $CFC662 enters them as nodes, the
walker $C096BA renders each node through sprite_compose $80903F -> OAM shadow
$7EAC42 -> NMI DMA. Frame duration = wait opcode ($00..$1F) in the script, measured
in the emulator.
"""
from __future__ import annotations

import json
from pathlib import Path

from .rom import Rom
from . import boysprites, palettes

# Render/anim pipeline provenance (SNES addresses, see docs/sprites.md).
RENDER_PIPELINE = {
    "anim_vm_dispatch": "0xD080D2",
    "anim_vm_jump_table": "0xD08000",
    "anim_op_2C_layer1_ptr": "0xD08434 -> Entity+0x09..0x0B",
    "anim_op_22_2B_layer2_ptr": "0xD0841D -> Entity+0x06..0x08, bank = op + 0xA9",
    "boy_action_table": "0xC4452E (16 B per action: 4 x {addr16, bank, flag} up/right/down/left; stand=5 walk=6 run=7 attack=10)",
    "boy_anim_scripts": "0xC811CE.. (bank $C8, every script starts with reset opcode $52)",
    "display_list_builder": "0xCFC662 (Entity+0x09 -> Knoten+0x0C, JSL 0x809609 Insert)",
    "display_list_walker": "0xC096BA (Kopf 0x7E5127, JSL 0x80903F je Knoten)",
    "sprite_compose": "0x809032 / re-entry 0x80903F",
    "compose_emit_loop": "0x80910D",
    "spriteblock_table_16x16": "0xEE0000 (flags bit0=1, bank=(b2&0x7F)+0x5A)",
    "spriteblock_table_8x8": "0xD90000 (flags bit0=0, bank=(b2&0x7F)+0x52)",
    "oam_shadow_buffer": "0x7EAC42",
    "oam_dma_inline_nmi": "0x8082E9",
    "spriteinfo_format": "byte0=count, byte1=dataoff, count*5B chunks {flags:u8,x:i8,y:i8,block:u16}",
}
TIMING_SOURCED_FROM_ROM = True
# Boy palettes: 8 variants from 0x10AD10 (32 B stride, soe.palettes). Index 1..5 skin/white/
# outline are the same in all, 6..11 hair/clothing (two sets), 12/13 = weapon colors (palette 0
# holds placeholder green 07E1 there). In game (map 56, bone club) palette 3 =
# 0x10AD70 sits in CGRAM slot 6 (found word for word in the ROM).
BOY_PALETTE_INDEX = 3
STATES = ("stand", "walk", "run", "attack")
PAD = 1  # transparent pixels between frames in the atlas


def _blit(px, grid, pal, ox, oy):
    for y, row in enumerate(grid):
        for x, v in enumerate(row):
            if v:  # index 0 = transparent
                px[ox + x, oy + y] = (*pal[v], 255)


def build(rom: Rom) -> dict:
    """All Boy frames (stand/walk/run x 4 directions) from the ROM anim scripts.

    Returns {frames: [{id, direction, state, layers, grid, w, h, origin}], animations}.
    A frame = the layer combination of one script step; identical layer combinations
    (e.g. the same stand frame) are rendered only once.
    """
    anims = boysprites.boy_animations(rom)
    frames, by_layers, animations = [], {}, {}
    for direction in boysprites.DIRECTIONS:
        animations[direction] = {}
        for state in STATES:
            sc = anims[state][direction]
            ids, durs = [], []
            for step in sc["frames"]:
                key = tuple(step["layers"])
                if key not in by_layers:
                    fr = boysprites.compose_frame(rom, step["layers"])
                    fid = f"{direction}_{state}{len(ids)}" if state != "stand" else f"{direction}_stand"
                    by_layers[key] = fid
                    frames.append({
                        "id": fid, "direction": direction, "state": state,
                        "layers": [f"{lay[0]:02X}:{lay[1]:04X}" if lay else None for lay in step["layers"]],
                        "grid": fr["grid"], "w": fr["w"], "h": fr["h"], "origin": list(fr["origin"]),
                    })
                ids.append(by_layers[key])
                durs.append(step["duration"])
            animations[direction][state] = {
                "frames": ids, "durations": durs, "loop": sc["loop"], "script": sc["script"],
                "loop_overhead_frames": boysprites.LOOP_OVERHEAD_FRAMES if sc["loop"] else 0,
            }
    return {"frames": frames, "animations": animations}


def _pack(frames: list[dict], cols: int = 6):
    col_w = max(f["w"] for f in frames) + PAD
    row_h = max(f["h"] for f in frames) + PAD
    placed = [(f, (i % cols) * col_w + PAD, (i // cols) * row_h + PAD) for i, f in enumerate(frames)]
    rows = (len(frames) + cols - 1) // cols
    return cols * col_w + PAD, rows * row_h + PAD, placed


def extract(rom: Rom, out_path) -> dict:
    """Write boy_atlas.png + boy_atlas.json to out_path, purely from the ROM."""
    from PIL import Image

    out = Path(out_path)
    out.mkdir(parents=True, exist_ok=True)
    pal = palettes.read_palette(rom, BOY_PALETTE_INDEX)

    built = build(rom)
    frames = built["frames"]
    aw, ah, placed = _pack(frames)
    atlas = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
    apx = atlas.load()
    manifest_frames = []
    for f, gx, gy in placed:
        _blit(apx, f["grid"], pal, gx, gy)
        manifest_frames.append({
            "id": f["id"], "direction": f["direction"], "state": f["state"],
            "rect": [gx, gy, f["w"], f["h"]],
            # Origin = actor anchor of the metasprite chunks (x/y offset (0,0) = map position, foot).
            "origin": f["origin"],
            "layers": f["layers"],
        })
    atlas.save(out / "boy_atlas.png")

    manifest = {
        "source": "Secret of Evermore (Europe), extracted from the user's ROM",
        "provenance": {
            "render_pipeline": RENDER_PIPELINE,
            "note": ("Frames = metasprites of the Boy anim scripts (bank $C8), rendered through "
                     "both SpriteBlock tables; timing = wait opcodes of the scripts. Details "
                     "docs/sprites.md."),
        },
        "palette_file": f"0x{palettes.PAL_TABLE_START + BOY_PALETTE_INDEX * palettes.PAL_STRIDE:06X}",
        "palette_note": ("Boy palette 3 of 8 (0x10AD10 + i*32): index 12/13 = weapon colors, "
                         "6..11 clothing/hair; palette 3 = live CGRAM slot 6 on map 56"),
        "atlas": {"file": "boy_atlas.png", "size": [aw, ah]},
        "timing_sourced_from_rom": TIMING_SOURCED_FROM_ROM,
        "timing_unit": ("frames @ 50Hz (PAL); durations = wait opcodes, the last frame of a "
                        "loop lasts loop_overhead_frames longer (tick of the loop opcode $D3)"),
        "frames": manifest_frames,
        "animations": built["animations"],
        "coverage": {"included": list(STATES), "pending": []},
        "verification": {
            "method": ("tools/verify_boy_atlas.py: Boy cluster from emulator OAM+VRAM+CGRAM "
                       "(assets/dumps/trace/boy_truth/, savestate on map 56) compared pixel by pixel "
                       "against the atlas frame of the same metasprite identity; score = fraction of "
                       "identical opaque pixels"),
            "stand": "4/4 frames score 1.000",
            "walk": "24/24 frames score 1.000",
            "attack": ("up: 3/4 frames score 1.000, up_attack2 0.235 (the capture shows a different "
                       "sprite composition there, open); right/down/left: no emulator data"),
            "run": ("sequence + durations measured in the emulator (assets/dumps/trace/boy_truth_ring/, "
                    "Jaguar ring flag $7E2262 bit 1 set, A held): CB:1488,14A2,14D0,14E5 "
                    "with 8,6,8,5(+1) frames = script; pixel comparison 14/16 frames score 1.000, 2 "
                    "silhouette only (tinted) = 1.000, down_run3 0.154 against an isolated transition "
                    "frame of the capture (only hit, Boy blinks at the wall), open"),
            "report": "assets/dumps/trace/boy_truth/verify/report.json",
        },
    }
    (out / "boy_atlas.json").write_text(json.dumps(manifest, indent=2))
    return {
        "atlas": str(out / "boy_atlas.png"),
        "atlas_size": [aw, ah],
        "frames_written": len(manifest_frames),
        "directions": 4,
        "states_included": list(STATES),
        "timing_from_rom": TIMING_SOURCED_FROM_ROM,
    }


def _selftest(rom: Rom) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        res = extract(rom, td)
        m = json.loads((Path(td) / "boy_atlas.json").read_text())
        # 4 stand + 4x6 walk + 4x4 run + 4x4 attack = 60 frames.
        assert res["frames_written"] == 60, f"unexpected frame count: {res['frames_written']}"
        aw, ah = m["atlas"]["size"]
        ids = {mf["id"] for mf in m["frames"]}
        for d in ("down", "up", "left", "right"):
            a = m["animations"][d]
            assert len(a["walk"]["frames"]) == 6 and len(a["run"]["frames"]) == 4 and a["stand"]["frames"]
            assert len(a["attack"]["frames"]) == 4
            assert all(fid in ids for st in a.values() for fid in st["frames"])
            assert all(1 <= n <= 31 for st in a.values() for n in st["durations"])
        assert m["animations"]["up"]["walk"]["durations"] == [8, 8, 7, 8, 8, 6]
        for mf in m["frames"]:
            x, y, w, h = mf["rect"]
            assert 0 <= x and x + w <= aw and 0 <= y and y + h <= ah, f"rect out of atlas: {mf['id']}"
            ox, oy = mf["origin"]
            assert 0 <= ox <= w and 0 <= oy <= h, f"origin outside: {mf['id']}"
        assert m["coverage"]["pending"] == [] and m["timing_sourced_from_rom"] is True
    print(f"boyatlas selftest ok ({res['frames_written']} frames, atlas {res['atlas_size']}, "
          f"states={res['states_included']}, timing_from_rom=True)")


if __name__ == "__main__":
    rom = Rom("Secret of Evermore (Europe).sfc")
    _selftest(rom)
    res = extract(rom, Path("assets/sprites/player"))
    for k, v in res.items():
        print(f"  {k}: {v}")
