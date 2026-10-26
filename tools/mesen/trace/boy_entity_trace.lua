-- $CFC665 never fires in the field (verified: 0 hits over 430 frames across two save
-- states). The real per-frame path is the
-- shared Insert routine $809609, which has 5 known callers ($CFC695, $CFC6EA, $CFC863,
-- $D08219, $D0DC31). Trap that entry instead, with prevPC via a global exec callback (compose_caller.lua
-- pattern) to see which caller fired. Node fields read from the WRAM slot at $1278 (the
-- Y-index used for the insert, per the CF:C665 disassembly's "LDY $1278" right before the JSL).
local OUT = os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS = os.getenv("SOE_MSS")
local OUTFILE = "boy_entity.txt"
local WR = emu.memType.snesWorkRam

local phases = {
  {name="stand", btn={},            hold=30},
  {name="down",  btn={down=true},   hold=40},
  {name="up",    btn={up=true},     hold=40},
  {name="left",  btn={left=true},   hold=40},
  {name="right", btn={right=true},  hold=40},
}

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0

local function rd(a) return emu.read(a, WR) end

local dump
local function startPhase(i) pi = i; pstart = frame end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("no mss"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  loaded = true
  startPhase(1)
  emu.log("boy_entity_trace: savestate loaded, driving")
end

local prevPC, curPC = -1, -1
local function onExecAny(addr) prevPC = curPC; curPC = addr end

local callerCounts = {}   -- callerPC -> count
local hits = {}           -- {frame, phase, caller, node, n4,n6,n8,nA, ptr, base}
local boyBases = {}       -- $4C values seen on bank-$CB hits
local dogBases = {}       -- $4C values seen on bank-$CC hits
local matchCount, mismatchCount = 0, 0

local writeTrapBases = {}
local writerCounts = {}   -- base -> pc -> count
local writeEvents = {}    -- {frame, phase, base, addr, val, pc}

local function armWriteTrap(base)
  if writeTrapBases[base] then return end
  writeTrapBases[base] = true
  emu.addMemoryCallback(function(a, v)
    local pc = curPC
    writerCounts[base] = writerCounts[base] or {}
    writerCounts[base][pc] = (writerCounts[base][pc] or 0) + 1
    if pi >= 1 then
      writeEvents[#writeEvents+1] = {frame=frame, phase=phases[pi].name, base=base, addr=a, val=v, pc=pc}
    end
  end, emu.callbackType.write, 0x7E0000+base+6, 0x7E0000+base+0xB)
  emu.log(string.format("write-trap armed on base=%04X +0x06..+0x0B", base))
end

local function onInsert(addr)
  if not loaded then return end
  local caller = prevPC
  callerCounts[caller] = (callerCounts[caller] or 0) + 1

  local node = rd(0x1278) + rd(0x1279) * 256
  local n4 = rd(node+4) + rd(node+5)*256
  local n6 = rd(node+6) + rd(node+7)*256
  local n8 = rd(node+8) + rd(node+9)*256
  local nA = rd(node+0xA) + rd(node+0xB)*256
  local plo, phi, pbank = rd(node+0xC), rd(node+0xD), rd(node+0xE)
  local ptr = string.format("%02X:%04X", pbank, plo + phi*256)
  local base = rd(0x4C) + rd(0x4D) * 256

  if pi >= 1 then
    hits[#hits+1] = {frame=frame, phase=phases[pi].name, caller=caller, node=node,
                      n4=n4, n6=n6, n8=n8, nA=nA, ptr=ptr, base=base}
  end

  if pbank == 0xCB then
    boyBases[base] = true
    armWriteTrap(base)
    local elo, ehi, ebank = rd(base+9), rd(base+0xA), rd(base+0xB)
    local eptr = string.format("%02X:%04X", ebank, elo + ehi*256)
    if eptr == ptr then matchCount = matchCount + 1 else mismatchCount = mismatchCount + 1 end
  elseif pbank == 0xCC then
    dogBases[base] = true
  end
end

local function onFrame()
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
    emu.setInput({up=false,down=false,left=false,right=false}, 0)
  end
end

dump = function()
  local h = io.open(OUT..OUTFILE, "w")
  h:write(string.format("# boy_entity_trace RUN3 (insert $809609 trap)  map=%d\n\n", rd(0x0ADB)))

  h:write("## caller PCs of $809609 (counts; expected among $CFC695/$CFC6EA/$CFC863/$D08219/$D0DC31)\n")
  local pcs = {}
  for pc in pairs(callerCounts) do pcs[#pcs+1]=pc end
  table.sort(pcs, function(a,b) return callerCounts[a] > callerCounts[b] end)
  for _, pc in ipairs(pcs) do
    h:write(string.format("  %06X  calls=%d\n", pc, callerCounts[pc]))
  end
  h:write("\n")

  local function setList(s)
    local l = {}
    for k in pairs(s) do l[#l+1] = k end
    table.sort(l)
    return l
  end
  local bb, db = setList(boyBases), setList(dogBases)
  h:write("## Boy candidate $4C values (bank $CB hits): ")
  for _, b in ipairs(bb) do h:write(string.format("%04X ", b)) end
  h:write("\n## Dog candidate $4C values (bank $CC hits): ")
  for _, b in ipairs(db) do h:write(string.format("%04X ", b)) end
  h:write("\n\n")

  h:write(string.format("## entity+0x09..0x0B vs node+0xC..0xE match check (bank $CB hits): match=%d mismatch=%d\n\n",
    matchCount, mismatchCount))

  h:write("## per-hit log (frame, phase, callerPC, node, n4,n6,n8,nA, ptr, base)\n")
  for _, e in ipairs(hits) do
    h:write(string.format("f=%-4d %-6s caller=%06X node=%04X n4=%04X n6=%04X n8=%04X nA=%04X ptr=%s base=%04X\n",
      e.frame, e.phase, e.caller, e.node, e.n4, e.n6, e.n8, e.nA, e.ptr, e.base))
  end
  h:write("\n")

  h:write("## write-trap results per base (entity+0x06..0x0B; expected writers $D08436/$D08442 for +0x09.., $D08421/$D08428 for +0x06..)\n")
  local bases = {}
  for b in pairs(writerCounts) do bases[#bases+1]=b end
  table.sort(bases)
  for _, b in ipairs(bases) do
    h:write(string.format("base=%04X:\n", b))
    local pcs2 = {}
    for pc in pairs(writerCounts[b]) do pcs2[#pcs2+1]=pc end
    table.sort(pcs2, function(x,y) return writerCounts[b][x] > writerCounts[b][y] end)
    for _, pc in ipairs(pcs2) do
      h:write(string.format("  writer=%06X  writes=%d\n", pc, writerCounts[b][pc]))
    end
  end
  h:write(string.format("\ntotal write events logged: %d\n", #writeEvents))
  for _, w in ipairs(writeEvents) do
    h:write(string.format("  f=%-4d %-6s base=%04X %06X=%02X pc=%06X\n", w.frame, w.phase, w.base, w.addr, w.val, w.pc))
  end

  h:close()
  emu.log("boy_entity (run3) dumped")
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
emu.addMemoryCallback(onInsert, emu.callbackType.exec, 0x809609, 0x809609)
emu.log("boy_entity_trace (run3, insert trap) loaded")
