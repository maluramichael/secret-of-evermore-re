-- Trace-based routine identification for SoE (Europe), Mesen2 headless.
--
-- Boots, mashes START/A/B to the intro/attract (loads a real gameplay map with
-- active sprites), then over a window of frames records:
--   * CALL TARGETS (addresses reached via JSL $22 / JSR $20 / JSR(abs,X) $FC) split
--     into NMI-region vs main-loop -> the actual subroutine ENTRY points that run
--     during vblank render vs game logic. These are function names to assign.
--   * every $420B (MDMAEN) DMA transfer with B-bus target + source -> OAM ($2104),
--     CGRAM ($2122), VRAM ($2118) shadow-buffer sources.
--   * NMI handler confirmation via exec cb on $00823A (native NMI vector).
--
-- getState() must NOT be used in a memory callback; only emu.read/write.
-- Env: SOE_OUT (dir with trailing slash), SOE_WINDOW (frames to record, default 40).

local OUT = os.getenv("SOE_OUT") or
  "assets/dumps/trace/"
local WINDOW = tonumber(os.getenv("SOE_WINDOW") or "40")

local WR  = emu.memType.snesWorkRam
local CPU = emu.memType.snesMemory
local OAM = emu.memType.snesSpriteRam

local function rd(a)   return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a + 1) * 256 end
local function cpu(a)  return emu.read(a, CPU) end

local frame     = 0
local armed     = false
local armFrame  = 0
local nmiActive = false
local nmi_hits  = 0
local prevAddr  = -1
local targetsNmi  = {}   -- call targets while in NMI region
local targetsMain = {}   -- call targets in main loop
local dma_log   = {}
local execCbAdded = false

local function count_active_oam()
  local n = 0
  for i = 0, 127 do
    local y = emu.read(i * 4 + 1, OAM)
    if y ~= 0 and y < 0xE0 then n = n + 1 end
  end
  return n
end

-- record JSL/JSR call targets during the recording window
local function onExecAny(addr)
  if not armed then prevAddr = addr; return end
  if prevAddr >= 0 then
    local op = cpu(prevAddr)
    if op == 0x22 or op == 0x20 or op == 0xFC then
      if nmiActive then targetsNmi[addr] = (targetsNmi[addr] or 0) + 1
      else               targetsMain[addr] = (targetsMain[addr] or 0) + 1 end
    end
  end
  prevAddr = addr
end

local function onNMI()
  nmi_hits = nmi_hits + 1
  nmiActive = true
end

local BBUS = { [0x04]="OAM($2104)", [0x22]="CGRAM($2122)", [0x18]="VRAM($2118)",
               [0x19]="VRAM($2119)", [0x40]="APU($2140)", [0x00]="reg($2100)" }
local function onDmaEnable(addr, val)
  if val == 0 or not armed then return end
  local vmadd = cpu(0x2116) + cpu(0x2117) * 256
  for ch = 0, 7 do
    if (val & (1 << ch)) ~= 0 then
      local b = 0x4300 + ch * 0x10
      local ctrl, bbus = cpu(b), cpu(b + 1)
      local slo, shi, sbk = cpu(b + 2), cpu(b + 3), cpu(b + 4)
      local sz = cpu(b + 5) + cpu(b + 6) * 256
      dma_log[#dma_log + 1] = string.format(
        "f=%d nmi=%s ch=%d ctrl=%02X bbus=%02X(%s) src=%02X:%02X%02X sz=%04X vmadd=%04X",
        frame, tostring(nmiActive), ch, ctrl, bbus, BBUS[bbus] or "?",
        sbk, shi, slo, sz, vmadd)
    end
  end
end

local function dumpset(tbl, path)
  local keys = {}
  for k in pairs(tbl) do keys[#keys + 1] = k end
  table.sort(keys)
  local h = io.open(path, "w")
  for _, k in ipairs(keys) do h:write(string.format("%06X %d\n", k, tbl[k])) end
  h:close()
  return #keys
end

local function finish(tag)
  local nn = dumpset(targetsNmi,  OUT .. "targets_nmi.txt")
  local nm = dumpset(targetsMain, OUT .. "targets_main.txt")
  local h = io.open(OUT .. "dma.txt", "w")
  h:write(table.concat(dma_log, "\n") .. "\n"); h:close()
  local mn, w, hh = rd(0x0ADB), rd16(0x08EE), rd16(0x08F0)
  local info = io.open(OUT .. "info.txt", "w")
  info:write(string.format(
    "tag=%s frame=%d map=%d dims=%dx%d nmi_hits=%d nmi_targets=%d main_targets=%d dma=%d oam=%d window=%d\n",
    tag, frame, mn, w, hh, nmi_hits, nn, nm, #dma_log, count_active_oam(), WINDOW))
  info:close()
  emu.log(string.format("hwtrace %s nmi_t=%d main_t=%d dma=%d", tag, nn, nm, #dma_log))
  emu.stop(0)
end

local function onFrame()
  frame = frame + 1
  nmiActive = false                 -- NMI region ended at this frame boundary
  if armed and frame >= armFrame + WINDOW then finish("ok"); return end
  if not armed then
    local mn = rd(0x0ADB)
    local w, hh = rd16(0x08EE), rd16(0x08F0)
    if mn > 0 and mn < 0x80 and w > 0 and w < 128 and hh > 0 and hh < 128
       and frame > 420 and count_active_oam() >= 1 then
      armed = true; armFrame = frame
      if not execCbAdded then
        emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
        execCbAdded = true
      end
    end
    if frame >= 6000 then finish("cap6000") end
  end
end

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
emu.addMemoryCallback(onNMI, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onDmaEnable, emu.callbackType.write, 0x420B, 0x420B)
emu.log("hwtrace loaded")
