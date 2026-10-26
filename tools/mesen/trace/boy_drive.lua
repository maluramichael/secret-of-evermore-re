-- Drive the Boy from a save state and capture his walk animation (Europe, Mesen2).
-- Load .mss, then per direction hold the d-pad for HOLD frames and record every change of
-- the Boy's current-metasprite-ptr $7E4EF7/$7E4EF9 (= the walk frames for that direction),
-- in order, with the writer PC (the anim-tick routine). Also a RUN phase (B held + dir).
-- Env: SOE_OUT (dir with trailing slash), SOE_MSS (Mesen2 save state path), SOE_HOLD (frames/phase, default 48).
local OUT=os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS=os.getenv("SOE_MSS")
local HOLD=tonumber(os.getenv("SOE_HOLD") or "48")
local WR=emu.memType.snesWorkRam
local frame,loaded,loadFrame=0,false,0
local curPC=-1
local phases={
  {name="down",  btn={down=true}},
  {name="up",    btn={up=true}},
  {name="left",  btn={left=true}},
  {name="right", btn={right=true}},
  {name="run_down", btn={down=true,y=true}},   -- SoE dash = hold Y (charge)/B? capture both
  {name="run_right",btn={right=true,y=true}},
}
local seq={}         -- phase name -> ordered list of "bank:off" as they change
local tickPC={}      -- pc -> count (writers of $7E4EF7)
local phaseIdx=0
local phaseStart=0
local lastPtr=nil
local function rd(a) return emu.read(a,WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function ptr() return string.format("%02X:%04X", rd(0x4EF9), rd16(0x4EF7)) end
local function onExec(a) curPC=a end
local function onWrite(addr,val) if loaded then tickPC[curPC]=(tickPC[curPC] or 0)+1 end end
local function startPhase(i)
  phaseIdx=i; phaseStart=frame; lastPtr=nil
  if i>=1 then seq[phases[i].name]={} end
end
local function onLoadOnce()
  if loaded then return end
  local f=io.open(MSS,"rb"); local data=f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(data) end)
  loaded=true; loadFrame=frame; startPhase(1)
end
local function dump()
  local h=io.open(OUT.."boy_drive.txt","w")
  h:write("# map="..rd(0x0ADB).." hold="..HOLD.."\n\n## anim-tick writers of $7E4EF7:\n")
  local k={}; for x in pairs(tickPC) do k[#k+1]=x end
  table.sort(k,function(a,b) return tickPC[a]>tickPC[b] end)
  for _,x in ipairs(k) do h:write(string.format("  %06X  writes=%d\n",x,tickPC[x])) end
  h:write("\n## metasprite-pointer sequence per phase (each distinct frame the anim showed):\n")
  for _,p in ipairs(phases) do
    local s=seq[p.name] or {}
    h:write(string.format("%-9s (%d frames): %s\n", p.name, #s, table.concat(s," ")))
  end
  h:close()
end
local function onFrame()
  frame=frame+1
  if not loaded then if frame>600 then emu.stop(1) end return end
  -- record ptr change for the current phase
  if phaseIdx>=1 then
    local p=ptr()
    if p~=lastPtr then seq[phases[phaseIdx].name][#seq[phases[phaseIdx].name]+1]=p; lastPtr=p end
    if frame>=phaseStart+HOLD then
      if phaseIdx>=#phases then dump(); emu.log("boy_drive done"); emu.stop(0); return end
      startPhase(phaseIdx+1)
    end
  end
end
local function onInput()
  if loaded and phaseIdx>=1 and frame>phaseStart+4 then
    emu.setInput(phases[phaseIdx].btn, 0)
  else
    emu.setInput({up=false,down=false,left=false,right=false,a=false,b=false,x=false,y=false},0)
  end
end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onExec,emu.callbackType.exec,0x000000,0xFFFFFF)
emu.addMemoryCallback(onLoadOnce,emu.callbackType.exec,0x00823A,0x00823A)
emu.addMemoryCallback(onWrite,emu.callbackType.write,0x7E4EF7,0x7E4EF9)
emu.log("boy_drive loaded")
