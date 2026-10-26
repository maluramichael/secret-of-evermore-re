-- Capture the map-arrangement decompression as a READ-ORDER trace + matched WRAM
-- dump. Logs every ROM read in the map-data banks ($DD-$EF => file 0x1D-0x2F) in
-- consumption order into a ring buffer. When a map is stable (mapnum>0, valid
-- dims, unchanged 20 frames) it dumps WRAM and flushes the ring. Offline we then
-- locate the map's own blob region in the read log -> exact codec input order.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/emulator/"
local frame=0
local ring={}
local RN=200000
local ri=0
local rcount=0
local fin=false
local lastmap=-1
local stable=0

local function push(s)
  ri=ri%RN+1; ring[ri]=s; rcount=rcount+1
end

local function onRomRead(a,v)
  if fin then return end
  push(string.format("R %06X %02X",a,v))
end

local function dumpmem(name, memtype, n)
  local h=io.open(OUT..name,"wb")
  local step=4096
  local i=0
  while i<n do
    local chunk={}
    local m=math.min(step,n-i)
    for k=0,m-1 do chunk[k+1]=string.char(emu.read(i+k, memtype)) end
    h:write(table.concat(chunk))
    i=i+m
  end
  h:close()
end

local function flush(mapnum,w,h)
  if fin then return end
  fin=true
  -- WRAM 128K, VRAM 64K, CGRAM 512
  dumpmem(string.format("cap_map%d_wram.bin",mapnum), emu.memType.snesWorkRam, 0x20000)
  dumpmem(string.format("cap_map%d_vram.bin",mapnum), emu.memType.snesVideoRam, 0x10000)
  dumpmem(string.format("cap_map%d_cgram.bin",mapnum), emu.memType.snesCgRam, 0x200)
  -- flush ring in order
  local lines={}
  local start=1
  local total=math.min(rcount,RN)
  local pos
  if rcount<=RN then pos=1 else pos=ri%RN+1 end
  for k=1,total do
    lines[k]=ring[((pos-1+k-1)%RN)+1]
    pos=pos
  end
  local h=io.open(OUT..string.format("cap_map%d_reads.txt",mapnum),"w")
  h:write(table.concat(lines,"\n").."\n"); h:close()
  local s=io.open(OUT..string.format("cap_map%d_state.txt",mapnum),"w")
  s:write(string.format("frame=%d mapnum=%d w=%d h=%d reads=%d\n",frame,mapnum,w,h,rcount)); s:close()
  emu.log(string.format("captured map %d %dx%d reads=%d",mapnum,w,h,rcount))
  emu.stop(0)
end

local function onInput()
  local btn={}; local p=frame%16
  if frame>60 then if p<4 then btn.start=true elseif p<8 then btn.a=true elseif p<10 then btn.b=true end end
  emu.setInput(0,btn)
end

local function onFrame()
  frame=frame+1
  local mapnum=emu.read(0x0ADB, emu.memType.snesWorkRam)
  local w=emu.read(0x08EE, emu.memType.snesWorkRam)+emu.read(0x08EF, emu.memType.snesWorkRam)*256
  local h=emu.read(0x08F0, emu.memType.snesWorkRam)+emu.read(0x08F1, emu.memType.snesWorkRam)*256
  if mapnum>0 and w>0 and w<128 and h>0 and h<128 then
    if mapnum==lastmap then stable=stable+1 else stable=0; lastmap=mapnum end
    if stable>=20 then flush(mapnum,w,h) end
  else
    stable=0; lastmap=-1
  end
  if frame>=12000 then
    if lastmap>0 then flush(lastmap, 0,0) else emu.log("no map"); emu.stop(2) end
  end
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
-- map-data banks: snes $DD8000..$EFFFFF (file 0x1D8000..0x2FFFFF). Both HiROM
-- mirrors: $5D8000.. and $DD8000.. -> watch the high mirror (bank C0+).
emu.addMemoryCallback(onRomRead, emu.callbackType.read, 0x808000, 0xEFFFFF)
emu.log("readtrace loaded")
