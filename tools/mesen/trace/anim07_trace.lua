-- Find the SoE animation-script interpreter + the Boy metasprite pointers (Europe, Mesen2).
--
-- Two probes, run over a frame window while the attract Boy walks:
--  (A) exec cb on sprite_compose entry $809032: log the metasprite pointer DP $26/$27/$28
--      (24-bit) it is about to read, with the chunk count = byte0 of that metasprite.
--      -> the set of distinct metasprite frames actually rendered (incl. the Boy's).
--  (B) read cb on the Boy anim-script region in bank $07 ($074560..$0745C0): log the PC
--      that reads it (curPC) -> the animation-script interpreter address.
--
-- getState() is illegal in a mem cb; curPC is tracked via an exec cb.
-- Env: SOE_OUT (dir with trailing slash), SOE_WINDOW (default 40).

local OUT    = os.getenv("SOE_OUT") or
  "assets/dumps/trace/"
local WINDOW = tonumber(os.getenv("SOE_WINDOW") or "40")

local WR  = emu.memType.snesWorkRam
local OAM = emu.memType.snesSpriteRam

local COMPOSE = 0x809032
local ANIM_LO, ANIM_HI = 0x074560, 0x0745C0

local frame, armed, armFrame = 0, false, 0
local curPC = -1
local metaptrs = {}        -- "bank:off" -> {count=, n=}
local animreaders = {}     -- pc -> {count, firstoff}
local cbAdded = false

local function rd(a) return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a+1)*256 end

local function count_active_oam()
  local n = 0
  for i=0,127 do local y=emu.read(i*4+1,OAM); if y~=0 and y<0xE0 then n=n+1 end end
  return n
end

local function onExecAny(addr) curPC = addr end

-- (A) at compose entry, sample the metasprite pointer $26/$27/$28 and its count byte
local function onCompose(addr)
  if not armed then return end
  local off = rd(0x26) + rd(0x27)*256
  local bank = rd(0x28)
  -- read count = byte0 of the metasprite at bank:off (CPU bus)
  local cnt = emu.read(bank*0x10000 + off, emu.memType.snesMemory)
  local key = string.format("%02X:%04X", bank, off)
  local e = metaptrs[key] or {count=cnt, n=0}
  e.n = e.n + 1; e.count = cnt
  metaptrs[key] = e
end

-- (B) reads of the Boy anim-script region -> the interpreter PC
local function onAnimRead(addr, val)
  if not armed then return end
  local e = animreaders[curPC] or {n=0, firstoff=addr}
  e.n = e.n + 1
  animreaders[curPC] = e
end

local function dump()
  local h = io.open(OUT .. "anim07.txt", "w")
  h:write(string.format("# window=%d map=%d\n\n## metasprite pointers at compose $809032 (bank:off count seen):\n",
                        WINDOW, rd(0x0ADB)))
  local keys = {}
  for k in pairs(metaptrs) do keys[#keys+1]=k end
  table.sort(keys, function(a,b) return metaptrs[a].n > metaptrs[b].n end)
  for _,k in ipairs(keys) do
    local e = metaptrs[k]
    h:write(string.format("%s  count=%d  seen=%d\n", k, e.count, e.n))
  end
  h:write("\n## anim-script readers (PC -> reads of $074560..$0745C0):\n")
  local pk = {}
  for k in pairs(animreaders) do pk[#pk+1]=k end
  table.sort(pk, function(a,b) return animreaders[a].n > animreaders[b].n end)
  for _,k in ipairs(pk) do
    h:write(string.format("%06X  reads=%d\n", k, animreaders[k].n))
  end
  if #pk == 0 then h:write("(none - Boy anim region not read as a script this window)\n") end
  h:close()
end

local function finish(tag)
  dump()
  emu.log(string.format("anim07 %s metas=%d readers=%d", tag, 0, 0))
  emu.stop(0)
end

local function onFrame()
  frame = frame + 1
  if armed and frame >= armFrame + WINDOW then finish("ok"); return end
  if not armed then
    local mn = rd(0x0ADB); local w,hh = rd16(0x08EE), rd16(0x08F0)
    if mn>0 and mn<0x80 and w>0 and w<128 and hh>0 and hh<128
       and frame>420 and count_active_oam()>=1 then
      armed=true; armFrame=frame
      if not cbAdded then
        emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
        emu.addMemoryCallback(onCompose, emu.callbackType.exec, COMPOSE, COMPOSE)
        emu.addMemoryCallback(onAnimRead, emu.callbackType.read, ANIM_LO, ANIM_HI)
        cbAdded=true
      end
    end
    if frame>=6000 then finish("cap6000") end
  end
end

local function onInput()
  local b={}; local p=frame%16
  if frame>60 then
    if p<4 then b.start=true elseif p<8 then b.a=true elseif p<10 then b.b=true end
  end
  emu.setInput(0,b)
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.log("anim07 loaded")
