-- Force the Boy's walk-script cursor into its Run-script branch (bank $C8), instead
-- of guessing a controller button (A, B and Y all failed -- see boy_truth_a/_a11/_y).
-- Boy entity struct @ $7E4E89 (WRAM offset 0x4E89, no $7E prefix, read/write via
-- memType.snesWorkRam):
--   +0/+1 script cursor (lo/hi), +2 script bank, +3/+4 loop mark (lo/hi), +5 wait ctr.
-- The force is written EXACTLY ONCE per run phase (at pstart+6), then hands-off.
-- Rewriting it every frame pins the VM's wait-opcode cursor back to itself
-- every frame and it could never advance past the script start.
-- Run-script starts (the $52 marker byte itself, not +1), bank $C8, per direction:
--   up=$12BA  right=$12DB  down=$12FC  left=$131D
local OUT  = (os.getenv("SOE_OUT") or "assets/dumps/trace/").."boy_truth_force/"
local MSS  = os.getenv("SOE_MSS")
local WR   = emu.memType.snesWorkRam
local VRAM = emu.memType.snesVideoRam
local CG   = emu.memType.snesCgRam
local OAM  = emu.memType.snesSpriteRam

local CUR_LO, CUR_HI, SCR_BANK, LOOP_LO, LOOP_HI, WAIT = 0x4E89, 0x4E8A, 0x4E8B, 0x4E8C, 0x4E8D, 0x4E8E
local RUN_BANK = 0xC8

local function rd(a) return emu.read(a, WR) end
local function wr(a, v) emu.write(a, v, WR) end
local function cursor() return rd(CUR_LO) + rd(CUR_HI) * 256 end

local phases = {
  {name="stand",     btn={}},
  {name="run_up",    btn={up=true},    runStart=0x12BA},
  {name="run_right", btn={right=true}, runStart=0x12DB},
  {name="run_down",  btn={down=true},  runStart=0x12FC},
  {name="run_left",  btn={left=true},  runStart=0x131D},
}
for i, p in ipairs(phases) do p.hold = (i == 1) and 20 or 60 end

local frame, loaded, done = 0, false, false
local pi, pstart = 0, 0
local di = 0
local curPtrs = {}      -- {ptr=, d02=, d04=} entries (bank $CB, deduped) since last dump
local lastPtrKey = nil
local indexLines = {}

local function startPhase(i)
  pi = i; pstart = frame
  phases[i].written = false
end

local function onLoad()
  if loaded then return end
  local f = io.open(MSS, "rb")
  if not f then emu.log("boy_truth_force: no savestate"); return end
  local d = f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  loaded = true
  startPhase(1)
  emu.log("boy_truth_force: savestate loaded, driving")
end

local function onComposeEntry()
  if not loaded then return end
  local bank = rd(0x28)
  local off  = rd(0x26) + rd(0x27) * 256
  if bank == 0xCB then
    local key = string.format("CB:%04X", off)
    for _, e in ipairs(curPtrs) do if e.ptr == key then return end end
    local d02 = rd(0x02) + rd(0x03) * 256
    local d04 = rd(0x04) + rd(0x05) * 256
    curPtrs[#curPtrs+1] = {ptr=key, d02=d02, d04=d04}
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
  h:write(string.format("# boy_truth_force capture (single-shot force), map=%d\n", rd(0x0ADB)))
  for _, l in ipairs(indexLines) do h:write(l.."\n") end
  h:close()
  emu.log("boy_truth_force: index dumped, "..#indexLines.." frames")
end

local function onFrame()
  local entries = curPtrs
  curPtrs = {}
  frame = frame + 1
  if not loaded or done then return end

  local p = phases[pi]
  local forced = "no"

  -- write the force EXACTLY ONCE, at pstart+6, then hands-off for the rest of the
  -- phase (only reading cursor/pointer/position from here on).
  if pi >= 1 and p.runStart and not p.written and frame == pstart + 6 then
    wr(CUR_LO, p.runStart % 256);  wr(CUR_HI, math.floor(p.runStart / 256))
    wr(LOOP_LO, p.runStart % 256); wr(LOOP_HI, math.floor(p.runStart / 256))
    wr(SCR_BANK, RUN_BANK)
    wr(WAIT, 1)
    forced = "yes"
    p.written = true
  end

  if pi >= 1 then
    table.sort(entries, function(a, b) return a.ptr < b.ptr end)
    local ptrKeys = {}
    for _, e in ipairs(entries) do ptrKeys[#ptrKeys+1] = e.ptr end
    local ptrKey = table.concat(ptrKeys, ",")
    local posStr = (#entries > 0) and string.format("%04X,%04X", entries[1].d02, entries[1].d04) or "-"
    local phaseName = p.name

    dumpMem(OAM, 0x220, string.format("%soam_%04d.bin", OUT, di))
    dumpMem(CG,  0x200, string.format("%scgram_%04d.bin", OUT, di))

    local vramTag = "same"
    if di % 8 == 0 or ptrKey ~= lastPtrKey then
      local vramName = string.format("vram_%04d.bin", di)
      dumpMem(VRAM, 0x10000, OUT..vramName)
      vramTag = vramName
    end
    lastPtrKey = ptrKey

    local cursorTag = string.format("%02X:%04X", rd(SCR_BANK), cursor())
    local ptrField = (#ptrKeys > 0) and ptrKey or "-"

    indexLines[#indexLines+1] = string.format(
      "%d %s boy_ptrs=%s vram=%s cursor=%s forced=%s pos=%s",
      di, phaseName, ptrField, vramTag, cursorTag, forced, posStr)

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
emu.log("boy_truth_force loaded")
