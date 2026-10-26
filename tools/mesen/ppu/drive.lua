-- SoE map-load tracer for Mesen2 (headless --testRunner).
-- Boots the ROM, mashes START/A to get past logos+title into the intro (which
-- loads real maps), watches the WRAM map vars, and dumps WRAM/VRAM/CGRAM for the
-- first N distinct loaded maps. All ground-truth addresses from DataCrystal:
--   7E0ADB current map number, 7E08EE width(tiles), 7E08F0 height(tiles),
--   7E6187.. palette buffer, 7F0000 tile-info ptrs, 7FC300 arrangement.
-- WRAM offset in snesWorkRam = snesAddr - 0x7E0000.
local OUT = os.getenv("SOE_OUT") or "assets/dumps/emulator/"

local WRAM = emu.memType.snesWorkRam
local VRAM = emu.memType.snesVideoRam
local CGRAM = emu.memType.snesCgRam

local frame = 0
local dumped = {}          -- mapnum -> true
local dumpCount = 0
local MAXDUMPS = 2
local FRAMECAP = 30000
local trace = {}
local lastMap = -1
local stableMap, stableSince = -1, 0

local function rd(off) return emu.read(off, WRAM) end
local function rd16(off) return emu.read(off, WRAM) + emu.read(off+1, WRAM)*256 end

-- write a memory region to a binary file
local function dumpMem(memType, startOff, len, path)
  local h = io.open(path, "wb")
  if not h then emu.log("DUMP FAIL open "..path); return false end
  local buf = {}
  for i = 0, len-1 do
    buf[#buf+1] = string.char(emu.read(startOff+i, memType))
    if #buf >= 4096 then h:write(table.concat(buf)); buf = {} end
  end
  if #buf > 0 then h:write(table.concat(buf)) end
  h:close()
  return true
end

local function dumpState(path, mapnum, w, hgt)
  local h = io.open(path, "w")
  if not h then return end
  h:write(string.format("frame=%d\nmapnum=%d\nwidth=%d\nheight=%d\n", frame, mapnum, w, hgt))
  local ok, st = pcall(emu.getState)
  if ok and type(st)=="table" then
    local ppu = st.ppu or {}
    for k,v in pairs(ppu) do
      if type(v) ~= "table" then h:write("ppu."..k.."="..tostring(v).."\n") end
    end
    if st.cpu then h:write("cpu.pc="..tostring(st.cpu.pc).."\n") end
  end
  h:close()
end

local function doDump(mapnum)
  local w, hgt = rd16(0x08EE), rd16(0x08F0)
  local tag = string.format("map%02X_f%d", mapnum, frame)
  emu.log("DUMPING "..tag.." w="..w.." h="..hgt)
  dumpMem(WRAM, 0x00000, 0x20000, OUT..tag.."_wram.bin")   -- full 128KB (7E+7F)
  dumpMem(VRAM, 0x00000, 0x10000, OUT..tag.."_vram.bin")   -- 64KB VRAM
  dumpMem(CGRAM,0x00000, 0x200,   OUT..tag.."_cgram.bin")  -- 512B CGRAM
  dumpState(OUT..tag.."_state.txt", mapnum, w, hgt)
  dumpCount = dumpCount + 1
end

-- inject input: alternate START / A / B to power through logos, title, intro text
local function onInput()
  local btn = {}
  local phase = frame % 16
  if frame > 90 then
    if phase < 4 then btn.start = true
    elseif phase < 8 then btn.a = true
    elseif phase < 10 then btn.b = true
    end
  end
  emu.setInput(0, btn)
end

local function onFrame()
  frame = frame + 1
  local mapnum = rd(0x0ADB)
  local w = rd16(0x08EE)
  local hgt = rd16(0x08F0)

  if mapnum ~= lastMap then
    trace[#trace+1] = string.format("f=%d mapnum=%d w=%d h=%d", frame, mapnum, w, hgt)
    lastMap = mapnum
  end

  -- track a stably-loaded map (valid dims, held a few frames)
  if mapnum > 0 and w > 0 and w <= 64 and hgt > 0 and hgt <= 64 then
    if mapnum == stableMap then
      stableSince = stableSince + 1
    else
      stableMap = mapnum; stableSince = 0
    end
    if stableSince == 20 and not dumped[mapnum] then
      dumped[mapnum] = true
      doDump(mapnum)
      if dumpCount >= MAXDUMPS then finish() end
    end
  end

  if frame >= FRAMECAP then finish() end
end

function finish()
  local h = io.open(OUT.."trace.txt","w")
  if h then h:write(table.concat(trace,"\n").."\n"); h:close() end
  emu.log("FINISH dumps="..dumpCount)
  emu.stop(dumpCount)
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.log("drive.lua loaded")
