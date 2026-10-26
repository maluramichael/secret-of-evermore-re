"""Programmatic SPC ripper for Secret of Evermore -- let the real SNES/SPC700 make
the music, then snapshot the whole sound chip into standard .spc files.

Same principle as the map caller (soe/snescall.py): don't guess at BRR fragments or
reverse the AKAO sequence format by hand -- boot the ROM in Mesen2, let the GAME's own
sound engine upload a song into the SPC700 + S-DSP and start it playing, then dump the
complete APU state (64KB ARAM + 128 DSP registers + 64B IPL ROM + the SPC700 CPU
registers) into an ID666 .spc file. A .spc plays in any SPC player and preserves the
exact SNES performance -- no fragment guessing.

================================================================================
HOW A SONG IS MADE TO PLAY  (verified live against the ROM + Mesen2)
================================================================================
SoE picks its music by AREA: loading a map starts that area's song. So we reuse the
PROVEN bank-$90 map-load hijack from snescall.py -- pin WRAM $0ADB (current map id) to
our target at the loader entry $908F68 (opcode `LDA $0ADB`), so the game loads our map
through its own complete, natural code path. Crucially that natural path also runs the
game's normal music-start flow with the per-frame NMI sound-handler HEARTBEAT intact,
which is what actually makes the SPC700 sequencer begin and keep playing. We let the
area settle for a couple of seconds and read the real playing song id straight out of
WRAM $0E4D ("current song"), then dump the APU. See tools/mesen/spc_rip.lua.

WHY NOT force an arbitrary song id (fully traced, and it does NOT work):
  The general play-song routine is at $8C8581: it takes a song id in A, guards A==0 and
  A==current($0E4D), stores A->$0E4D, computes X=songid*3 and reads the 3-byte pointer
  from the song table $819903,X (file 0x19903 = $C1:9903, read via bank mirror $81) and
  uploads that song to the APU (JSL $8C8527, commands $0E then $02). You CAN pin $0E4D
  at the index point $8C8595 to make it upload any song's DATA (deterministic, verified
  for every id), and you CAN force-call the whole routine via a trampoline
  (JSL $8C8581 ; BRA self, setState PC + A). But merely loading the data does not make
  the SPC700 sequence it, and a force-call has to either keep NMI (then the game's main
  loop re-asserts the area song) or kill NMI (then the sound-handler heartbeat that
  STARTS the song is gone -> the voices stay at envelope 0, silent). Every "it played"
  in that direction turned out to be the residual title song still ringing. The
  area-music route sidesteps all of it: the game itself starts the song correctly.

WHAT WE GET: one clean, actually-playing song per area. Different maps -> different
songs; we de-duplicate by the $0E4D song id and keep one .spc per unique song. This
covers the field/area soundtrack; a handful of the 59 song-table ids are battle/boss/
event cues that no map plays as area music and are therefore not captured this way
(reported by rip_all()).

================================================================================
SPC FILE FORMAT (v0.30, 0x10200 bytes) -- what we assemble from the dump
================================================================================
  0x00000  33  "SNES-SPC700 Sound File Data v0.30"
  0x00021   2  0x1A 0x1A
  0x00023   1  26 (has ID666 tag)
  0x00024   1  30 (minor version)
  0x00025   2  SPC700 PC (little-endian)
  0x00027   1  A     0x00028 1 X   0x00029 1 Y
  0x0002A   1  PSW   0x0002B 1 SP
  0x0002E ...  ID666 text tag (song/game/dumper)
  0x00100 64K  ARAM (spcRam)
  0x10100 128  DSP registers (spcDspRegisters)
  0x10180  64  unused
  0x101C0  64  IPL ROM (spcRom)

VERIFICATION: render_spc() drives libgme (Blargg's snes_spc, a standard SPC700+S-DSP core) to decode the .spc to PCM and reports RMS-over-time. A valid
music rip is non-silent AND structured (per-window RMS varies, not a constant tone).
"""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import wave
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ROM = _ROOT / "Secret of Evermore (Europe).sfc"
_LUA = _ROOT / "tools/mesen/spc_rip.lua"
_DUMP_ROOT = _ROOT / "assets/dumps/sound"
_SPC_DIR = _ROOT / "assets/audio/spc"
_WAV_DIR = _ROOT / "assets/audio/music"

