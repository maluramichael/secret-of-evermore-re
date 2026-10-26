-- Minimal, robust: dump WRAM/VRAM/CGRAM for the first map that is stable for 60
-- frames after frame 4000 (past the intro -> real gameplay screen, tileset in VRAM).
local OUT=(os.getenv("SOE_OUT") or "assets/dumps/emulator/").."grab_"
local WRAM=emu.memType.snesWorkRam
local VRAM=emu.memType.snesVideoRam
local CGRAM=emu.memType.snesCgRam
local frame=0
local sm,ss=-1,0
local done=false
local function rd(o) return emu.read(o,WRAM) end
local function rd16(o) return emu.read(o,WRAM)+emu.read(o+1,WRAM)*256 end
local function dumpMem(mt,st,len,path)
  local h=io.open(path,"wb"); local b={}
  for i=0,len-1 do b[#b+1]=string.char(emu.read(st+i,mt)); if #b>=4096 then h:write(table.concat(b)); b={} end end
  if #b>0 then h:write(table.concat(b)) end; h:close()
end
local function onInput()
  local btn={}; local p=frame%16
  if frame>90 then if p<4 then btn.start=true elseif p<8 then btn.a=true elseif p<10 then btn.b=true end end
  emu.setInput(0,btn)
end
local function onFrame()
  frame=frame+1
  if done then return end
  local mn=rd(0x0ADB); local w=rd16(0x08EE); local h=rd16(0x08F0)
  if frame>4000 and mn>0 and w>0 and w<=64 and h>0 and h<=64 then
    if mn==sm then ss=ss+1 else sm=mn; ss=0 end
    if ss==60 then
      done=true
      local tag=string.format("%02X",mn)
      dumpMem(WRAM,0,0x20000,OUT..tag.."_wram.bin")
      dumpMem(VRAM,0,0x10000,OUT..tag.."_vram.bin")
      dumpMem(CGRAM,0,0x200,OUT..tag.."_cgram.bin")
      local hh=io.open(OUT..tag.."_info.txt","w"); hh:write(string.format("frame=%d mapnum=%d w=%d h=%d\n",frame,mn,w,h)); hh:close()
      emu.stop(mn)
    end
  end
  if frame>=30000 then emu.stop(0) end
end
emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
