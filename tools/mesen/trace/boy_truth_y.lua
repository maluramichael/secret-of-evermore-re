-- Ground-truth capture for the moving Boy: OAM+CGRAM (+ periodic/on-change VRAM)
-- per driven frame, tied to the Boy's active metasprite pointer (compose calls at
-- $80903F/$809032, bank $CB = Boy -- see tools/mesen/trace/boy_list_trace.lua).
-- GUI mode (no emu.stop): savestate load in exec callback on $00823A, phase-driven
-- controller input via emu.setInput in inputPolled (see tools/mesen/trace/boy_drive_gui.lua).
local OUT  = (os.getenv("SOE_OUT") or "assets/dumps/trace/").."boy_truth_y/"
local MSS  = os.getenv("SOE_MSS")
local WR   = emu.memType.snesWorkRam
local VRAM = emu.memType.snesVideoRam
local CG   = emu.memType.snesCgRam
local OAM  = emu.memType.snesSpriteRam

local function rd(a) return emu.read(a, WR) end

-- stand still, then walk each direction, then run (dir + b) each direction.
-- a=true is the dash button (Jaguar Ring); b is the attack button; index.txt's boy_ptrs bank:offset lets a
-- reader check whether run metasprites ($CB:1488+) actually fired for those phases.
local phases = {
  {name="stand",      btn={},                 hold=20},
  {name="walk_up",    btn={up=true},          hold=45},
  {name="walk_right", btn={right=true},       hold=45},
  {name="walk_down",  btn={down=true},        hold=45},
  {name="walk_left",  btn={left=true},        hold=45},
  {name="run_up",     btn={up=true,y=true},   hold=45},
  {name="run_right",  btn={right=true,y=true},hold=45},
  {name="run_down",   btn={down=true,y=true}, hold=45},
  {name="run_left",   btn={left=true,y=true}, hold=45},
}

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0
local di = 0                -- driven-frame counter, also used as dump file index
local curPtrs = {}          -- CB:xxxx pointers seen since the last onFrame dump
local lastPtrKey = nil
local indexLines = {}

local function startPhase(i) pi = i; pstart = frame end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("boy_truth: no savestate"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  loaded = true
  startPhase(1)
  emu.log("boy_truth: savestate loaded, driving")
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
  h:write(string.format("# boy_truth capture, map=%d\n", rd(0x0ADB)))
  for _, l in ipairs(indexLines) do h:write(l.."\n") end
  h:close()
  emu.log("boy_truth: index dumped, "..#indexLines.." frames")
end

local function onFrame()
  -- ptrs accumulated since the previous dump belong to the CPU-execution window
  -- that just completed; associate them with the frame about to be snapshot
  -- (one-frame-lag heuristic -- fine here, we only need frame-level pointers).
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

    local objbase, objoff, objsize = "?", "?", "?"
    local ok, st = pcall(emu.getState)
    if ok and st.ppu then
      objbase = tostring(st.ppu.oamBaseAddress)
      objoff  = tostring(st.ppu.oamAddressOffset)
      objsize = tostring(st.ppu.oamMode)
    end

    local ptrField = (#ptrs > 0) and ptrKey or "-"
    indexLines[#indexLines+1] = string.format(
      "%d %s boy_ptrs=%s vram=%s objbase=%s objoff=%s objsize=%s",
      di, phaseName, ptrField, vramTag, objbase, objoff, objsize)

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
emu.log("boy_truth loaded")