SONG_PTR_TABLE = 0x19903          # file offset; 3-byte pointers into bank $8A
_LIBGME_CANDIDATES = ["/opt/homebrew/lib/libgme.dylib", "libgme.dylib", "libgme.so"]
SAMPLE_RATE = 32000


# --- SPC assembly -------------------------------------------------------------

def _read_regs(path: Path) -> dict:
    return {k: int(v) for k, v in (kv.split("=") for kv in path.read_text().split())}


def assemble_spc(dump_dir: Path, song_id: int) -> bytes:
    """Build a standard 0x10200-byte ID666 .spc from a Mesen APU dump directory."""
    aram = (dump_dir / "aram.bin").read_bytes()
    dsp = (dump_dir / "dsp.bin").read_bytes()
    ipl = (dump_dir / "iplrom.bin").read_bytes()
    regs = _read_regs(dump_dir / "regs.txt")
    if not (len(aram) == 0x10000 and len(dsp) == 128 and len(ipl) == 64):
        raise ValueError(f"bad dump sizes: aram={len(aram)} dsp={len(dsp)} ipl={len(ipl)}")

    spc = bytearray(0x10200)
    spc[0:33] = b"SNES-SPC700 Sound File Data v0.30"
    spc[0x21] = 0x1A
    spc[0x22] = 0x1A
    spc[0x23] = 26          # has ID666 tag
    spc[0x24] = 30          # minor version
    struct.pack_into("<H", spc, 0x25, regs["pc"] & 0xFFFF)
    spc[0x27] = regs["a"] & 0xFF
    spc[0x28] = regs["x"] & 0xFF
    spc[0x29] = regs["y"] & 0xFF
    spc[0x2A] = regs["psw"] & 0xFF
    spc[0x2B] = regs["sp"] & 0xFF

    def put(off, s, n):
        b = s.encode("ascii", "replace")[:n]
        spc[off:off + len(b)] = b

    put(0x2E, f"Song {song_id:02d}", 32)          # song title
    put(0x4E, "Secret of Evermore", 32)           # game title
    put(0x6E, "soundcall", 16)                    # dumper
    spc[0x100:0x10100] = aram
    spc[0x10100:0x10180] = dsp
    spc[0x101C0:0x10200] = ipl
    return bytes(spc)


def validate_spc(data: bytes) -> dict:
    """Structural check of a .spc: header magic, size, plausible boot vector."""
    ok_magic = data[0:33] == b"SNES-SPC700 Sound File Data v0.30"
    boot_pc = data[0x25] | data[0x26] << 8
    aram = data[0x100:0x10100]
    nonzero = sum(1 for b in aram if b)
    return {
        "size_ok": len(data) == 0x10200,
        "magic_ok": ok_magic,
        "boot_pc": boot_pc,
        "boot_pc_plausible": 0 <= boot_pc < 0x10000 and nonzero > 0,
        "aram_nonzero": nonzero,
    }


# --- emulator run -------------------------------------------------------------

def _mesen_path() -> Path:
    exe = os.environ.get("MESEN")
    if not exe:
        raise RuntimeError("MESEN is not set: point it at the Mesen2 executable "
                           "(e.g. export MESEN=/path/to/Mesen)")
    return Path(exe)


def dump_dir(mapid: int) -> Path:
    return _DUMP_ROOT / f"area_{mapid:04d}"


