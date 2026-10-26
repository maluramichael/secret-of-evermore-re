-- Find the caller of sprite_compose $809032 and the entity field holding the metasprite
-- pointer (Europe, Mesen2). Pins map 56. At $809032 the actor's metasprite ptr is DP
-- $26/$27/$28; the caller (the instruction that jumped here) set it. We track curPC via an
-- exec cb and record, on each compose entry: the previous PC (caller) + the $26 pointer +
-- the actor base-attr pal ($06>>1)&7 (Boy=6). Dump caller PCs split boy vs other.
-- Env: SOE_OUT (dir with trailing slash), SOE_WINDOW (default 40), SOE_MAPID (default 56).

local OUT    = os.getenv("SOE_OUT") or
  "assets/dumps/trace/"
local WINDOW = tonumber(os.getenv("SOE_WINDOW") or "40")
local TARGET = tonumber(os.getenv("SOE_MAPID") or "56")
local MINFRAME = 300

local WR  = emu.memType.snesWorkRam
local OAM = emu.memType.snesSpriteRam

local frame, armed, armFrame, loadedAt = 0, false, 0, nil
local prevPC, curPC = -1, -1
local callers = {}   -- pc -> {boy=n, other=n}
local cbAdded = false

local function rd(a) return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a+1)*256 end
local function count_active_oam()
  local n=0; for i=0,127 do local y=emu.read(i*4+1,OAM); if y~=0 and y<0xE0 then n=n+1 end end; return n
end

local function onExecAny(addr) prevPC = curPC; curPC = addr end

local function onCompose(addr)
  if not armed then return end
  local pal = (rd(0x06) >> 1) & 7
  local key = prevPC   -- the caller PC (instruction before entering $809032)
  local e = callers[key] or {boy=0, other=0}
  if pal == 6 then e.boy = e.boy + 1 else e.other = e.other + 1 end
  callers[key] = e
end

local function dump()
  local h = io.open(OUT .. "compose_caller.txt", "w")
  h:write(string.format("# map=%d armFrame=%d window=%d\n\n## callers of $809032 (pc : boy_calls other_calls):\n",
                        rd(0x0ADB), armFrame, WINDOW))
  local keys = {}
  for k in pairs(callers) do keys[#keys+1]=k end
  table.sort(keys, function(a,b) return (callers[a].boy+callers[a].other) > (callers[b].boy+callers[b].other) end)
  for _,k in ipairs(keys) do
    h:write(string.format("%06X  boy=%d other=%d\n", k, callers[k].boy, callers[k].other))
  end
  h:close()
end

local function finish(tag) dump(); emu.log("compose_caller "..tag); emu.stop(0) end

local function onLoader()
  if frame < MINFRAME then return end
  emu.write(0x0ADB, TARGET & 0xFF, WR); emu.write(0x0ADC, 0, WR)
  if not loadedAt then loadedAt = frame end
end

local function onFrame()
  frame = frame + 1
  if armed and frame >= armFrame + WINDOW then finish("ok"); return end
  if not armed then
    local mn=rd(0x0ADB); local w,hh=rd16(0x08EE),rd16(0x08F0)
    if mn==TARGET and w>0 and w<128 and hh>0 and hh<128 and loadedAt and frame>loadedAt+60
       and count_active_oam()>=1 then
      armed=true; armFrame=frame
      if not cbAdded then
        emu.addMemoryCallback(onExecAny, emu.callbackType.exec, 0x000000, 0xFFFFFF)
        emu.addMemoryCallback(onCompose, emu.callbackType.exec, 0x809032, 0x809032)
        cbAdded=true
      end
    end
    if frame>=6000 then finish("cap6000") end
  end
end

local function onInput()
  local b={}; local p=frame%16
  if frame>60 then if p<4 then b.start=true elseif p<8 then b.a=true elseif p<10 then b.b=true end end
  emu.setInput(0,b)
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onLoader, emu.callbackType.exec, 0x908F68, 0x908F68)
emu.log("compose_caller loaded")
