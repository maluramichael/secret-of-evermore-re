"""Audio (SNES BRR) -> WAV, via the AKAO sample references (real extraction).

SoE uses the Square/AKAO sound engine. The BRR instrument samples sit in four
ROM banks; the *music component data* (0xAA7BE..0xB8EF1, addressed by the
song pointer table @0x19903, 59 entries, 3-byte $8A pointers) references every
used sample by a 3-byte pointer to its BRR start.

Instead of guessing at the end flag (old heuristic -> 3 ms garbage), exactly
these referenced starts are collected, each is decoded as a complete BRR
sample, and only what can be cleanly justified is kept:
  * starts in filter 0 (S-DSP convention for a fresh sample),
  * decodes in 9-byte blocks up to an end flag inside its bank,
  * is long enough for a real tone (>= MIN_BLOCKS blocks),
  * overlaps no other kept sample (real samples are disjoint).

Result: whole instrument loops (tens to hundreds of ms), no fragments.

Limit (naive heuristic with a named ceiling): the exact loop points are in the
S-DSP DIR, which is loaded into ARAM per song, not in the ROM next to the
sample. `loops` (loop flag of the end block) is therefore reported, but
`loop_point` stays null. Upgrade path: reconstruct ARAM per song and read the
DIR, which gives exact loop offsets and SPC-style playback (song table
documented below).
"""
from __future__ import annotations
import json
import wave
from pathlib import Path

from .rom import Rom

SAMPLE_RATE = 32000               # SNES base rate at pitch 0x1000; the real pitch is per note
MIN_BLOCKS = 16                   # >= 16 blocks: a real tone instead of a click/fragment
MIN_RMS = 20                      # below ~20 RMS: silence / false hit, discard

# Music component data: holds the 3-byte pointers to the used samples.
COMPONENT_REGION = (0xAA7BE, 0xB8EF1)
# Song/sequence pointer table (3-byte SNES pointers, bank $8A) -> AKAO sequence data.
SONG_PTR_TABLE = 0x19903
# BRR sample banks (file offsets), region-independent.
SAMPLE_BANKS = [(0x18000, 0x1FFFF), (0x48000, 0x4FA71),
                (0x58000, 0x6FFFF), (0x78000, 0xA9FFF)]


def _selftest():
    d, _ = Rom.decode_brr(bytes([0x00] + [0x00] * 8), 0)
    assert d[:16] == [0] * 16
    d, _ = Rom.decode_brr(bytes([0x80, 0x10] + [0] * 7), 0)
    assert d[0] == 256, d[0]


def _bank_of(f: int):
    for a, b in SAMPLE_BANKS:
        if a <= f <= b:
            return (a, b)
    return None


def _brr_extent(data: bytes, start: int):
    """(start, end) of a clean BRR sample starting at `start`, else None.

    Must start in filter 0 and run in 9-byte blocks up to an end flag *inside*
    its bank.
    """
    if (data[start] >> 2) & 3 != 0:               # not filter 0 -> not a fresh sample start
        return None
    bank = _bank_of(start)
    if bank is None:
        return None
    pos = start
    while pos + 9 <= bank[1] + 1:
        end_flag = data[pos] & 1
        pos += 9
        if end_flag:
            return (start, pos)
    return None


def _referenced_samples(data: bytes):
    """Collect referenced BRR starts from the component data.

    Return: (cand{start:end}, refs{start:count}).
    """
    lo, hi = COMPONENT_REGION
    cand: dict[int, int] = {}
    refs: dict[int, int] = {}
    for p in range(lo, hi - 2):
        snes = data[p] | (data[p + 1] << 8) | (data[p + 2] << 16)
        f = (((snes >> 16) & 0x3F) << 16) | (snes & 0xFFFF)   # HiROM SNES->File
        if _bank_of(f) is None:
            continue
        if f not in cand:
            ext = _brr_extent(data, f)
            if ext is None or (ext[1] - ext[0]) // 9 < MIN_BLOCKS:
                cand[f] = 0                                    # remember as "checked, discarded"
                continue
            cand[f] = ext[1]
        if cand[f]:
            refs[f] = refs.get(f, 0) + 1
    return {s: e for s, e in cand.items() if e}, refs


def _prune_overlaps(cand: dict[int, int], refs: dict[int, int]):
    """Sorted by start, discard overlapping candidates (real samples are disjoint).

    On overlap the one with more references wins (else the one that starts first).
    """
    kept: list[tuple[int, int]] = []
    for s in sorted(cand):
        e = cand[s]
        if kept and s < kept[-1][1]:
            ps, pe = kept[-1]
            if refs.get(s, 0) > refs.get(ps, 0):
                kept[-1] = (s, e)
            continue
        kept.append((s, e))
    return kept


