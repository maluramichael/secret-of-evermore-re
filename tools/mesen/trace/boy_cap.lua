-- GUI Boy driver: load a save state (SOE_MSS) on map 56, wait until the map is stable,
-- then drive each direction, capturing the walk metasprite-ptr sequence ($7E4EF7) + $4218 + worldX + anim-tick PC.
local OUT=os.getenv("SOE_OUT") or "assets/dumps/trace/"
local MSS=os.getenv("SOE_MSS")
local WR=emu.memType.snesWorkRam
local CPU=emu.memType.snesMemory
local frame,loaded,lf=0,false,0
local phase=0            -- 0=waiting to stabilize; 1..N = drive phases; -1=done
local pstart=0
local STAB=45
local HOLD=70
local curPC=-1
local phases={
  {name="down", btn={down=true,up=false,left=false,right=false}},
  {name="up",   btn={up=true,down=false,left=false,right=false}},
  {name="left", btn={left=true,right=false,up=false,down=false}},
  {name="right",btn={right=true,left=false,up=false,down=false}},
}
local seq,tickPC,dbg={},{},{}
local lastPtr=nil
local function rd(a) return emu.read(a,WR) end
local function rd16(a) return rd(a)+rd(a+1)*256 end
local function ptr() return string.format("%02X:%04X", rd(0x4EF9), rd16(0x4EF7)) end
local function onExec(a) curPC=a end
local function onWrite(a,v) if loaded and phase>=1 then tickPC[curPC]=(tickPC[curPC] or 0)+1 end end
local function onLoad() if loaded then return end
  local f=io.open(MSS,"rb"); local d=f:read("*a"); f:close()
  pcall(function() emu.loadSavestate(d) end); loaded=true; lf=frame end
local function dump()
  local h=io.open(OUT.."boy_cap.txt","w")
  h:write("# boy_cap map="..rd(0x0ADB).."\n## per-phase (button, $4218 seen, worldX0->1, metaptr sequence):\n")
  for _,l in ipairs(dbg) do h:write(l.."\n") end
  h:write("## anim-tick writers of $7E4EF7:\n")
  local k={}; for x in pairs(tickPC) do k[#k+1]=x end
  table.sort(k,function(a,b) return tickPC[a]>tickPC[b] end)
  for _,x in ipairs(k) do h:write(string.format("  %06X writes=%d\n",x,tickPC[x])) end
  h:write("## metasprite sequences:\n")
  for _,p in ipairs(phases) do local s=seq[p.name] or {}
    h:write(string.format("%-6s(%d): %s\n",p.name,#s,table.concat(s," "))) end
  h:close()
end
local px0
local seen4218
local function startPhase(i)
  phase=i; pstart=frame; lastPtr=nil
  if i>=1 and i<=#phases then seq[phases[i].name]={}; px0=rd16(0x4F17); seen4218={} end
end
local function onFrame()
  frame=frame+1
  if not loaded then return end
  if phase==0 then
    if rd(0x0ADB)==56 and frame>=lf+STAB then startPhase(1) end
    return
  end
  if phase>=1 and phase<=#phases then
    local nm=phases[phase].name
    local p=ptr(); if p~=lastPtr then table.insert(seq[nm],p); lastPtr=p end
    seen4218[string.format("%04X",emu.read(0x4218,CPU))]=true
    if frame>=pstart+HOLD then
      local s={}; for k in pairs(seen4218) do s[#s+1]=k end
      dbg[#dbg+1]=string.format("%-6s btn=%s  4218={%s}  wx %04X->%04X  seq=%d",
        nm, nm, table.concat(s,","), px0, rd16(0x4F17), #seq[nm])
      if phase>=#phases then dump(); phase=-1; emu.log("boy_cap done"); return end
      startPhase(phase+1)
    end
  end
end
local function onInput()
  if loaded and phase>=1 and phase<=#phases and frame>pstart+3 then
    emu.setInput(phases[phase].btn, 0)
  end
end
emu.addEventCallback(onInput,emu.eventType.inputPolled)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.addMemoryCallback(onExec,emu.callbackType.exec,0x000000,0xFFFFFF)
emu.addMemoryCallback(onLoad,emu.callbackType.exec,0x00823A,0x00823A)
emu.addMemoryCallback(onWrite,emu.callbackType.write,0x7E4EF7,0x7E4EF9)
emu.log("boy_cap loaded")
