-- Read-trap on the Boy action table $C4452E..$C4462D (16 bytes/action, 4 bytes/dir),
-- plus its FastROM mirror $84452E..$84462D (same low 22 bits). Global exec
-- callback keeps an 8-entry ring buffer of executed PCs so the first few reads after each
-- phase change show the call context (compose_caller.lua pattern for curPC).
local OUT = os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS = os.getenv("SOE_MSS")
local OUTFILE = "boy_table.txt"
local WR = emu.memType.snesWorkRam
local TBL_C4, TBL_84 = 0xC4452E, 0x84452E

local phases = {
  {name="stand",  btn={},                   hold=20},
  {name="up",     btn={up=true},            hold=30},
  {name="right",  btn={right=true},         hold=30},
  {name="down",   btn={down=true},          hold=30},
  {name="left",   btn={left=true},          hold=30},
  {name="down_b", btn={down=true, b=true},  hold=30},
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
  emu.log("boy_table_trace: savestate loaded, driving")
end

local curPC = -1
local ringBuf = {}
local function onExecAny(addr)
  curPC = addr
  ringBuf[#ringBuf+1] = addr
  if #ringBuf > 8 then table.remove(ringBuf, 1) end
end

local readerPC = {}         -- pc -> count
local actionDir = {}        -- phase -> "action,dir" -> count
local phaseReadCount = {}   -- phase -> reads seen so far (for "first 3" gating)
local snapshots = {}        -- {phase, frame, addr, action, dir, pc, ring={...}}

local function onTableRead(addr, val)
  if not loaded or pi < 1 then return end
  local base = addr >= 0xC00000 and TBL_C4 or TBL_84
  local off = addr - base
  local action = off // 16
  local dir = (off % 16) // 4

  readerPC[curPC] = (readerPC[curPC] or 0) + 1

  local pname = phases[pi].name
  local ad = actionDir[pname]
  if not ad then ad = {}; actionDir[pname] = ad end
  local key = action..","..dir
  ad[key] = (ad[key] or 0) + 1

  phaseReadCount[pname] = (phaseReadCount[pname] or 0) + 1
  if phaseReadCount[pname] <= 3 then
    local ring = {}
    for i = 1, #ringBuf do ring[i] = ringBuf[i] end
    snapshots[#snapshots+1] = {phase=pname, frame=frame, addr=addr, action=action, dir=dir, pc=curPC, ring=ring}
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
    emu.setInput({up=false,down=false,left=false,right=false,a=false,b=false}, 0)
  end
end

dump = function()
  local h = io.open(OUT..OUTFILE, "w")
  h:write(string.format("# boy_table_trace  map=%d  table=$C4452E..$C4462D (mirror $84452E..)\n\n", rd(0x0ADB)))

  h:write("## reader PCs (counts)\n")
  local pcs = {}
  for pc in pairs(readerPC) do pcs[#pcs+1]=pc end
  table.sort(pcs, function(a,b) return readerPC[a] > readerPC[b] end)
  for _, pc in ipairs(pcs) do
    h:write(string.format("  %06X  reads=%d\n", pc, readerPC[pc]))
  end
  h:write("\n")

  h:write("## (action,dir) pairs read per phase\n")
  for _, p in ipairs(phases) do
    h:write("### phase="..p.name.."\n")
    local ad = actionDir[p.name] or {}
    local keys = {}
    for k in pairs(ad) do keys[#keys+1]=k end
    table.sort(keys)
    for _, k in ipairs(keys) do
      h:write(string.format("  (action,dir)=(%s)  reads=%d\n", k, ad[k]))
    end
  end
  h:write("\n")

  h:write("## first 3 reads per phase: ring buffer of last 8 exec PCs up to and including the read\n")
  for _, s in ipairs(snapshots) do
    h:write(string.format("### phase=%s frame=%d addr=%06X action=%d dir=%d read_pc=%06X\n",
      s.phase, s.frame, s.addr, s.action, s.dir, s.pc))
    local parts = {}
    for _, a in ipairs(s.ring) do parts[#parts+1] = string.format("%06X", a) end
    h:write("  ring: "..table.concat(parts, " -> ").."\n")
  end

  h:close()
  emu.log("boy_table dumped")
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
emu.addMemoryCallback(onTableRead, emu.callbackType.read, TBL_84, TBL_84 + 0xFF)
emu.addMemoryCallback(onTableRead, emu.callbackType.read, TBL_C4, TBL_C4 + 0xFF)
emu.log("boy_table_trace loaded")
