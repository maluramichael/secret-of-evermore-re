-- Boy-entity ($7E4E89) script-cursor trace. Struct:
--   +0/+1 = script cursor lo/hi (16-bit offset)      +2 = script bank
--   +3/+4 = loop-marker (16-bit offset, same bank as +2; provisional)
-- Write-trap on $7E4E89..$7E4E8D (all 5 bytes) + global exec callback for curPC (writer PC),
-- same pattern as boy_entity_trace.lua. Phases drive each direction plain, then with A (dash, in case the
-- Jaguar Ring is available), then one attack (down+B).
local OUT = os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS = os.getenv("SOE_MSS")
local OUTFILE = "boy_script.txt"
local WR = emu.memType.snesWorkRam
local BASE = 0x4E89 -- Boy entity base (verified)

local phases = {
  {name="stand",   btn={},                        hold=20},
  {name="up",      btn={up=true},                 hold=40},
  {name="right",   btn={right=true},              hold=40},
  {name="down",    btn={down=true},               hold=40},
  {name="left",    btn={left=true},               hold=40},
  {name="up_a",    btn={up=true, a=true},         hold=40},
  {name="right_a", btn={right=true, a=true},      hold=40},
  {name="down_a",  btn={down=true, a=true},       hold=40},
  {name="left_a",  btn={left=true, a=true},       hold=40},
  {name="down_b",  btn={down=true, b=true},       hold=40},
}

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0
local phaseStart = {}

local function rd(a) return emu.read(a, WR) end

local dump
local function startPhase(i)
  pi = i; pstart = frame
  phaseStart[phases[i].name] = frame
end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("no mss"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  loaded = true
  startPhase(1)
  emu.log("boy_script_trace: savestate loaded, driving")
end

local curPC = -1
local function onExecAny(addr) curPC = addr end

local writeEvents = {}         -- {frame, phase, addr, val, pc}
local cursorPC, bankPC, markPC = {}, {}, {}  -- pc -> count, split by field
local phaseFirstCursor = {}    -- phase -> "bank:cursor" (settled value within first 5 frames)
local perFrameLog = {}         -- {frame, phase, str} on change only
local lastStructStr = nil

local function fieldBucketFor(addr)
  if addr == 0x7E4E89 or addr == 0x7E4E8A then return cursorPC end
  if addr == 0x7E4E8B then return bankPC end
  return markPC -- 0x7E4E8C / 0x7E4E8D
end

local function onEntityWrite(a, v)
  if not loaded then return end
  local pname = pi >= 1 and phases[pi].name or "-"
  writeEvents[#writeEvents+1] = {frame=frame, phase=pname, addr=a, val=v, pc=curPC}
  local bucket = fieldBucketFor(a)
  bucket[curPC] = (bucket[curPC] or 0) + 1

  if (a == 0x7E4E89 or a == 0x7E4E8A) and pi >= 1 and (frame - pstart) <= 5 then
    local bank = rd(BASE+2)
    local cur = rd(BASE) + rd(BASE+1) * 256
    phaseFirstCursor[pname] = string.format("%02X:%04X", bank, cur)
  end
end

local function onFrame()
  if pi >= 1 then
    local bank = rd(BASE+2)
    local cur = rd(BASE) + rd(BASE+1) * 256
    local mark = rd(BASE+3) + rd(BASE+4) * 256
    local str = string.format("%02X:%04X loop=%02X:%04X", bank, cur, bank, mark)
    if str ~= lastStructStr then
      perFrameLog[#perFrameLog+1] = {frame=frame, phase=phases[pi].name, str=str}
      lastStructStr = str
    end
  end

  frame = frame + 1
  if not loaded or done then return end
  if pi >= 1 and frame >= pstart + phases[pi].hold then
    if pi >= #phases then
      done = true
      dump()
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

local function dumpPCTable(h, label, tbl)
  h:write("### "..label.."\n")
  local pcs = {}
  for pc in pairs(tbl) do pcs[#pcs+1]=pc end
  table.sort(pcs, function(a,b) return tbl[a] > tbl[b] end)
  for _, pc in ipairs(pcs) do
    h:write(string.format("  %06X  writes=%d\n", pc, tbl[pc]))
  end
end

dump = function()
  local h = io.open(OUT..OUTFILE, "w")
  h:write(string.format("# boy_script_trace  map=%d  base=$7E%04X\n\n", rd(0x0ADB), BASE))

  h:write("## writer PCs by field\n")
  dumpPCTable(h, "cursor (+0/+1)", cursorPC)
  dumpPCTable(h, "bank (+2)", bankPC)
  dumpPCTable(h, "loop-marker (+3/+4)", markPC)
  h:write("\n")

  h:write("## per-phase script start (settled cursor value within first 5 frames of the phase)\n")
  for _, p in ipairs(phases) do
    h:write(string.format("%-8s -> %s\n", p.name, phaseFirstCursor[p.name] or "(no cursor write seen)"))
  end
  h:write("\n")

  h:write("## selection-PC candidates: cursor-field writer PCs, split into early-phase (frame-in-phase<=5, i.e. likely script SELECTION) vs late (likely VM step)\n")
  local pcs = {}
  for pc in pairs(cursorPC) do pcs[#pcs+1]=pc end
  table.sort(pcs, function(a,b) return cursorPC[a] > cursorPC[b] end)
  for _, pc in ipairs(pcs) do
    local early, late = 0, 0
    for _, w in ipairs(writeEvents) do
      if w.pc == pc and (w.addr == 0x7E4E89 or w.addr == 0x7E4E8A) then
        local ps = phaseStart[w.phase] or 0
        if (w.frame - ps) <= 5 then early = early + 1 else late = late + 1 end
      end
    end
    h:write(string.format("  %06X  total=%d early=%d late=%d\n", pc, cursorPC[pc], early, late))
  end
  h:write("\n")

  h:write("## per-frame struct log (bank:cursor loop=bank:mark), rows only on change\n")
  for _, e in ipairs(perFrameLog) do
    h:write(string.format("f=%-4d %-8s %s\n", e.frame - (phaseStart[e.phase] or 0), e.phase, e.str))
  end
  h:write("\n")

  h:write(string.format("## full write log (%d events): frame-in-phase, phase, addr=value, pc\n", #writeEvents))
  for _, w in ipairs(writeEvents) do
    h:write(string.format("f=%-4d %-8s %06X=%02X pc=%06X\n",
      w.frame - (phaseStart[w.phase] or 0), w.phase, w.addr, w.val, w.pc))
  end

  h:close()
  emu.log("boy_script dumped")
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
emu.addMemoryCallback(onEntityWrite, emu.callbackType.write, 0x7E0000+BASE, 0x7E0000+BASE+4)
emu.log("boy_script_trace loaded")
