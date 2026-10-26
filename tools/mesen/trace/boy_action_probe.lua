-- boy_action_probe: read-trap on boy action table $C4452E (+FastROM mirror $84452E), and for
-- every table read record the current Entity+0x22 = $7E4EAB (hypothesis: the state value
-- that indexes the group). Drives movement/attack/run automatically (Jaguar-Ring flag $7E2262
-- bit1 forced ON so run = group 7 is reachable) and holds each direction long enough to bump a
-- wall (push candidate). Manual actions (spell/damage/death/swim) can be triggered by hand while
-- the trap runs: everything is logged with map + group + Entity+0x22 so the mapping is direct.
local OUT = os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS = os.getenv("SOE_MSS")
local OUTFILE = os.getenv("SOE_OUTFILE") or "boy_action_probe.txt"
local WR = emu.memType.snesWorkRam
local TBL_C4, TBL_84 = 0xC4452E, 0x84452E
local E22 = 0x4EAB     -- Boy Entity ($7E4E89) + 0x22
local RING = 0x2262    -- charm bitflags; bit1 = Jaguar Ring (enables run)

-- long holds so the boy reaches a wall; free phase at the end for manual actions
local phases = {
  {name="stand",   btn={},                    hold=30},
  {name="push_up", btn={up=true},              hold=300},  -- long enough to bump a wall
  {name="push_rt", btn={right=true},           hold=300},
  {name="push_dn", btn={down=true},            hold=300},
  {name="push_lf", btn={left=true},            hold=300},
  {name="run_up",  btn={up=true, a=true},      hold=90},
  {name="attack",  btn={down=true, b=true},    hold=40},
  {name="attack2", btn={b=true},               hold=40},   -- attack while standing (no dir held)
  {name="free",    btn=nil,                    hold=600},  -- no forced input: play by hand here
}

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0
local function rd(a) return emu.read(a, WR) end
local dump
local function startPhase(i) pi = i; pstart = frame end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("no mss "..MSS); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  -- force Jaguar Ring bit so run is selectable (SOE_RING=0 disables, to test attack without ring)
  if (os.getenv("SOE_RING") or "1") ~= "0" then
    pcall(function() emu.write(RING, emu.read(RING, WR) | 0x02, WR) end)
  end
  loaded = true
  startPhase(1)
  emu.log("boy_action_probe: savestate loaded, ring forced, driving")
end

local curPC = -1
local ringBuf = {}
local function onExecAny(addr)
  curPC = addr
  ringBuf[#ringBuf+1] = addr
  if #ringBuf > 6 then table.remove(ringBuf, 1) end
end

-- per phase: (group,dir,e22) combo -> count ; and first-seen snapshot with exec ring
local combo = {}       -- phase -> "group,dir,e22" -> count
local firstSeen = {}   -- phase -> set of combo keys already snapshotted
local snapshots = {}
local readerPC = {}

local function onTableRead(addr, val)
  if not loaded or pi < 1 then return end
  local base = addr >= 0xC00000 and TBL_C4 or TBL_84
  local off = addr - base
  local group = off // 16
  local dir = (off % 16) // 4
  local e22 = rd(E22)
  readerPC[curPC] = (readerPC[curPC] or 0) + 1
  local pname = phases[pi].name
  local c = combo[pname]; if not c then c = {}; combo[pname] = c end
  local key = group..","..dir..","..string.format("%02X", e22)
  c[key] = (c[key] or 0) + 1
  local fs = firstSeen[pname]; if not fs then fs = {}; firstSeen[pname] = fs end
  if not fs[key] then
    fs[key] = true
    local ring = {}
    for i = 1, #ringBuf do ring[i] = string.format("%06X", ringBuf[i]) end
    snapshots[#snapshots+1] = {phase=pname, frame=frame, group=group, dir=dir, e22=e22,
      pc=curPC, ring=table.concat(ring, " -> ")}
  end
end

local function onFrame()
  frame = frame + 1
  if not loaded or done then return end
  if pi >= 1 and frame >= pstart + phases[pi].hold then
    if pi >= #phases then done = true; dump(); return end
    startPhase(pi + 1)
  end
end

local function onInput()
  if loaded and not done and pi >= 1 and frame > pstart + 3 and phases[pi].btn then
    emu.setInput(phases[pi].btn, 0)
  end
end

dump = function()
  local h = io.open(OUT..OUTFILE, "w")
  h:write(string.format("# boy_action_probe  map=%d  HP=%d/%d  charms$2262=%02X\n",
    rd(0x0ADB), rd(0x2296) | (rd(0x2297)<<8), rd(0x2298) | (rd(0x2299)<<8), rd(RING)))
  h:write("# table $C4452E..$C4462D (mirror $84452E..); e22 = Entity+0x22 $7E4EAB at read time\n\n")
  h:write("## reader PCs\n")
  local pcs = {}; for pc in pairs(readerPC) do pcs[#pcs+1]=pc end
  table.sort(pcs, function(a,b) return readerPC[a] > readerPC[b] end)
  for _, pc in ipairs(pcs) do h:write(string.format("  %06X reads=%d\n", pc, readerPC[pc])) end
  h:write("\n## (group,dir,e22) per phase\n")
  for _, p in ipairs(phases) do
    h:write("### phase="..p.name.."\n")
    local c = combo[p.name] or {}
    local keys = {}; for k in pairs(c) do keys[#keys+1]=k end; table.sort(keys)
    for _, k in ipairs(keys) do h:write(string.format("  (grp,dir,e22)=(%s) reads=%d\n", k, c[k])) end
  end
  h:write("\n## first-seen snapshots (exec ring up to the read)\n")
  for _, s in ipairs(snapshots) do
    h:write(string.format("### phase=%s frame=%d grp=%d dir=%d e22=%02X pc=%06X\n  ring: %s\n",
      s.phase, s.frame, s.group, s.dir, s.e22, s.pc, s.ring))
  end
  h:close()
  emu.log("boy_action_probe dumped "..OUTFILE)
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
emu.addMemoryCallback(onTableRead, emu.callbackType.read, TBL_84, TBL_84 + 0xFF)
emu.addMemoryCallback(onTableRead, emu.callbackType.read, TBL_C4, TBL_C4 + 0xFF)
emu.log("boy_action_probe loaded")
