-- Find who writes the Boy's current-metasprite-pointer field $7E4EF7 (the anim tick).
-- Pin map 56; write cb on $7E4EF7..$7E4EF9; log curPC (via exec cb) + value.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/trace/"
local WINDOW=tonumber(os.getenv("SOE_WINDOW") or "60")
local TARGET=tonumber(os.getenv("SOE_MAPID") or "56")
local WR=emu.memType.snesWorkRam
local frame,armed,armFrame,loadedAt=0,false,0,nil
local curPC=-1
local writers={}
local cbAdded=false
local function rd(a) return emu.read(a,WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function oam() local n=0; for i=0,127 do local y=emu.read(i*4+1,emu.memType.snesSpriteRam); if y~=0 and y<0xE0 then n=n+1 end end; return n end
local function onExec(a) curPC=a end
local function onW(addr,val)
  if not armed then return end
  local e=writers[curPC] or {n=0,addr={}}
  e.n=e.n+1; e.addr[addr]=(e.addr[addr] or 0)+1
  writers[curPC]=e
end
local function onLoader() if frame<300 then return end; emu.write(0x0ADB,TARGET&0xFF,WR); emu.write(0x0ADC,0,WR); if not loadedAt then loadedAt=frame end end
local function dump()
  local h=io.open(OUT.."anim_tick.txt","w")
  h:write(string.format("# map=%d window=%d : writers of $7E4EF7-$7E4EF9\n",rd(0x0ADB),WINDOW))
  local k={}; for x in pairs(writers) do k[#k+1]=x end
  table.sort(k,function(a,b) return writers[a].n>writers[b].n end)
  for _,x in ipairs(k) do
    local a={}; for ad,c in pairs(writers[x].addr) do a[#a+1]=string.format("%06X:%d",ad,c) end
    h:write(string.format("%06X  writes=%d  [%s]\n",x,writers[x].n,table.concat(a," ")))
  end
  if #k==0 then h:write("(no writes - stand frame set once before window)\n") end
  h:close()
end
local function finish(t) dump(); emu.stop(0) end
local function onFrame()
  frame=frame+1
  if armed and frame>=armFrame+WINDOW then finish("ok"); return end
  if not armed then
    local mn=rd(0x0ADB); local w,hh=rd16(0x08EE),rd16(0x08F0)
    if mn==TARGET and w>0 and w<128 and hh>0 and hh<128 and loadedAt and frame>loadedAt+60 and oam()>=1 then
      armed=true; armFrame=frame
      if not cbAdded then
        emu.addMemoryCallback(onExec,emu.callbackType.exec,0x000000,0xFFFFFF)
        emu.addMemoryCallback(onW,emu.callbackType.write,0x7E4EF7,0x7E4EF9)
        cbAdded=true
      end
    end
    if frame>=6000 then finish("cap") end
  end
end
local function onInput() local b={}; local p=frame%16; if frame>60 then if p<4 then b.start=true elseif p<8 then b.a=true elseif p<10 then b.b=true end end; emu.setInput(0,b) end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onLoader,emu.callbackType.exec,0x908F68,0x908F68)