def _rms(pcm):
    return (sum(v * v for v in pcm) / len(pcm)) ** 0.5 if pcm else 0.0


def _autocorr(pcm, lo=16, hi=400, cap=2000):
    v = pcm[:cap]
    n = len(v)
    if n < 2 * lo:
        return 0.0
    mean = sum(v) / n
    v = [x - mean for x in v]
    a0 = sum(x * x for x in v) or 1.0
    hi = min(hi, n // 2)
    return max((sum(v[i] * v[i + lag] for i in range(n - lag)) / a0
                for lag in range(lo, hi)), default=0.0)


def _write_wav(path: Path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join((v & 0xFFFF).to_bytes(2, "little") for v in pcm))


def _song_table(data: bytes):
    """[snes_ptr, ...] of the AKAO song sequence table (3-byte $8A pointers)."""
    ptrs = []
    for i in range(256):
        o = SONG_PTR_TABLE + i * 3
        snes = data[o] | (data[o + 1] << 8) | (data[o + 2] << 16)
        if (snes >> 16) != 0x8A:
            break
        ptrs.append(snes)
    return ptrs


def extract(rom: Rom, out: Path) -> dict:
    _selftest()
    out.mkdir(parents=True, exist_ok=True)
    data = rom.data

    cand, refs = _referenced_samples(data)
    kept = _prune_overlaps(cand, refs)

    samples = []
    for start, end in kept:
        pcm, _ = Rom.decode_brr(data, start)
        rms = _rms(pcm)
        if rms < MIN_RMS:                                # silence / false hit
            continue
        idx = len(samples)
        blocks = (end - start) // 9
        loops = bool((data[end - 9] >> 1) & 1)          # loop flag of the end block
        _write_wav(out / f"inst_{idx:04d}.wav", pcm)
        samples.append({
            "index": idx,
            "file": f"inst_{idx:04d}.wav",
            "rom_offset": start,
            "blocks": blocks,
            "n_samples": len(pcm),
            "duration_s": round(len(pcm) / SAMPLE_RATE, 4),
            "rms": round(rms, 1),
            "autocorr": round(_autocorr(pcm), 3),       # ~tonal periodicity (0..1)
            "loops": loops,
            "loop_point": None,                          # exact only from the ARAM DIR (see README)
            "refs": refs.get(start, 0),
            "sample_rate": SAMPLE_RATE,
        })

    (out / "samples.json").write_text(json.dumps(
        {"sample_rate": SAMPLE_RATE, "count": len(samples), "samples": samples},
        indent=2) + "\n")

    songs = _song_table(data)
    durs = sorted(s["duration_s"] for s in samples)
    med = durs[len(durs) // 2] if durs else 0.0
    readme = [
        "# Audio (AKAO BRR -> WAV)",
        "",
        f"{len(samples)} real instrument samples, mono PCM16 @ {SAMPLE_RATE} Hz "
        f"(`inst_XXXX.wav`). Duration min={durs[0] if durs else 0}s "
        f"med={med}s max={durs[-1] if durs else 0}s.",
        "",
        "## Origin (verified, not guessed)",
        "",
        "SoE uses the Square/AKAO sound engine. The BRR instruments sit in four ROM banks:",
        "",
    ] + [f"- 0x{a:06X}..0x{b:06X}" for a, b in SAMPLE_BANKS] + [
        "",
        f"The music component data (0x{COMPONENT_REGION[0]:06X}..0x{COMPONENT_REGION[1]:06X}) "
        "references every used sample by a 3-byte pointer to its BRR start. "
        "These starts are collected and each is decoded as a complete BRR sample. "
        "Only samples that start in filter 0, run block by block up to an end flag, "
        f"are >= {MIN_BLOCKS} blocks long and overlap no other sample are kept.",
        "",
        "## Song/sequence table (for later SPC-style playback)",
        "",
        f"- Offset: 0x{SONG_PTR_TABLE:06X}",
        f"- {len(songs)} entries, each a 3-byte SNES pointer (bank $8A) to AKAO sequence data.",
        "- First targets: " + ", ".join(f"0x{p:06X}" for p in songs[:6]) + " ...",
        "",
        "## Limit: loop points",
        "",
        "The exact loop offsets are in the S-DSP DIR, which is loaded into ARAM per song, "
        "not in the ROM next to the sample. `samples.json` reports `loops` (loop flag "
        "of the end block); `loop_point` stays null. Upgrade: reconstruct ARAM per song, "
        "read the DIR -> exact loops + SPC playback.",
        "",
        "## samples.json",
        "",
        "Per sample: rom_offset, blocks, n_samples, duration_s, rms, autocorr "
        "(tonal periodicity 0..1), loops, loop_point, refs.",
    ]
    (out / "README.md").write_text("\n".join(readme) + "\n")

    return {"instruments": len(samples), "songs": len(songs)}
