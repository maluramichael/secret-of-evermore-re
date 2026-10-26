-- Force the Jaguar-Ring charm-bits (Data-Crystal WRAM map $7E2261..$7E2263, the spin
-- routine at $D082A8 reads $2262) to 0xFF right after savestate load, then hold each
-- direction + the dash-button guess (a=true) for 60 frames. Same OAM/CGRAM/VRAM dump
-- + $80903F/$809032 boy_ptrs trap as boy_truth_a.lua; see that file for the mechanism.
local OUT  = (os.getenv("SOE_OUT") or "assets/dumps/trace/").."boy_truth_ring/"
local MSS  = os.getenv("SOE_MSS")
local WR   = emu.memType.snesWorkRam
local VRAM = emu.memType.snesVideoRam
local CG   = emu.memType.snesCgRam
local OAM  = emu.memType.snesSpriteRam

local function rd(a) return emu.read(a, WR) end
local function wr(a, v) emu.write(a, v, WR) end

local phases = {
  {name="stand",     btn={},                 hold=20},
  {name="run_up",    btn={up=true,a=true},   hold=60},
  {name="run_right", btn={right=true,a=true},hold=60},
  {name="run_down",  btn={down=true,a=true}, hold=60},
  {name="run_left",  btn={left=true,a=true}, hold=60},
}

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0
local di = 0
local curPtrs = {}
local lastPtrKey = nil
local indexLines = {}

local function startPhase(i) pi = i; pstart = frame end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("boy_truth_ring: no savestate"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  wr(0x2261, 0xFF); wr(0x2262, 0xFF); wr(0x2263, 0xFF)
  loaded = true
  startPhase(1)
  emu.log("boy_truth_ring: savestate loaded, charm bytes forced, driving")
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

local function dumpMem(mt, len, path)
  local h = io.open(path, "wb")
  local b = {}
  for i = 0, len - 1 do
    b[#b+1] = string.char(emu.read(i, mt))
    if #b >= 8192 then h:write(table.concat(b)); b = {} end
  end
  if #b > 0 then h:write(table.concat(b)) end
  h:close()
end

local function dumpIndex()
  local h = io.open(OUT.."index.txt", "w")
  h:write(string.format("# boy_truth_ring capture, map=%d, charm $2261/$2262/$2263=FF\n", rd(0x0ADB)))
  for _, l in ipairs(indexLines) do h:write(l.."\n") end
  h:close()
  emu.log("boy_truth_ring: index dumped, "..#indexLines.." frames")
end

local function onFrame()
  local ptrs = curPtrs
  curPtrs = {}
  frame = frame + 1
  if not loaded or done then return end

  if pi >= 1 then
    table.sort(ptrs)
    local ptrKey = table.concat(ptrs, ",")
    local phaseName = phases[pi].name

    dumpMem(OAM, 0x220, string.format("%soam_%04d.bin", OUT, di))
    dumpMem(CG,  0x200, string.format("%scgram_%04d.bin", OUT, di))

    local vramTag = "same"
    if di % 8 == 0 or ptrKey ~= lastPtrKey then
      local vramName = string.format("vram_%04d.bin", di)
      dumpMem(VRAM, 0x10000, OUT..vramName)
      vramTag = vramName
    end
    lastPtrKey = ptrKey

    local ptrField = (#ptrs > 0) and ptrKey or "-"
    indexLines[#indexLines+1] = string.format("%d %s boy_ptrs=%s vram=%s", di, phaseName, ptrField, vramTag)

    di = di + 1
  end

  if pi >= 1 and frame >= pstart + phases[pi].hold then
    if pi >= #phases then
      done = true
      dumpIndex()
      return
    end
    startPhase(pi + 1)
  end
end

local function onInput()
  if loaded and not done and pi >= 1 and frame > pstart + 3 then
    emu.setInput(phases[pi].btn, 0)
  else
    emu.setInput({up=false,down=false,left=false,right=false,a=false,b=false}, 0)
  end
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onComposeEntry, emu.callbackType.exec, 0x80903F, 0x80903F)
emu.addMemoryCallback(onComposeEntry, emu.callbackType.exec, 0x809032, 0x809032)
emu.log("boy_truth_ring loaded")
