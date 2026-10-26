-- Map-56 camera edge probe (GUI mode): load a save state (SOE_MSS) on map 56, hold
-- up / left in phases, save a screenshot every 30 frames so the camera position can be matched against
-- a rendered image of map 56. Also logs PPU BG1 scroll.
local OUT=(os.getenv("SOE_OUT") or "assets/dumps/trace/").."cam_edge/"
local MSS=os.getenv("SOE_MSS")
local phases={{up=true},{left=true},{up=true},{up=true,left=true},{left=true},{up=true},{right=true},{up=true}}
local HOLD=240
local frame,loaded,done,pi,pstart=0,false,false,1,0
local log=io.open(OUT.."cam_edge.txt","w")
local function onLoad()
  if loaded then return end
  local f=io.open(MSS,"rb"); local d=f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end)
  loaded=true; pstart=frame
end
local function onFrame()
  frame=frame+1
  if not loaded or done then return end
  local n=frame-pstart
  if n%30==0 then
    local s=emu.getState()
    log:write(string.format("f=%d phase=%d bg1h=%s bg1v=%s map=%d\n", n, pi,
      tostring(s["ppu.layers[0].hscroll"]), tostring(s["ppu.layers[0].vscroll"]),
      emu.read(0x0ADB, emu.memType.snesWorkRam))); log:flush()
    local ok,png=pcall(emu.takeScreenshot)
    if ok and png then local h=io.open(string.format("%sshot_%04d.png",OUT,n),"wb"); h:write(png); h:close() end
    local t={} for a=0,0xFFFF do t[#t+1]=string.char(emu.read(a,emu.memType.snesWorkRam)) end
    local w=io.open(string.format("%swram_%04d.bin",OUT,n),"wb"); w:write(table.concat(t)); w:close()
  end
  if n>=pi*HOLD then pi=pi+1; if pi>#phases then done=true; log:write("done\n"); log:close(); emu.stop(0) end end
end
local function onInput()
  if loaded and not done and pi<=#phases then emu.setInput(phases[pi],0)
  else emu.setInput({},0) end
end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onLoad,emu.callbackType.exec,0x00823A,0x00823A)
emu.log("cam_edge loaded")
