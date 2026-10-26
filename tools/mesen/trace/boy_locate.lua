-- Locate the Boy's metasprite frame(s) in ROM (Europe, Mesen2). Pins map 56.
-- At sprite_compose $809032 the actor's metasprite pointer is DP $26/$27/$28 and the
-- actor base OAM-attr is DP $06 (composer builds each OAM attr = (chunk.flags&7)+[$6]).
-- OBJ palette = ([$6]>>1)&7. The Boy renders with OBJ pal row 6, so we record the
-- $26 pointer + the first 24 metasprite bytes whenever ([$6]>>1)&7 == 6.
-- Output: boy_locate.txt (distinct boy metasprite pointers + bytes).
-- Env: SOE_OUT (dir with trailing slash), SOE_WINDOW (default 90), SOE_MAPID (default 56), SOE_PAL (default 6).

local OUT    = os.getenv("SOE_OUT") or
  "assets/dumps/trace/"
local WINDOW = tonumber(os.getenv("SOE_WINDOW") or "90")
local TARGET = tonumber(os.getenv("SOE_MAPID") or "56")
local WANTPAL = tonumber(os.getenv("SOE_PAL") or "6")
local MINFRAME = 300

local WR  = emu.memType.snesWorkRam
local OAM = emu.memType.snesSpriteRam
local CPU = emu.memType.snesMemory

local frame, armed, armFrame, loadedAt = 0, false, 0, nil
local boymeta = {}    -- "bank:off" -> {count, seen, bytes, pal}
local allpals = {}    -- pal -> count (to see which pals actually render)
local cbAdded = false

local function rd(a) return emu.read(a, WR) end
local function rd16(a) return rd(a) + rd(a+1)*256 end
local function count_active_oam()
  local n=0; for i=0,127 do local y=emu.read(i*4+1,OAM); if y~=0 and y<0xE0 then n=n+1 end end; return n
end

local function onLoader()
  if frame < MINFRAME then return end
  emu.write(0x0ADB, TARGET & 0xFF, WR); emu.write(0x0ADC, 0, WR)
  if not loadedAt then loadedAt = frame end
end

local function onCompose(addr)
  if not armed then return end
  local base_attr = rd(0x06)
  local pal = (base_attr >> 1) & 7
  allpals[pal] = (allpals[pal] or 0) + 1
  if pal ~= WANTPAL then return end
  local off = rd(0x26) + rd(0x27)*256
  local bank = rd(0x28)
  local key = string.format("%02X:%04X", bank, off)
  local e = boymeta[key]
  if not e then
    local bytes = {}
    for i=0,23 do bytes[#bytes+1] = string.format("%02X", emu.read(bank*0x10000+off+i, CPU)) end
    e = {count=emu.read(bank*0x10000+off, CPU), seen=0, bytes=table.concat(bytes," "), pal=pal}
    boymeta[key] = e
  end
  e.seen = e.seen + 1
end

local function dump()
  local h = io.open(OUT .. "boy_locate.txt", "w")
  h:write(string.format("# map=%d want_pal=%d armFrame=%d window=%d\n\n", rd(0x0ADB), WANTPAL, armFrame, WINDOW))
  h:write("## OBJ palettes seen at compose (pal -> count):\n")
  local pk={}; for k in pairs(allpals) do pk[#pk+1]=k end; table.sort(pk)
  for _,k in ipairs(pk) do h:write(string.format("  pal %d: %d\n", k, allpals[k])) end
  h:write("\n## Boy (pal "..WANTPAL..") metasprite pointers (bank:off count seen : first 24 bytes):\n")
  local keys={}; for k in pairs(boymeta) do keys[#keys+1]=k end
  table.sort(keys, function(a,b) return boymeta[a].seen > boymeta[b].seen end)
  for _,k in ipairs(keys) do
    local e=boymeta[k]
    h:write(string.format("%s  count=%d seen=%d : %s\n", k, e.count, e.seen, e.bytes))
  end
  if #keys==0 then h:write("(no pal-"..WANTPAL.." actor composed this window)\n") end
  h:close()
end

local function finish(tag) dump(); emu.log("boy_locate "..tag); emu.stop(0) end

local function onFrame()
  frame = frame + 1
  if armed and frame >= armFrame + WINDOW then finish("ok"); return end
  if not armed then
    local mn=rd(0x0ADB); local w,hh=rd16(0x08EE),rd16(0x08F0)
    if mn==TARGET and w>0 and w<128 and hh>0 and hh<128 and loadedAt and frame>loadedAt+60
       and count_active_oam()>=1 then
      armed=true; armFrame=frame
      if not cbAdded then
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
emu.log("boy_locate loaded")
