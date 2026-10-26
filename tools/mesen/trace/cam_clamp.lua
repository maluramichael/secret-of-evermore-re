-- Map-56 camera clamp probe (GUI mode): load a save state (SOE_MSS) on map 56, pin entity $7E4EA3/$7E4EA5 (x/y)
-- to a sequence of target positions, log camera $7E0059/$7E005B and save a screenshot per step.
local OUT=(os.getenv("SOE_OUT") or "assets/dumps/trace/").."cam_clamp/"
local MSS=os.getenv("SOE_MSS")
local WR=emu.memType.snesWorkRam
local steps={{600,900},{1320,1450},{1320,20},{20,1450},{20,20}}
local HOLD=400
local frame,loaded,done,si,pstart=0,false,false,1,0
local log=io.open(OUT.."cam_clamp.txt","w")
local function rd16(a) return emu.read(a,WR)+emu.read(a+1,WR)*256 end
local function wr16(a,v) emu.write(a,v%256,WR); emu.write(a+1,math.floor(v/256),WR) end
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
  local s=steps[si]
  wr16(0x4EA3,s[1]); wr16(0x4EA5,s[2])
  if n==si*HOLD-1 then
    log:write(string.format("target=%d,%d  ent=%d,%d  cam=%d,%d  map=%d\n",s[1],s[2],rd16(0x4EA3),rd16(0x4EA5),rd16(0x59),rd16(0x5B),emu.read(0x0ADB,WR))); log:flush()
    local ok,png=pcall(emu.takeScreenshot)
    if ok and png then local h=io.open(string.format("%sclamp_h400_%d_%d.png",OUT,s[1],s[2]),"wb"); h:write(png); h:close() end
    si=si+1
    if si>#steps then done=true; log:write("done\n"); log:close(); emu.stop(0) end
  end
end
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onLoad,emu.callbackType.exec,0x00823A,0x00823A)
