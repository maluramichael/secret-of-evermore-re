-- Log EVERY $80903F/$809032 compose call (no sampling: keeping only the first call per
-- frame hides the running Boy behind the static party/HUD sprite CD:3F03).
-- Per call: frame, phase, entry, bank:off, ROM count-byte, DP $06 raw, DP $02/$04 (node
-- +6/+8, screen/world pos per background). Raw table -> boy_list_calls.txt. Aggregated
-- per-phase, per-call-ordinal (call 1, call 2, ... within the frame, in fire order) RLE
-- sequences -> boy_list.txt, plus per-pointer avg position and outlier-call flagging
-- (pointers that appear <3x within a directional phase -- likely turn/hurt, not walk-cycle).
local OUT = os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS = os.getenv("SOE_MSS")
local OUTFILE = os.getenv("SOE_OUTFILE") or "boy_list.txt"
local CALLSFILE = "boy_list_calls.txt"
local HOLD = 70 -- default hold for driven phases; stand uses its own (30)
local WR  = emu.memType.snesWorkRam
local CPU = emu.memType.snesMemory

local phases = {
  {name="stand", btn={},            hold=30},
  {name="down",  btn={down=true},   hold=HOLD},
  {name="up",    btn={up=true},     hold=HOLD},
  {name="left",  btn={left=true},   hold=HOLD},
  {name="right", btn={right=true},  hold=HOLD},
}

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0

local function rd(a) return emu.read(a, WR) end
local function romCount(bank, off) return emu.read(bank*0x10000 + off, CPU) end

local callLog = {}             -- {frame, phase, entry, val, count, d06, d02, d04}
local phaseCallSeqs = {}       -- [phase][callIdx] = {{val=,frames=},...} RLE by ordinal call position
local phasePtrCount = {}       -- [phase][val] = occurrences (any position) this phase
local distinctPtr = {}         -- val -> {count=chunkByte, calls=0, sumD02=0, sumD04=0}
local curFrameCallList = {}    -- ordered vals seen this SNES frame so far
local curFrameEntries = {}     -- parallel: entry codes ("3F"/"32") for calls.txt readability

local dump

local phaseStart = {} -- phase name -> its own pstart, for correct frame-offset reporting later

local function startPhase(i)
  pi = i; pstart = frame
  phaseStart[phases[i].name] = frame
  phaseCallSeqs[phases[i].name] = {}
  phasePtrCount[phases[i].name] = {}
