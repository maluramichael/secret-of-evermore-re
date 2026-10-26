-- Pin map 56 (Boy start map) and find the animation-script interpreter that reads
-- the Boy char-record anim scripts (bank $07), plus the Boy metasprite pointers.
-- Same probes as anim07_trace but with the $908F68 map-pin hijack so the Boy IS present.
-- Env: SOE_OUT (dir with trailing slash), SOE_WINDOW (default 60), SOE_MAPID (default 56).

local OUT    = os.getenv("SOE_OUT") or
  "assets/dumps/trace/"
local WINDOW = tonumber(os.getenv("SOE_WINDOW") or "60")
local TARGET = tonumber(os.getenv("SOE_MAPID") or "56")
local MINFRAME = 300

local WR  = emu.memType.snesWorkRam
local OAM = emu.memType.snesSpriteRam
local CPU = emu.memType.snesMemory

local COMPOSE = 0x809032
local ANIM_LO, ANIM_HI = 0x074560, 0x0745E0   -- Boy anim-script cluster (damage..block)

local frame, armed, armFrame = 0, false, 0
local loadedAt = nil
local curPC = -1
local metaptrs = {}
local animreaders = {}
local animbytes = {}   -- sample (pc, addr, val) of the first anim-region reads
local cbAdded = false

local function rd(a) return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a+1)*256 end

local function count_active_oam()
  local n = 0
  for i=0,127 do local y=emu.read(i*4+1,OAM); if y~=0 and y<0xE0 then n=n+1 end end
  return n
end

local function onExecAny(addr) curPC = addr end

-- pin the map id at the loader entry
local function onLoader()
  if frame < MINFRAME then return end
  emu.write(0x0ADB, TARGET & 0xFF, WR)
  emu.write(0x0ADC, 0, WR)
  if not loadedAt then loadedAt = frame end
end

local function onCompose(addr)
  if not armed then return end
  local off = rd(0x26) + rd(0x27)*256
  local bank = rd(0x28)
  local cnt = emu.read(bank*0x10000 + off, CPU)
  local key = string.format("%02X:%04X", bank, off)
  local e = metaptrs[key] or {count=cnt, n=0}
  e.n = e.n + 1; e.count = cnt
  metaptrs[key] = e
end

local function onAnimRead(addr, val)
  if not armed then return end
  local e = animreaders[curPC] or {n=0}
  e.n = e.n + 1
  animreaders[curPC] = e
  if #animbytes < 64 then
    animbytes[#animbytes+1] = string.format("pc=%06X addr=%06X val=%02X", curPC, addr, val)
  end
end

local function dump()
  local h = io.open(OUT .. "anim07_pin56.txt", "w")
  h:write(string.format("# map=%d loadedAt=%s armFrame=%d window=%d\n\n",
                        rd(0x0ADB), tostring(loadedAt), armFrame, WINDOW))
  h:write("## anim-script readers (PC -> reads of $074560..$0745E0):\n")
  local pk = {}
  for k in pairs(animreaders) do pk[#pk+1]=k end
  table.sort(pk, function(a,b) return animreaders[a].n > animreaders[b].n end)
  for _,k in ipairs(pk) do h:write(string.format("%06X  reads=%d\n", k, animreaders[k].n)) end
  if #pk==0 then h:write("(none)\n") end
  h:write("\n## first anim-region read samples:\n")
  for _,s in ipairs(animbytes) do h:write(s.."\n") end
  h:write("\n## metasprite pointers at compose $809032:\n")
  local keys = {}
  for k in pairs(metaptrs) do keys[#keys+1]=k end
  table.sort(keys, function(a,b) return metaptrs[a].n > metaptrs[b].n end)
  for _,k in ipairs(keys) do
    local e=metaptrs[k]; h:write(string.format("%s  count=%d  seen=%d\n", k, e.count, e.n))
  end
  h:close()
end

local function finish(tag) dump(); emu.log("anim07_pin56 "..tag); emu.stop(0) end

local function onFrame()
  frame = frame + 1
  if armed and frame >= armFrame + WINDOW then finish("ok"); return end
  if not armed then
    local mn = rd(0x0ADB); local w,hh = rd16(0x08EE), rd16(0x08F0)
    if mn==TARGET and w>0 and w<128 and hh>0 and hh<128
       and loadedAt and frame>loadedAt+60 and count_active_oam()>=1 then
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
emu.addMemoryCallback(onLoader, emu.callbackType.exec, 0x908F68, 0x908F68)
emu.log("anim07_pin56 loaded")
