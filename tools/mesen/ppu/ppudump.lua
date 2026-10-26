-- Dump the PPU BG configuration (char base, tilemap base, layer enables) for the
-- first stable map, plus WRAM/VRAM/CGRAM. Fills the gap in the earlier dumps: the
-- BG char-base register that a from-VRAM render needs.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/emulator/"
local frame=0
local lastmap=-1
local stable=0
local fin=false

local function onInput()
  local btn={}; local p=frame%16
  if frame>60 then if p<4 then btn.start=true elseif p<8 then btn.a=true elseif p<10 then btn.b=true end end
  emu.setInput(0,btn)
end

local function dumpmem(name, mt, n)
  local h=io.open(OUT..name,"wb"); local i=0
  while i<n do
    local c={}; local m=math.min(4096,n-i)
    for k=0,m-1 do c[k+1]=string.char(emu.read(i+k,mt)) end
    h:write(table.concat(c)); i=i+m
  end
  h:close()
end

local function serialize(t, prefix, out, depth)
  if depth>4 then return end
  for k,v in pairs(t) do
    local key=prefix..tostring(k)
    if type(v)=="table" then serialize(v,key..".",out,depth+1)
    else out[#out+1]=key.."="..tostring(v) end
  end
end

local function flush(mapnum)
  if fin then return end
  fin=true
  local st=emu.getState()
  local out={}
  if st and st.ppu then serialize(st.ppu,"ppu.",out,0) end
  -- keep only BG/mode/layer relevant lines to stay small
  local keep={}
  for _,line in ipairs(out) do
    if line:find("[Bb][Gg]") or line:find("mode") or line:find("[Ll]ayer")
       or line:find("[Tt]ile") or line:find("[Cc]har") or line:find("[Ss]creen")
       or line:find("[Aa]ddr") or line:find("[Ee]nable") then
      keep[#keep+1]=line
    end
  end
  table.sort(keep)
  local h=io.open(OUT..string.format("cap_map%d_ppu.txt",mapnum),"w")
  h:write(string.format("frame=%d mapnum=%d\n",frame,mapnum))
  h:write(table.concat(keep,"\n").."\n"); h:close()
  dumpmem(string.format("cap2_map%d_vram.bin",mapnum), emu.memType.snesVideoRam, 0x10000)
  dumpmem(string.format("cap2_map%d_cgram.bin",mapnum), emu.memType.snesCgRam, 0x200)
  dumpmem(string.format("cap2_map%d_wram.bin",mapnum), emu.memType.snesWorkRam, 0x20000)
  emu.log("ppu dumped map "..mapnum.." lines="..#keep)
  emu.stop(0)
end

local function onFrame()
  frame=frame+1
  local mapnum=emu.read(0x0ADB, emu.memType.snesWorkRam)
  local w=emu.read(0x08EE, emu.memType.snesWorkRam)+emu.read(0x08EF, emu.memType.snesWorkRam)*256
  local h=emu.read(0x08F0, emu.memType.snesWorkRam)+emu.read(0x08F1, emu.memType.snesWorkRam)*256
  if mapnum>0 and w>0 and w<128 and h>0 and h<128 then
    if mapnum==lastmap then stable=stable+1 else stable=0; lastmap=mapnum end
    if stable>=30 then flush(mapnum) end
  else stable=0; lastmap=-1 end
  if frame>=12000 then if lastmap>0 then flush(lastmap) else emu.stop(2) end end
end

emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.log("ppudump loaded")
