-- Trigger on the first NONZERO write into the 7F work buffer (real decompression
-- output, past the zero-fill). From that moment log every ROM data-read (banks
-- $40-$EF, catches either HiROM mirror) and every work-buffer write, in order.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/emulator/"
local frame=0
local seq=0
local started=false
local startFrame=0
local ev={}
local MAX=60000
local fin=false

function flush()
  if fin then return end
  fin=true
  local h=io.open(OUT.."trace_c300src.txt","w"); h:write(table.concat(ev,"\n").."\n"); h:close()
  emu.log("flush seq="..seq.." startFrame="..startFrame)
  emu.stop(1)
end

local function onWork(a,v)
  if fin then return end
  if not started then
    if v==0 or frame<2500 then return end            -- skip zero-fill
    started=true; startFrame=frame
  end
  seq=seq+1; ev[#ev+1]=string.format("W %06X %02X",a,v)
  if seq>=MAX then flush() end
end
local function onRomRead(a,v)
  if fin or not started then return end
  seq=seq+1; ev[#ev+1]=string.format("R %06X %02X",a,v)
  if seq>=MAX then flush() end
end
local function onWorkRead(a,v)
  if fin or not started then return end
  seq=seq+1; ev[#ev+1]=string.format("r %06X %02X",a,v)
  if seq>=MAX then flush() end
end

local function onInput()
  local btn={}; local p=frame%16
  if frame>90 then if p<4 then btn.start=true elseif p<8 then btn.a=true elseif p<10 then btn.b=true end end
  emu.setInput(0,btn)
end
local function onFrame()
  frame=frame+1
  if started and frame>startFrame+3 then flush() end
  if frame>=8000 then flush() end
end
emu.addEventCallback(onInput, emu.eventType.inputPolled)
emu.addEventCallback(onFrame, emu.eventType.startFrame)
emu.addMemoryCallback(onWork, emu.callbackType.write, 0x7FC300, 0x7FD500)
emu.addMemoryCallback(onWorkRead, emu.callbackType.read, 0x7F0000, 0x7FD500)
emu.addMemoryCallback(onRomRead, emu.callbackType.read, 0x408000, 0xEFFFFF)
emu.log("trace3 loaded")