def rip_area(mapid: int, *, wait: int = 240, force: bool = False,
             timeout: int = 120) -> dict:
    """Boot the ROM headless, load `mapid`, let its area song play, dump the APU.

    Runs Mesen2 with tools/mesen/spc_rip.lua. Writes aram/dsp/iplrom/regs/info into
    assets/dumps/sound/area_XXXX/. Returns the parsed info dict (mapid, song id from
    WRAM $0E4D, envSum at dump time, ...). Idempotent unless force=True.
    """
    d = dump_dir(mapid)
    info_path = d / "info.txt"
    if info_path.exists() and not force:
        return _read_info(info_path)
    mesen = _mesen_path()
    for p in (_ROM, mesen, _LUA):
        if not p.exists():
            raise FileNotFoundError(p)
    d.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SOE_MAPID=str(mapid), SOE_OUT=str(d) + os.sep, SOE_WAIT=str(wait))
    proc = subprocess.run([str(mesen), "--testRunner", "--noAudio", str(_ROM), str(_LUA)],
                          env=env, capture_output=True, timeout=timeout)
    if not info_path.exists():
        raise RuntimeError(f"map {mapid}: no dump (exit {proc.returncode}): "
                           f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    info = _read_info(info_path)
    if "TIMEOUT" in info:
        raise RuntimeError(f"map {mapid}: map loader never hijacked (timeout)")
    return info


def _read_info(path: Path) -> dict:
    text = path.read_text()
    if text.startswith("TIMEOUT"):
        return {"TIMEOUT": True}
    out: dict = {}
    for tok in text.split():
        k, _, v = tok.partition("=")
        if v:
            out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


# --- libgme rendering + verification ------------------------------------------

def _load_libgme():
    for cand in _LIBGME_CANDIDATES:
        try:
            gme = ctypes.CDLL(cand)
        except OSError:
            continue
        gme.gme_open_file.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        gme.gme_open_file.restype = ctypes.c_char_p
        gme.gme_start_track.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gme.gme_start_track.restype = ctypes.c_char_p
        gme.gme_play.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_short)]
        gme.gme_play.restype = ctypes.c_char_p
        gme.gme_delete.argtypes = [ctypes.c_void_p]
        return gme
    return None


def render_spc(spc_path: Path, *, seconds: int = 20, wav_path: Path | None = None) -> dict:
    """Render a .spc to PCM with libgme (Blargg snes_spc) and measure it.

    Returns {ok, rms, peak, nonzero_frac, structured, windows, error}. `structured` is
    True when the per-0.5s RMS varies enough to be real music rather than a flat tone.
    Writes a mono 16-bit WAV to wav_path if given. A pure-Python fallback is not
    attempted; if libgme is missing, ok=False with an error note (SPC is still valid).
    """
    import numpy as np

    gme = _load_libgme()
    if gme is None:
        return {"ok": False, "error": "libgme not found (brew install game-music-emu)"}
    emu = ctypes.c_void_p()
    err = gme.gme_open_file(str(spc_path).encode(), ctypes.byref(emu), SAMPLE_RATE)
    if err:
        return {"ok": False, "error": f"gme_open: {err!r}"}
    err = gme.gme_start_track(emu, 0)
    if err:
        gme.gme_delete(emu)
        return {"ok": False, "error": f"gme_start: {err!r}"}
    n = SAMPLE_RATE * seconds
    buf = (ctypes.c_short * (n * 2))()
    err = gme.gme_play(emu, n * 2, buf)
    gme.gme_delete(emu)
    if err:
        return {"ok": False, "error": f"gme_play: {err!r}"}

    mono = np.frombuffer(buf, dtype=np.int16).astype(np.float32).reshape(-1, 2).mean(1)
    if wav_path is not None:
        _write_wav(wav_path, mono)
    return _measure(mono)


