-- SoE programmatic map-load caller for Mesen2 headless (--testRunner).
--
-- Idea: instead of statically reversing every codec, let the GAME's own map-load
-- routine build the map, then read the fully decoded result out of RAM/VRAM.
--
-- HOW THE CALL IS TRIGGERED (verified):
--   The bank-$90 map loader starts at $908F68 with `LDA $0ADB` (opcode AD DB 0A),
--   where $0ADB = current map id. It then computes the 3-byte map-data pointer,
--   reads width/height (+2/+3 -> $08EE/$08F0), decompresses the arrangement to
--   $7FC300, the op7 record-pointer table to $7F0000, the metatile records, DMAs
--   the tileset to VRAM char base $4000 ($9091C1) and loads the BG palette.
--
--   We put an EXEC memory-callback on $908F68 and, every time the game is about to
--   run the loader, overwrite $0ADB (and $0ADC high byte) with our TARGET id BEFORE
--   the `LDA` reads it. The game therefore builds OUR map through its own complete,
--   natural path -- no calling-convention guesswork, no manual JSL. Because we pin
--   $0ADB on every loader entry, any follow-up reload during the intro also rebuilds
--   the same target, so the decoded structures stay valid until we dump.
--
--   The intro/attract sequence naturally invokes the loader within a few hundred
--   frames (first hit ~f=389), so we just mash START/A/B to reach it and hijack.
--
-- WHY NOT setState+JSL: emu.setState CAN set PC/K/SP/A/... and a manual JSL is
--   possible, but the loader is normally entered mid-sequence and relies on
--   surrounding warp setup; hijacking the natural entry reuses ALL of that for free
--   and proved robust. emu.getState() must NOT be called inside a memory callback
--   (it errors); only read plain memory there.
--
-- Config via env: SOE_MAPID (decimal id), SOE_OUT (dir, trailing slash; must exist),
--   SOE_WAIT (frames to settle after first load, default 180),
--   SOE_MINFRAME (ignore loader hits before this frame, default 300).
--
-- Dumps written to SOE_OUT: wram.bin (128KB, 7E+7F), vram.bin (64KB), cgram.bin
--   (512B), oam.bin (544B), shot.png (live PPU frame, cross-check), info.txt.
--
-- ANIMATION / OAM (documented, not built): sprite animation runs through the OAM
--   mirror in WRAM and the object engine; to capture animation frames one would
--   let the loaded map run free (remove the pin, keep stepping frames) and dump
--   emu.memType.snesSpriteRam (OAM, 544B: 512B table + 32B high-table) plus the
--   CGRAM object palettes (rows 8..15) each frame -- the palette-cycle queue
--   ($90D582 -> $7E6187) already animates BG palettes in place, so re-dumping CGRAM
--   over successive frames captures palette animation without any extra call.

local TARGET   = tonumber(os.getenv("SOE_MAPID") or "16")
local OUT      = os.getenv("SOE_OUT") or "assets/dumps/snescall/"
local WAIT     = tonumber(os.getenv("SOE_WAIT") or "180")
local MINFRAME = tonumber(os.getenv("SOE_MINFRAME") or "300")

local WR   = emu.memType.snesWorkRam
local VRAM = emu.memType.snesVideoRam
local CG   = emu.memType.snesCgRam
local OAM  = emu.memType.snesSpriteRam

local frame, loadedAt, dumped = 0, nil, false

local function rd(a)   return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a + 1) * 256 end

-- Pin $0ADB to TARGET at the loader entry, before `LDA $0ADB` executes.
local function onExec()
  if frame < MINFRAME then return end
  emu.write(0x0ADB, TARGET & 0xFF, WR)
  emu.write(0x0ADC, 0, WR)
  if not loadedAt then loadedAt = frame end
end

local function dumpMem(mt, st, len, path)
  local h = io.open(path, "wb")
  local b = {}
  for i = 0, len - 1 do
    b[#b + 1] = string.char(emu.read(st + i, mt))
    if #b >= 8192 then h:write(table.concat(b)); b = {} end
  end
  if #b > 0 then h:write(table.concat(b)) end
  h:close()
end

local function onFrame()
  frame = frame + 1
  if dumped then return end
  if loadedAt and frame >= loadedAt + WAIT then
    dumped = true
    local mn, w, hh = rd(0x0ADB), rd16(0x08EE), rd16(0x08F0)
    dumpMem(WR,   0, 0x20000, OUT .. "wram.bin")
    dumpMem(VRAM, 0, 0x10000, OUT .. "vram.bin")
    dumpMem(CG,   0, 0x200,   OUT .. "cgram.bin")
    dumpMem(OAM,  0, 0x220,   OUT .. "oam.bin")
    local okS, s = pcall(emu.takeScreenshot)
    if okS and type(s) == "string" then
      local f = io.open(OUT .. "shot.png", "wb"); f:write(s); f:close()
    end
    local f = io.open(OUT .. "info.txt", "w")
    f:write(string.format("target=%d mapnum=%d width=%d height=%d frame=%d loadedAt=%d\n",
      TARGET, mn, w, hh, frame, loadedAt))
    -- PPU layer config (getState is safe here -- NOT in a memory callback).
    local ok, st = pcall(emu.getState)
    if ok and st.ppu then
      local p = st.ppu
      f:write(string.format("bgMode=%s mainScreen=%s subScreen=%s\n",
        tostring(p.bgMode), tostring(p.mainScreenLayers), tostring(p.subScreenLayers)))
      for i = 0, 3 do
        local L = p.layers[i]
        if L then
          f:write(string.format("bg%d chr=%s tilemap=%s large=%s hs=%s vs=%s\n",
            i + 1, tostring(L.chrAddress), tostring(L.tilemapAddress),
            tostring(L.largeTiles), tostring(L.hscroll), tostring(L.vscroll)))
        end
      end
    end
    f:close()
    emu.stop(0)
  end
  if frame >= 30000 then
    local f = io.open(OUT .. "info.txt", "w"); f:write("TIMEOUT no loader hit\n"); f:close()
    emu.stop(1)
  end
end

-- Mash START/A/B to power through logos/title into the attract/intro that loads maps.
local function onInput()
  local b = {}
  local p = frame % 16
  if frame > 60 then
    if p < 4 then b.start = true elseif p < 8 then b.a = true elseif p < 10 then b.b = true end
  end
  emu.setInput(0, b)
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onExec, emu.callbackType.exec, 0x908F68, 0x908F68)
emu.log(string.format("map_hijack.lua loaded target=%d", TARGET))
