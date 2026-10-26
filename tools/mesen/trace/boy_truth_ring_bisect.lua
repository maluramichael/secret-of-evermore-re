-- Bisect which byte/bit at $7E2261..63 is the Jaguar-Ring charm flag that unlocks
-- Run. Config via env: SOE_B1/SOE_B2/SOE_B3 (hex byte, default 00) written once to
-- $2261/$2262/$2263 right after savestate load; SOE_TAG names the log file;
-- SOE_HOLD = run_up frame count (default 20). Log-only (boy_ptrs per frame), no dumps.
local OUT  = (os.getenv("SOE_OUT") or "assets/dumps/trace/").."boy_truth_ring/"
local MSS  = os.getenv("SOE_MSS")
local WR   = emu.memType.snesWorkRam
local TAG  = os.getenv("SOE_TAG") or "bisect"
local B1   = tonumber(os.getenv("SOE_B1") or "0", 16)
local B2   = tonumber(os.getenv("SOE_B2") or "0", 16)
local B3   = tonumber(os.getenv("SOE_B3") or "0", 16)
local HOLD = tonumber(os.getenv("SOE_HOLD") or "20")

local function rd(a) return emu.read(a, WR) end
local function wr(a, v) emu.write(a, v, WR) end

local frame, loaded, done = 0, false, false
local pstart = 0
local curPtrs = {}
local lines = {}

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("bisect: no mss"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  wr(0x2261, B1); wr(0x2262, B2); wr(0x2263, B3)
  loaded = true
  pstart = frame
  emu.log(string.format("bisect %s: loaded, B1=%02X B2=%02X B3=%02X", TAG, B1, B2, B3))
end

local function onComposeEntry()
  if not loaded then return end
  local bank = rd(0x28)
  local off  = rd(0x26) + rd(0x27) * 256
  if bank == 0xCB then
    local key = string.format("CB:%04X", off)
    for _, v in ipairs(curPtrs) do if v == key then return end end
    curPtrs[#curPtrs+1] = key
  end
end

local function dumpLog()
  local h = io.open(OUT.."bisect_"..TAG..".txt", "w")
  h:write(string.format("# bisect %s  B1=%02X B2=%02X B3=%02X\n", TAG, B1, B2, B3))
  for _, l in ipairs(lines) do h:write(l.."\n") end
  h:close()
  emu.log("bisect "..TAG.." dumped")
end

local function onFrame()
  local ptrs = curPtrs
  curPtrs = {}
  frame = frame + 1
  if not loaded or done then return end
  table.sort(ptrs)
  local ptrKey = (#ptrs > 0) and table.concat(ptrs, ",") or "-"
  lines[#lines+1] = string.format("%d %s", frame - pstart, ptrKey)
  if frame >= pstart + HOLD then
    done = true
    dumpLog()
  end
end

local function onInput()
  if loaded and not done and frame > pstart + 3 then
    emu.setInput({up=true, a=true}, 0)
  else
    emu.setInput({up=false,down=false,left=false,right=false,a=false,b=false}, 0)
  end
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onComposeEntry, emu.callbackType.exec, 0x80903F, 0x80903F)
emu.addMemoryCallback(onComposeEntry, emu.callbackType.exec, 0x809032, 0x809032)
emu.log("bisect loaded, tag="..TAG)
