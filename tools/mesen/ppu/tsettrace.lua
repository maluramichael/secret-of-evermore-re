-- Locate the map TILESET blob + its codec by EXECUTION trace.
-- Traps the decompressor dispatcher $8C9C22 (reads DP src/dst/opcode each call)
-- and every VRAM DMA (write to $420B -> read channel regs + $2116 VMADD).
-- Drives input to reach a gameplay map, then dumps VRAM/CGRAM/WRAM at the exact
-- stable moment and flushes the event log. Offline: match VRAM char-base 0x4000
-- <- DMA source <- decompress dst -> the ROM blob + opcode that made the tileset.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/emulator/"
local frame=0
local log={}
local fin=false
local lastmap=-1
local stable=0
local WR=emu.memType.snesWorkRam
local CPU=emu.memType.snesMemory

local function rd(a) return emu.read(a, WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function cpu(a) return emu.read(a, CPU) end

-- $8C9C22 dispatcher entry: caller has set DP $36/$38 = src off/bank,
-- $3A/$3C = dst off/bank. opcode = first byte at [src].
local function onDispatch()
  if fin then return end
  local so=rd16(0x36); local sb=rd(0x38)
  local dof=rd16(0x3A); local db=rd(0x3C)
  local srcAddr=sb*0x10000+so
  local op=cpu(srcAddr)              -- first blob byte = opcode
  local sz=cpu(srcAddr+1)+cpu(srcAddr+2)*256
  log[#log+1]=string.format("DEC f=%d op=%02X src=%02X:%04X(%06X) dst=%02X:%04X sz=%04X",
    frame,op,sb,so,srcAddr,db,dof,sz)
end

-- Any VRAM DMA: fired on write to $420B (MDMAEN). Read enabled channels' regs.
local function onDmaEnable(addr,val)
  if fin then return end
  if val==0 then return end
  local vmadd=cpu(0x2116)+cpu(0x2117)*256   -- VRAM word address
  for ch=0,7 do
    if (val & (1<<ch))~=0 then
      local base=0x4300+ch*0x10
      local ctrl=cpu(base+0)
      local bbus=cpu(base+1)                 -- B-bus target ($18/$19=VRAM data)
      local a_lo=cpu(base+2); local a_hi=cpu(base+3); local a_bk=cpu(base+4)
      local sz=cpu(base+5)+cpu(base+6)*256
      -- keep VRAM-target DMAs (bbus $18/$19), any size (filters CGRAM/OAM noise)
      if bbus==0x18 or bbus==0x19 then
        log[#log+1]=string.format("DMA f=%d ch=%d ctrl=%02X bbus=%02X src=%02X:%02X%02X sz=%04X vmadd=%04X(byte %05X)",
          frame,ch,ctrl,bbus,a_bk,a_hi,a_lo,sz,vmadd,vmadd*2)
      end
    end
  end
end

local function dumpmem(name, memtype, n)
  local h=io.open(OUT..name,"wb"); local step=4096; local i=0
  while i<n do
    local chunk={}; local m=math.min(step,n-i)
    for k=0,m-1 do chunk[k+1]=string.char(emu.read(i+k, memtype)) end
    h:write(table.concat(chunk)); i=i+m
  end
  h:close()
end

local function flush(mapnum,w,h)
  if fin then return end
  fin=true
  dumpmem(string.format("tset_map%d_wram.bin",mapnum), WR, 0x20000)
  dumpmem(string.format("tset_map%d_vram.bin",mapnum), emu.memType.snesVideoRam, 0x10000)
  dumpmem(string.format("tset_map%d_cgram.bin",mapnum), emu.memType.snesCgRam, 0x200)
  local h=io.open(OUT..string.format("tset_map%d_events.txt",mapnum),"w")
  h:write(table.concat(log,"\n").."\n"); h:close()
  emu.log(string.format("tset trace map %d %dx%d events=%d",mapnum,w,h,#log))
  emu.stop(0)
end

local function onInput()
  local btn={}; local p=frame%16
  if frame>60 then if p<4 then btn.start=true elseif p<8 then btn.a=true elseif p<10 then btn.b=true end end
  emu.setInput(0,btn)
end

local function onFrame()
  frame=frame+1
  local mapnum=rd(0x0ADB)
  local w=rd16(0x08EE); local h=rd16(0x08F0)
  if mapnum>0 and w>0 and w<128 and h>0 and h<128 then
    if mapnum==lastmap then stable=stable+1 else stable=0; lastmap=mapnum end
    -- capture on the FIRST stable gameplay map with a decent size (map 16 = 24x15)
    if stable>=30 and mapnum==16 then flush(mapnum,w,h) end
  else
    stable=0; lastmap=-1
  end
  if frame>=12000 then
    if lastmap>0 then flush(lastmap,0,0) else emu.log("no map"); emu.stop(2) end
  end
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
-- $808650 = VRAM-DMA primitive (ch1 src from DP $26/$28, dest VMADD $2116).
local function onVramDma()
  if fin then return end
  local vmadd=rd16(0x2E)              -- $808650: VMADD (VRAM word addr) = DP $2E
  local so=rd16(0x26); local sb=rd(0x28)
  log[#log+1]=string.format("VDMA f=%d src=%02X:%04X vmadd=%04X(byte %05X)",
    frame,sb,so,vmadd,vmadd*2)
end
emu.addMemoryCallback(onDispatch, emu.callbackType.exec, 0x8C9C22, 0x8C9C22)
emu.addMemoryCallback(onVramDma, emu.callbackType.exec, 0x808650, 0x808650)
emu.addMemoryCallback(onDmaEnable, emu.callbackType.write, 0x420B, 0x420B)
emu.log("tsettrace loaded")
