-- Drive Boy from a free-roam save state, capture the metasprite the compositor renders
-- for pal-6 (Boy) via a trap on sprite_compose $809032. Raw distinct sequence per input.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS=os.getenv("SOE_MSS")
local WR=emu.memType.snesWorkRam
local frame,loaded,lf=0,false,0
local phase,pstart=0,0
local STAB,HOLD=60,120
local phases={
  {name="down", btn={down=true,up=false,left=false,right=false}},
  {name="up",   btn={up=true,down=false,left=false,right=false}},
  {name="left", btn={left=true,right=false,up=false,down=false}},
  {name="right",btn={right=true,left=false,up=false,down=false}},
}
local seq,lastP={},{}
local function rd(a) return emu.read(a,WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function onLoad() if loaded then return end
  local f=io.open(MSS,"rb"); if not f then emu.log("MSS OPEN FAILED"); return end
  local d=f:read("*a"); f:close()
  local ok=pcall(function() emu.loadSavestate(d) end)
  emu.log("loadSavestate ok="..tostring(ok).." len="..#d); loaded=true; lf=frame end
local function onCompose(a)
  if not loaded or phase<1 or phase>#phases then return end
  if ((rd(0x06)>>1)&7)~=6 then return end
  local p=string.format("%02X:%04X", rd(0x28), rd16(0x26))
  local nm=phases[phase].name
  if p~=lastP[nm] then table.insert(seq[nm],p); lastP[nm]=p end
end
local function startPhase(i) phase=i; pstart=frame; if i>=1 and i<=#phases then seq[phases[i].name]={}; lastP[phases[i].name]=nil end end
local function dump()
  local h=io.open(OUT.."boy_cap3.txt","w")
  h:write("# boy_cap3 map="..rd(0x0ADB).." (free-roam save state)\n")
  for _,p in ipairs(phases) do local s=seq[p.name] or {}
    h:write(string.format("%-6s(%d): %s\n",p.name,#s,table.concat(s," "))) end
  h:close(); emu.log("boy_cap3 done")
end
local function onFrame()
  frame=frame+1
  if not loaded then return end
  if phase==0 then if rd(0x0ADB)>0 and frame>=lf+STAB then startPhase(1) end return end
  if phase>=1 and phase<=#phases and frame>=pstart+HOLD then
    if phase>=#phases then dump(); phase=-1; return end
    startPhase(phase+1)
  end
end
local function onInput() if loaded and phase>=1 and phase<=#phases and frame>pstart+3 then emu.setInput(phases[phase].btn,0) end end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onCompose,emu.callbackType.exec,0x809032,0x809032)
emu.addMemoryCallback(onLoad,emu.callbackType.exec,0x00823A,0x00823A)
emu.log("boy_cap3 loaded")
