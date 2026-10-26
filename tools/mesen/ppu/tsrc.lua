-- Trap the INLINE tileset DMA at $9091C1 (LDA #$2000;STA $2116 ; src 7F:[$0FAA] -> char base 0x4000).
-- Also trap the decompress dispatcher $8C9C22. On map16 stable: dump the staged tileset
-- region 7F:[$0FAA..+0x8000], VRAM, and the event log. Reveals tileset ROM source+codec.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/emulator/"
local frame=0; local log={}; local fin=false
local lastmap=-1; local stable=0
local WR=emu.memType.snesWorkRam; local CPU=emu.memType.snesMemory
local last_faa=0
local function rd(a) return emu.read(a,WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function cpu(a) return emu.read(a,CPU) end

local function dumpmem(name,mt,off,n)
  local h=io.open(OUT..name,"wb"); local i=0
  while i<n do local c={}; local m=math.min(4096,n-i)
    for k=0,m-1 do c[k+1]=string.char(emu.read(off+i+k,mt)) end
    h:write(table.concat(c)); i=i+m end
  h:close()
end

local function onDispatch()
  if fin then return end
  local so=rd16(0x36); local sb=rd(0x38); local sa=sb*0x10000+so
  log[#log+1]=string.format("DEC f=%d op=%02X src=%06X dst=%02X:%04X sz=%04X faa=%04X fac=%04X fc6=%04X f48=%04X",
    frame,cpu(sa),sa,rd(0x3C),rd16(0x3A),cpu(sa+1)+cpu(sa+2)*256,rd16(0x0FAA),rd16(0x0FAC),rd16(0x0FC6),rd16(0x0F48))
end

local staged_done=false
local function onTilesetDma()
  if fin then return end
  local faa=rd16(0x0FAA)
  last_faa=faa
  local mn=rd(0x0ADB)
  log[#log+1]=string.format("TSDMA f=%d map=%d src=7F:%04X -> charbase(word 2000 byte 4000)",frame,mn,faa)
  -- capture the staged tileset AT dma time (source == intended VRAM char base)
  if mn==16 and not staged_done then
    staged_done=true
    dumpmem("tsrc_map16_staged.bin", WR, 0x10000+faa, 0x8000)
  end
end

local function flush()
  if fin then return end; fin=true
  -- tsrc_map16_staged.bin already captured in-callback at the tileset DMA moment.
  dumpmem("tsrc_map16_vram.bin", emu.memType.snesVideoRam, 0, 0x10000)
  dumpmem("tsrc_map16_wram.bin", WR, 0, 0x20000)
  local h=io.open(OUT.."tsrc_map16_events.txt","w")
  h:write(string.format("last_faa=%04X\n",last_faa)..table.concat(log,"\n").."\n"); h:close()
  emu.log("tsrc done faa="..string.format("%04X",last_faa)); emu.stop(0)
end

local function onInput()
  local b={}; local p=frame%16
  if frame>60 then if p<4 then b.start=true elseif p<8 then b.a=true elseif p<10 then b.b=true end end
  emu.setInput(0,b)
end
local function onFrame()
  frame=frame+1
  local mn=rd(0x0ADB); local w=rd16(0x08EE); local h=rd16(0x08F0)
  if mn>0 and w>0 and w<128 and h>0 and h<128 then
    if mn==lastmap then stable=stable+1 else stable=0; lastmap=mn end
    if stable>=30 and mn==16 then flush() end
  else stable=0; lastmap=-1 end
  if frame>=12000 then flush() end
end
emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onDispatch, emu.callbackType.exec, 0x8C9C22, 0x8C9C22)
emu.addMemoryCallback(onTilesetDma, emu.callbackType.exec, 0x9091C1, 0x9091C1)
emu.log("tsrc loaded")
