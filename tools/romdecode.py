#!/usr/bin/env python3
"""SNES ROM header + layout decoder. Stdlib only.

Reads the internal SNES header (LoROM 0x7FC0 / HiROM 0xFFC0), picks the one
with the correct checksum, and prints mapping, size, vectors and a bank
overview. Basis for reverse engineering / asset extraction.
"""
import sys, struct, hashlib

def load(path):
    data = open(path, "rb").read()
    # Copier header (SMC) = 512 bytes in front when size % 1024 == 512
    if len(data) % 1024 == 512:
        return data[512:], True
    return data, False

def read_header(rom, base):
    """base = 0x7FC0 (LoROM) or 0xFFC0 (HiROM). Returns dict or None."""
    if base + 0x40 > len(rom):
        return None
    h = rom[base:base + 0x40]
    title = h[0x00:0x15].decode("ascii", "replace").rstrip()
    map_mode = h[0x15]
    rom_type = h[0x16]
    rom_size = h[0x17]          # 2^n KB
    ram_size = h[0x18]
    country  = h[0x19]
    dev_id   = h[0x1A]
    version  = h[0x1B]
    chk_comp = struct.unpack("<H", h[0x1C:0x1E])[0]
    chk      = struct.unpack("<H", h[0x1E:0x20])[0]
    # Interrupt vectors (native + emulation), from 0x20
    vec = h[0x20:0x40]
    vectors = {
        "native_COP":   struct.unpack("<H", vec[0x04:0x06])[0],
        "native_BRK":   struct.unpack("<H", vec[0x06:0x08])[0],
        "native_NMI":   struct.unpack("<H", vec[0x0A:0x0C])[0],
        "native_IRQ":   struct.unpack("<H", vec[0x0E:0x10])[0],
        "emu_RESET":    struct.unpack("<H", vec[0x1C:0x1E])[0],
        "emu_NMI":      struct.unpack("<H", vec[0x1A:0x1C])[0],
        "emu_IRQ":      struct.unpack("<H", vec[0x1E:0x20])[0],
    }
    return dict(title=title, map_mode=map_mode, rom_type=rom_type,
                rom_size=rom_size, ram_size=ram_size, country=country,
                dev_id=dev_id, version=version, chk=chk, chk_comp=chk_comp,
                vectors=vectors)

def calc_checksum(rom):
    """SNES checksum: sum of all bytes mod 0x10000. ROMs whose size is not a
    power of two are mirrored by the real algorithm; here: plain sum for
    standard sizes (SoE = 24 Mbit = 3 MB, not a power of two)."""
    n = len(rom)
    # next smaller power of two
    p = 1 << (n.bit_length() - 1)
    if p == n:
        return sum(rom) & 0xFFFF
    # mirror the remainder up to a power of two (SNES convention)
    lo = sum(rom[:p])
    rest = rom[p:]
    r = len(rest)
    if r == 0:
        return lo & 0xFFFF
    mult = p // r  # how often the remainder is mirrored
    hi = sum(rest) * mult
    return (lo + hi) & 0xFFFF

MAP_NAMES = {0x20: "LoROM", 0x21: "HiROM", 0x23: "SA-1",
             0x30: "LoROM+FastROM", 0x31: "HiROM+FastROM", 0x32: "ExLoROM",
             0x35: "ExHiROM"}

def score(h, calc):
    if h is None:
        return -1
    s = 0
    if h["chk"] + h["chk_comp"] == 0xFFFF: s += 2   # complement matches
    if h["chk"] == calc: s += 3                      # sum matches
    if all(32 <= ord(c) < 127 for c in h["title"] if c != "�"): s += 1
    return s

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "Secret of Evermore (Europe).sfc"
    rom, smc = load(path)
    calc = calc_checksum(rom)
    lo = read_header(rom, 0x7FC0)
    hi = read_header(rom, 0xFFC0)
    best = "HiROM" if score(hi, calc) >= score(lo, calc) else "LoROM"
    h = hi if best == "HiROM" else lo

    print(f"File:         {path}")
    print(f"Size:         {len(rom)} bytes ({len(rom)//1024} KB / {len(rom)*8//1024//1024} Mbit)")
    print(f"SMC-Header:   {'yes (512 B stripped)' if smc else 'no'}")
    print(f"MD5:          {hashlib.md5(rom).hexdigest()}")
    print(f"SHA1:         {hashlib.sha1(rom).hexdigest()}")
    print(f"Selected:     {best} (Score lo={score(lo,calc)} hi={score(hi,calc)})")
    print("-" * 50)
    print(f"Title:        '{h['title']}'")
    print(f"Map-Mode:     0x{h['map_mode']:02X} ({MAP_NAMES.get(h['map_mode'],'?')})")
    print(f"ROM type:     0x{h['rom_type']:02X}")
    print(f"ROM size fld: 0x{h['rom_size']:02X} (= {1<<h['rom_size']} KB nominal)")
    print(f"RAM size fld: 0x{h['ram_size']:02X} (= {(1<<h['ram_size']) if h['ram_size'] else 0} KB SRAM)")
    print(f"Country:      0x{h['country']:02X}")
    print(f"Version:      1.{h['version']}")
    print(f"Checksum:     in ROM=0x{h['chk']:04X} compl=0x{h['chk_comp']:04X} computed=0x{calc:04X}"
          f"  {'OK' if h['chk']==calc else 'MISMATCH'}")
    print("-" * 50)
    print("Interrupt vectors (entry addresses in bank 0):")
    for k, v in h["vectors"].items():
        print(f"  {k:12s} = 0x{v:04X}")
    print("-" * 50)
    # Bank overview: 64 KB banks, first bytes per bank
    banks = len(rom) // 0x10000
    print(f"Banks (64KB): {banks}")
    print("Empty/fill-byte banks (possibly padding):")
    for b in range(banks):
        chunk = rom[b*0x10000:(b+1)*0x10000]
        if len(set(chunk)) <= 2:
            print(f"  Bank {b:02d}: uniform (fill byte 0x{chunk[0]:02X})")

if __name__ == "__main__":
    main()
