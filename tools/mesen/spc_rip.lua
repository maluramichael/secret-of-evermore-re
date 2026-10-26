-- SoE area-music SPC ripper for Mesen2 headless (--testRunner).
-- Reuses the map-load hijack (see tools/mesen/map_hijack.lua): pin WRAM $0ADB
-- (current map id) to TARGET at the bank-$90 map loader entry $908F68, so the game
-- loads our map through its own complete, natural code path. Loading an area also
-- makes the game start that area's MUSIC on the real SPC700 via its normal flow
-- (NMI sound-handler heartbeat intact -> the song actually sequences and plays).
-- After the area has settled we dump the full APU state for a standard .spc file:
--   spcRam (64KB ARAM) + spcDspRegisters (128B) + spcRom (64B IPL) + SPC700 regs.
--
-- Env: SOE_MAPID map id, SOE_OUT dir+slash, SOE_WAIT frames to let music settle (240),
--   SOE_MINFRAME ignore loader hits before this frame (300).

local TARGET=tonumber(os.getenv("SOE_MAPID") or "16")
local OUT=os.getenv("SOE_OUT") or "assets/dumps/sound/"
local WAIT=tonumber(os.getenv("SOE_WAIT") or "240")
local MINF=tonumber(os.getenv("SOE_MINFRAME") or "300")
local WR=emu.memType.snesWorkRam
local ARAM=emu.memType.spcRam; local DSP=emu.memType.spcDspRegisters; local IPL=emu.memType.spcRom
local frame,loadedAt,dumped=0,nil,false

local function onExec()               -- pin $0ADB=TARGET before `LDA $0ADB`
  if frame<MINF then return end
  emu.write(0x0ADB,TARGET&0xFF,WR); emu.write(0x0ADC,0,WR)
  if not loadedAt then loadedAt=frame end
end
local function envSum() local a=0; for v=0,7 do a=a+emu.read(v*0x10+8,DSP) end; return a end
local function dumpMem(mt,len,path) local h=io.open(path,"wb"); local b={}
  for i=0,len-1 do b[#b+1]=string.char(emu.read(i,mt)); if #b>=8192 then h:write(table.concat(b)); b={} end end
  if #b>0 then h:write(table.concat(b)) end; h:close() end
-- Dump only when the song is audibly at a peak (all voices sounding): a fixed-frame
-- snapshot sometimes catches the SPC700 in its idle wait-loop -> a valid-but-silent
-- .spc. Waiting for an envelope peak lands the capture in an active play state, which
-- resumes cleanly in a standalone SPC player. Falls back to a plain dump after PEAKMAX.
local PEAK=tonumber(os.getenv("SOE_PEAK") or "700")
local PEAKMAX=tonumber(os.getenv("SOE_PEAKMAX") or "360")
local function onFrame()
  frame=frame+1
  if dumped then return end
  if loadedAt and frame>=loadedAt+WAIT then
    local e=envSum()
    if e<PEAK and frame<loadedAt+WAIT+PEAKMAX then return end   -- wait for a musical peak
    dumped=true
    dumpMem(ARAM,0x10000,OUT.."aram.bin"); dumpMem(DSP,128,OUT.."dsp.bin"); dumpMem(IPL,64,OUT.."iplrom.bin")
    local st=emu.getState()
    local f=io.open(OUT.."regs.txt","w")
    f:write(string.format("pc=%d a=%d x=%d y=%d psw=%d sp=%d\n",
      st["spc.pc"] or 0,st["spc.a"] or 0,st["spc.x"] or 0,st["spc.y"] or 0,st["spc.ps"] or 0,st["spc.sp"] or 0)); f:close()
    f=io.open(OUT.."info.txt","w")
    f:write(string.format("mapid=%d loadedAt=%d frame=%d envSum=%d cur0E4D=%d\n",
      TARGET,loadedAt,frame,envSum(),emu.read(0x0E4D,WR))); f:close()
    emu.stop(0)
  end
  if frame>=30000 then local f=io.open(OUT.."info.txt","w"); f:write("TIMEOUT no loader hit\n"); f:close(); emu.stop(1) end
end
local function onInput()              -- mash to power through logos/title into gameplay
  local b={}; local p=frame%16
  if frame>60 then if p<4 then b.start=true elseif p<8 then b.a=true elseif p<10 then b.b=true end end
  emu.setInput(0,b)
end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onExec,emu.callbackType.exec,0x908F68,0x908F68)
emu.log(string.format("spc_rip.lua mapid=%d",TARGET))