end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("no mss"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  loaded = true
  startPhase(1)
  emu.log("boy_list_trace: savestate loaded, driving")
end

local function pushSeqVal(tbl, key, val)
  local list = tbl[key]
  if not list then list = {}; tbl[key] = list end
  local last = list[#list]
  if last and last.val == val then
    last.frames = last.frames + 1
  else
    list[#list+1] = {val=val, frames=1}
  end
end

local function onComposeEntry(entryCode)
  return function(addr)
    if not loaded then return end
    local d06  = rd(0x06)
    local bank = rd(0x28)
    local off  = rd(0x26) + rd(0x27) * 256
    local d02  = rd(0x02) + rd(0x03) * 256
    local d04  = rd(0x04) + rd(0x05) * 256
    local val  = string.format("%02X:%04X", bank, off)

    local d = distinctPtr[val]
    if not d then d = {count=romCount(bank, off), calls=0, sumD02=0, sumD04=0}; distinctPtr[val] = d end
    d.calls = d.calls + 1
    d.sumD02 = d.sumD02 + d02
    d.sumD04 = d.sumD04 + d04

    local pname = pi >= 1 and phases[pi].name or "-"
    callLog[#callLog+1] = {frame=frame, phase=pname, entry=entryCode, val=val,
                            count=d.count, d06=d06, d02=d02, d04=d04}

    if pi >= 1 then
      curFrameCallList[#curFrameCallList+1] = val
      curFrameEntries[#curFrameEntries+1] = entryCode
      local ppc = phasePtrCount[pname]
      ppc[val] = (ppc[val] or 0) + 1
    end
  end
end

local function onFrame()
  if pi >= 1 then
    local seqs = phaseCallSeqs[phases[pi].name]
    for k, val in ipairs(curFrameCallList) do
      pushSeqVal(seqs, k, val)
    end
  end
  curFrameCallList = {}
  curFrameEntries = {}

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

local function fmtSeq(list)
  local parts = {}
  for _, e in ipairs(list) do parts[#parts+1] = e.val.."x"..e.frames end
  return table.concat(parts, " ")
end

local function dumpCallsFile()
  local h = io.open(OUT..CALLSFILE, "w")
  h:write("# frame phase entry bank:off count d06 d02 d04\n")
  for _, c in ipairs(callLog) do
    h:write(string.format("%d %s %s %s %d %02X %04X %04X\n",
      c.frame, c.phase, c.entry, c.val, c.count, c.d06, c.d02, c.d04))
  end
  h:close()
end

dump = function()
  dumpCallsFile()

  local h = io.open(OUT..OUTFILE, "w")
  local mapid = rd(0x0ADB)
  h:write(string.format("# boy_list_trace RUN2 (full call log)  map=%d HOLD(stand=30,dir=%d)\n", mapid, HOLD))
  h:write(string.format("total compose calls logged: %d (raw table: %s)\n\n", #callLog, CALLSFILE))

  h:write("## per-phase, per-call-ordinal metasprite pointer RLE (call 1/2/../N = order of compose calls within each frame; avg pos and outlier flag looked up from distinct-pointer table below)\n")
  for _, p in ipairs(phases) do
    h:write("### phase="..p.name.."\n")
    local seqs = phaseCallSeqs[p.name] or {}
    local ks = {}
    for k in pairs(seqs) do ks[#ks+1]=k end
    table.sort(ks)
    for _, k in ipairs(ks) do
      h:write(string.format("call%d: %s\n", k, fmtSeq(seqs[k])))
    end
  end
  h:write("\n")

  h:write("## outlier calls per phase (pointer seen <3x anywhere in that phase -- candidate turn/hurt frame, not walk-cycle)\n")
  for _, p in ipairs(phases) do
    if p.name ~= "stand" then
      local ppc = phasePtrCount[p.name] or {}
      local found = false
      for _, c in ipairs(callLog) do
        if c.phase == p.name and (ppc[c.val] or 0) < 3 then
          if not found then h:write("### phase="..p.name.."\n"); found = true end
          h:write(string.format("  frame=%-3d entry=%s ptr=%s count-in-phase=%d pos=%04X,%04X\n",
            c.frame - phaseStart[p.name], c.entry, c.val, ppc[c.val] or 0, c.d02, c.d04))
        end
      end
    end
  end
  h:write("\n")

  h:write("## distinct metasprite pointers (bank:off): ROM count-byte (chunks), total calls, avg DP $02/$04\n")
  local pk = {}
  for k in pairs(distinctPtr) do pk[#pk+1]=k end
  table.sort(pk)
  for _, k in ipairs(pk) do
    local d = distinctPtr[k]
    h:write(string.format("%s  count-byte=%d  calls=%d  avg_d02=%04X  avg_d04=%04X\n",
      k, d.count, d.calls, math.floor(d.sumD02/d.calls+0.5), math.floor(d.sumD04/d.calls+0.5)))
  end

  h:close()
  emu.log("boy_list (run2) + boy_list_calls dumped")
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoad, emu.callbackType.exec, 0x00823A, 0x00823A)
emu.addMemoryCallback(onComposeEntry("3F"), emu.callbackType.exec, 0x80903F, 0x80903F)
emu.addMemoryCallback(onComposeEntry("32"), emu.callbackType.exec, 0x809032, 0x809032)
emu.log("boy_list_trace (run2) loaded")
