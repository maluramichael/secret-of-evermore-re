-- SoE ANIMATION caller for Mesen2 headless (--testRunner).  Sibling of
-- tools/mesen/map_hijack.lua: same "let the game build it" trick, but instead of
-- dumping ONE settled frame we let the loaded map RUN and record N successive
-- frames so palette-cycle and sprite motion fall out on their own.
--
-- MECHANISM (identical hijack, see tools/mesen/map_hijack.lua for the full write-up):
--   The bank-$90 map loader starts at $908F68 with `LDA $0ADB` (= current map id).
--   An EXEC callback on $908F68 overwrites $0ADB/$0ADC with our TARGET id before the
--   LDA reads it, so the game decodes OUR map through its own natural path. We pin on
--   every entry, so any reload rebuilds the same target.
--
-- CAPTURE PHASE (the new part):
--   Once the loader has fired and WAIT frames have passed to let VRAM/CGRAM/OAM settle,
--   we STOP mashing inputs (idle controller) but keep the map pinned, and for FRAMES
--   successive frames we dump, per frame:
--     * oam_%03d.bin   (snesSpriteRam, 544B = 512B primary OAM + 32B high table)
--     * cgram_%03d.bin (snesCgRam, 512B = 256 BGR555 colors) -> palette-cycle animation
--     * shot_%03d.png  (live 256x224 PPU frame) -> GROUND-TRUTH proof of motion
--   plus, once at capture start: vram.bin (64KB, holds the OBJ tile sheet) and info.txt
--   (dims + OBJ char base/offset/size from the PPU state).
--
--   Why idle the controller during capture: mashing START/A/B was only needed to power
--   through the logos into the attract/intro that invokes the loader. Once the map is up
--   we want a stable scene that animates in place (water/torch palette rotation, the
--   attract actors walking) rather than transitioning away. The pin still rebuilds the
--   same map if the attract sequence forces a reload.
--
-- Config via env: SOE_MAPID, SOE_OUT (trailing slash), SOE_WAIT (settle frames, def 180),
--   SOE_FRAMES (frames to record, def 64), SOE_MINFRAME (ignore loader hits before, def 300).

local TARGET   = tonumber(os.getenv("SOE_MAPID") or "8")
local OUT      = os.getenv("SOE_OUT") or "assets/dumps/anim/"
local WAIT     = tonumber(os.getenv("SOE_WAIT") or "180")
local FRAMES   = tonumber(os.getenv("SOE_FRAMES") or "64")
local MINFRAME = tonumber(os.getenv("SOE_MINFRAME") or "300")

local WR   = emu.memType.snesWorkRam
local VRAM = emu.memType.snesVideoRam
local CG   = emu.memType.snesCgRam
local OAM  = emu.memType.snesSpriteRam

local frame, loadedAt, capStart, capIdx, done = 0, nil, nil, 0, false

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

local function writeInfo()
  local mn, w, hh = rd(0x0ADB), rd16(0x08EE), rd16(0x08F0)
  local f = io.open(OUT .. "info.txt", "w")
  f:write(string.format("target=%d mapnum=%d width=%d height=%d frames=%d loadedAt=%d\n",
    TARGET, mn, w, hh, FRAMES, loadedAt))
  local ok, st = pcall(emu.getState)
  if ok and st.ppu then
    local p = st.ppu
    -- OBJ tile sheet lives in VRAM; base/offset are WORD addresses (x2 = byte).
    f:write(string.format("objBaseWord=%s objOffsetWord=%s oamMode=%s bgMode=%s\n",
      tostring(p.oamBaseAddress), tostring(p.oamAddressOffset),
      tostring(p.oamMode), tostring(p.bgMode)))
  end
  f:close()
end

local function onFrame()
  frame = frame + 1
  if done then return end
  if loadedAt and not capStart and frame >= loadedAt + WAIT then
    capStart = frame
    dumpMem(VRAM, 0, 0x10000, OUT .. "vram.bin")
    writeInfo()
  end
  if capStart then
    local i = capIdx
    dumpMem(OAM, 0, 0x220, string.format("%soam_%03d.bin", OUT, i))
    dumpMem(CG,  0, 0x200, string.format("%scgram_%03d.bin", OUT, i))
    local okS, s = pcall(emu.takeScreenshot)
    if okS and type(s) == "string" then
      local fh = io.open(string.format("%sshot_%03d.png", OUT, i), "wb")
      fh:write(s); fh:close()
    end
    capIdx = i + 1
    if capIdx >= FRAMES then
      done = true
      emu.stop(0)
    end
  end
  if frame >= 30000 then
    local f = io.open(OUT .. "info.txt", "w"); f:write("TIMEOUT no loader hit\n"); f:close()
    emu.stop(1)
  end
end

-- Mash START/A/B to reach the attract/intro that loads maps; go idle once loaded so the
-- scene animates in place instead of transitioning away.
local function onInput()
  local b = {}
  if not loadedAt then
    local p = frame % 16
    if frame > 60 then
      if p < 4 then b.start = true elseif p < 8 then b.a = true elseif p < 10 then b.b = true end
    end
  end
  emu.setInput(0, b)
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onExec, emu.callbackType.exec, 0x908F68, 0x908F68)
emu.log(string.format("anim_capture.lua loaded target=%d frames=%d", TARGET, FRAMES))
