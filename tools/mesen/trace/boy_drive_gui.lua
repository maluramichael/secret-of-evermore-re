-- GUI-mode Boy driver: load the save state (SOE_MSS), walk the Boy each direction,
-- capture the walk metasprite pointers ($7E4EF7) + anim-tick writer PC.
-- Writes boy_drive.txt when done (no emu.stop).
local OUT=os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS=os.getenv("SOE_MSS")
local HOLD=40
local WR=emu.memType.snesWorkRam
local frame,loaded,lf,done=0,false,0,false
local curPC=-1
local phases={
  {name="down", btn={down=true}}, {name="up", btn={up=true}},
  {name="left", btn={left=true}}, {name="right", btn={right=true}},
}
local seq,tickPC={},{}
local pi,pstart,lastPtr=0,0,nil
local function rd(a) return emu.read(a,WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function ptr() return string.format("%02X:%04X", rd(0x4EF9), rd16(0x4EF7)) end
local function onExec(a) curPC=a end
local function onWrite(a,v) if loaded then tickPC[curPC]=(tickPC[curPC] or 0)+1 end end
local function startPhase(i) pi=i; pstart=frame; lastPtr=nil; if i>=1 then seq[phases[i].name]={} end end
local function onLoad() if loaded then return end
  local f=io.open(MSS,"rb"); if not f then emu.log("no mss"); return end
  local d=f:read("*a"); f:close(); pcall(function() emu.loadSavestate(d) end)
  loaded=true; lf=frame; startPhase(1); emu.log("savestate loaded, driving") end
local function dump()
  local h=io.open(OUT.."boy_drive.txt","w")
  h:write("# GUI drive; map="..rd(0x0ADB).." $4218 test\n## anim-tick writers of $7E4EF7:\n")
  local k={}; for x in pairs(tickPC) do k[#k+1]=x end
  table.sort(k,function(a,b) return tickPC[a]>tickPC[b] end)
  for _,x in ipairs(k) do h:write(string.format("  %06X writes=%d\n",x,tickPC[x])) end
  h:write("## metasprite ptr sequence per direction:\n")
  for _,p in ipairs(phases) do local s=seq[p.name] or {}
    h:write(string.format("%-6s(%d): %s\n",p.name,#s,table.concat(s," "))) end
  h:close(); emu.log("boy_drive dumped") end
local function onFrame()
  frame=frame+1
  if not loaded or done then return end
  if pi>=1 then
    local p=ptr()
    if p~=lastPtr then table.insert(seq[phases[pi].name],p); lastPtr=p end
    if frame>=pstart+HOLD then
      if pi>=#phases then dump(); done=true; return end
      startPhase(pi+1)
    end
  end
end
local function onInput()
  if loaded and not done and pi>=1 and frame>pstart+3 then emu.setInput(phases[pi].btn,0)
  else emu.setInput({up=false,down=false,left=false,right=false},0) end
end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onExec,emu.callbackType.exec,0x000000,0xFFFFFF)
emu.addMemoryCallback(onLoad,emu.callbackType.exec,0x00823A,0x00823A)
emu.addMemoryCallback(onWrite,emu.callbackType.write,0x7E4EF7,0x7E4EF9)
emu.log("boy_drive_gui loaded")