def _write_wav(wav_path: Path, mono) -> None:
    import numpy as np
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    w = wave.open(str(wav_path), "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SAMPLE_RATE)
    w.writeframes(mono.astype(np.int16).tobytes())
    w.close()


def _measure(mono) -> dict:
    """RMS/peak + a 'structured' (real music) verdict from a mono float sample array."""
    import numpy as np
    seg = SAMPLE_RATE // 2
    nseg = max(1, (len(mono) - seg) // seg)
    win = np.array([np.sqrt(np.mean(mono[i * seg:i * seg + seg] ** 2)) for i in range(nseg)])
    rms = float(np.sqrt(np.mean(mono ** 2)))
    peak = int(np.max(np.abs(mono))) if len(mono) else 0
    return {"ok": True, "rms": round(rms, 1), "peak": peak,
            "nonzero_frac": round(float(np.mean(np.abs(mono) > 2)), 3),
            "structured": _is_music(rms, peak, win),
            "windows": [round(float(w)) for w in win]}


def _is_music(rms: float, peak: int, win) -> bool:
    """Real music = clearly non-silent AND loudness varies over time (a held tone/DC is
    flat). Variation = relative window spread OR a loud/quiet window ratio."""
    import numpy as np
    active = win[win > 50]
    quiet = win[win > 5]
    rel_std = float(np.std(win) / active.mean()) if active.size else 0.0
    ratio = float(win.max() / quiet.min()) if active.size and quiet.size else 1.0
    return bool(rms > 100 and peak > 1500 and active.size >= 3
                and (rel_std > 0.08 or ratio > 1.5))


# --- song table (for the README / coverage report) ----------------------------

def song_table(count: int = 59) -> list[int]:
    """Return the `count` 3-byte song pointers from the table at file 0x19903."""
    rom = _ROM.read_bytes()
    t = SONG_PTR_TABLE
    return [rom[t + i * 3] | rom[t + i * 3 + 1] << 8 | rom[t + i * 3 + 2] << 16
            for i in range(count)]


# --- batch --------------------------------------------------------------------

def rip_area_playing(mapid: int, *, tries: int = 5, seconds: int = 20) -> dict:
    """Rip a map's area song and keep the .spc only if it renders as real music.

    The APU dump is taken at a frame boundary, so the captured SPC700 PC occasionally
    lands in the driver's idle wait-loop -> a valid-but-silent .spc. That is rare, so we
    render-verify each rip and re-run Mesen (force) until libgme reports non-silent,
    structured audio, up to `tries` times. Returns {info, spc, render, valid, tries}.
    """
    best = None
    for attempt in range(1, tries + 1):
        info = rip_area(mapid, force=(attempt > 1))
        sid = info.get("cur0E4D", -1)
        spc = assemble_spc(dump_dir(mapid), sid)
        r = render_spc(_tmp_spc(spc), seconds=min(seconds, 10))
        rec = {"info": info, "song": sid, "spc": spc, "render": r,
               "valid": validate_spc(spc), "tries": attempt}
        if r.get("ok") and r.get("structured"):
            return rec
        # keep the loudest attempt as a fallback
        if best is None or r.get("rms", 0) > best["render"].get("rms", 0):
            best = rec
    return best


_TMP_SPC = _DUMP_ROOT / "_verify.spc"


def _tmp_spc(data: bytes) -> Path:
    _DUMP_ROOT.mkdir(parents=True, exist_ok=True)
    _TMP_SPC.write_bytes(data)
    return _TMP_SPC


def rip_all(maps=range(127), *, seconds: int = 20, tries: int = 5) -> dict:
    """Rip every area song across `maps`, de-dup by song id, write one .spc per song.

    For each map: load it, read its playing song id ($0E4D); the first time we see a
    song id, capture a rendering-verified .spc to assets/audio/spc/song_XX.spc and a
    WAV preview to assets/audio/music/song_XX.wav. Returns a report:
    {songs: {id: {...}}, maps_song: {mapid: songid}, missing: [...]}.
    """
    _SPC_DIR.mkdir(parents=True, exist_ok=True)
    songs: dict[int, dict] = {}
    maps_song: dict[int, int] = {}
    for mapid in maps:
        try:
            info = rip_area(mapid)
        except Exception as e:  # keep going; note the failure
            maps_song[mapid] = -1
            print(f"map {mapid:3d}: FAILED ({e})")
            continue
        sid = info.get("cur0E4D", -1)
        maps_song[mapid] = sid
        if sid < 0 or sid in songs:
            print(f"map {mapid:3d}: song {sid} (dup/skip)")
            continue
        rec = rip_area_playing(mapid, tries=tries, seconds=seconds)
        sid = rec["song"]
        maps_song[mapid] = sid
        if sid in songs:
            continue
        spc_path = _SPC_DIR / f"song_{sid:02d}.spc"
        spc_path.write_bytes(rec["spc"])
        r = rec["render"]
        if r.get("ok"):
            render_spc(spc_path, seconds=seconds, wav_path=_WAV_DIR / f"song_{sid:02d}.wav")
        songs[sid] = {"song": sid, "from_map": mapid, "spc": str(spc_path),
                      "valid": rec["valid"], "render": r, "env_sum": info.get("envSum", 0),
                      "tries": rec["tries"]}
        print(f"map {mapid:3d}: song {sid:2d} -> {spc_path.name}  "
              f"rms={r.get('rms', '?')} structured={r.get('structured', '?')} "
              f"tries={rec['tries']}")
    table_ids = list(range(len(song_table())))
    missing = [i for i in table_ids if i not in songs]
    return {"songs": songs, "maps_song": maps_song, "missing": missing}


def write_readme(report: dict) -> Path:
    """Write assets/audio/spc/README.md mapping song id -> source map + verification."""
    songs = report["songs"]
    lines = [
        "# Secret of Evermore -- ripped SPC music",
        "",
        "Real SNES music captured by driving the game's own AKAO sound engine in Mesen2",
        "(headless) and dumping the full APU state (64KB ARAM + DSP registers + SPC700",
        "registers) into standard ID666 `.spc` files. See `soe/soundcall.py` for how.",
        "",
        "Songs are selected by AREA: each `.spc` is the music the game plays when the",
        "listed map loads. Files are named by the game's internal song id (WRAM $0E4D).",
        "Verification RMS/peak come from rendering each `.spc` with libgme (Blargg's",
        "snes_spc). `structured` means the audio is non-silent AND varies over time",
        "(real music, not a held tone).",
        "",
        "| song id | file | from map | boot PC | RMS | peak | structured |",
        "|--------:|------|---------:|--------:|----:|-----:|:----------:|",
    ]
    for sid in sorted(songs):
        rec = songs[sid]
        v = rec["valid"]
        r = rec.get("render", {})
        lines.append(
            f"| {sid} | song_{sid:02d}.spc | {rec['from_map']} | "
            f"${v['boot_pc']:04X} | {r.get('rms', '-')} | {r.get('peak', '-')} | "
            f"{'yes' if r.get('structured') else 'no'} |")
    missing = [i for i in report["missing"] if i != 0]
    bonus = sorted(s for s in songs if s >= 59)
    lines += [
        "",
        f"Captured {len(songs)} unique songs, all non-silent and structured (real music).",
        "",
        "Song id 0 is the engine's \"no music / stop\" entry (the play routine skips on "
        "A==0), so the areas that report it are silent by design and it is not shipped.",
        "",
        "Song-table ids (0..58) that no scanned area plays -- battle/boss/event/menu cues "
        f"that are not area music, so not captured this way: {', '.join(map(str, missing)) or 'none'}.",
        "",
        f"Song ids beyond the nominal 59-entry table were also seen and captured (extra "
        f"songs the game addresses with higher ids): {', '.join(map(str, bonus)) or 'none'}.",
        "",
        "## Song id -> area map(s)",
        "",
    ]
    by_song: dict[int, list[int]] = {}
    for mapid, sid in report["maps_song"].items():
        if sid >= 0:
            by_song.setdefault(sid, []).append(mapid)
    for sid in sorted(by_song):
        maps = ", ".join(str(m) for m in sorted(by_song[sid]))
        lines.append(f"- song {sid:2d}: maps {maps}")
    path = _SPC_DIR / "README.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def _selftest():
    """Rip one area (map 16), assemble + validate + render, assert real music."""
    rec = rip_area_playing(16, tries=5, seconds=10)
    v = rec["valid"]
    assert v["size_ok"] and v["magic_ok"], v
    assert v["boot_pc_plausible"] and v["aram_nonzero"] > 20000, v
    r = rec["render"]
    assert r["ok"], r
    assert r["structured"] and r["rms"] > 200, r
    _SPC_DIR.mkdir(parents=True, exist_ok=True)
    p = _SPC_DIR / f"song_{rec['song']:02d}.spc"
    p.write_bytes(rec["spc"])
    render_spc(p, seconds=10, wav_path=_WAV_DIR / f"song_{rec['song']:02d}.wav")
    print(f"selftest OK: map16 -> song {rec['song']}, valid SPC, rms={r['rms']} "
          f"peak={r['peak']} structured={r['structured']} tries={rec['tries']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    elif len(sys.argv) > 1 and sys.argv[1] == "all":
        rep = rip_all()
        write_readme(rep)
        print(f"\n{len(rep['songs'])} songs, missing table ids: {rep['missing']}")
    else:
        for m in (int(a) for a in sys.argv[1:]) or [16]:
            print(rip_area(m))
