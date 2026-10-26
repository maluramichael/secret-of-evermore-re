-- Identify the SoE sprite-composition routine (Europe, Mesen2 headless).
--
-- The NMI DMAs the 544-byte OAM shadow buffer $7EAC42 -> OAM ($8082E9, docs/labels.md).
-- WHOEVER WRITES $7EAC42 composes the hardware sprites = "renders the boy".
-- We boot, mash to the attract (a gameplay map with the walking Boy/actors), then
-- over a frame window trap every write into $7EAC42..+0x21F and log the writing PC
-- (tracked via an exec callback, since getState() is illegal inside a mem callback).
--
-- Output (SOE_OUT, dir with trailing slash):
--   oamwriters.txt : "PC count" per writing code address, sorted, + a few samples.
-- Env: SOE_OUT, SOE_WINDOW (frames to record after arming, default 30).

local OUT    = os.getenv("SOE_OUT") or
  "assets/dumps/trace/"
local WINDOW = tonumber(os.getenv("SOE_WINDOW") or "30")

local WR  = emu.memType.snesWorkRam
local OAM = emu.memType.snesSpriteRam

local OAMSHADOW = 0x7EAC42
local SHADOWLEN = 0x220          -- 544 bytes

local frame     = 0
local armed     = false
local armFrame  = 0
local curPC     = -1
local writers   = {}             -- pc -> count
local samples   = {}             -- first writes: "pc idx val"
local execCbAdded = false

local function rd(a)   return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a + 1) * 256 end

local function count_active_oam()
  local n = 0
  for i = 0, 127 do
    local y = emu.read(i * 4 + 1, OAM)
    if y ~= 0 and y < 0xE0 then n = n + 1 end
  end
  return n
end

-- exec cb: keep the current PC so the write cb can attribute the store
local function onExecAny(addr)
  curPC = addr
end

-- write cb on the OAM shadow: the composer
local function onOamWrite(addr, val)
  if not armed then return end
  writers[curPC] = (writers[curPC] or 0) + 1
  if #samples < 48 then
    samples[#samples + 1] = string.format("pc=%06X off=%03X val=%02X", curPC, addr - OAMSHADOW, val)
  end
end

local function dumpwriters(path)
  local keys = {}
  for k in pairs(writers) do keys[#keys + 1] = k end
  table.sort(keys, function(a, b) return writers[a] > writers[b] end)
  local h = io.open(path, "w")
  h:write(string.format("# OAM-shadow ($7EAC42) writers, window=%d frames, map=%d\n",
                        WINDOW, rd(0x0ADB)))
  for _, k in ipairs(keys) do h:write(string.format("%06X %d\n", k, writers[k])) end
  h:write("\n# first write samples:\n")
  for _, s in ipairs(samples) do h:write(s .. "\n") end
  h:close()
  return #keys
end

local function finish(tag)
  local nw = dumpwriters(OUT .. "oamwriters.txt")
  emu.log(string.format("oamwrite %s writers=%d oam=%d", tag, nw, count_active_oam()))
  emu.stop(0)
end

local function onFrame()
  frame = frame + 1
  if armed and frame >= armFrame + WINDOW then finish("ok"); return end
  if not armed then
    local mn = rd(0x0ADB)
    local w, hh = rd16(0x08EE), rd16(0x08F0)
    if mn > 0 and mn < 0x80 and w > 0 and w < 128 and hh > 0 and hh < 128
       and frame > 420 and count_active_oam() >= 1 then
      armed = true; armFrame = frame
      if not execCbAdded then
        emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
        emu.addMemoryCallback(onOamWrite, emu.callbackType.write, OAMSHADOW, OAMSHADOW + SHADOWLEN - 1)
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
emu.log("oamwrite loaded")
