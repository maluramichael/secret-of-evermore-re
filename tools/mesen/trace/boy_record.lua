-- Manually driven (walk the Boy yourself): find the routine that renders the controlled Boy. The Boy's OAM sprites are
-- the centre cluster (slots ~8-21) = OAM-shadow bytes $7EAC42 + slot*4. We trap WRITES to
-- that byte range and log the writing PC (via exec-tracked curPC). While you WALK, the Boy's
-- render routine writes there -> its address falls out. Injects no input.
local OUT=(os.getenv("SOE_OUT") or "assets/dumps/trace/").."boy_record.txt"
local WR=emu.memType.snesWorkRam
local OAM=emu.memType.snesSpriteRam
-- boy OAM slots 6..24 -> shadow bytes $7EAC42+6*4 .. +24*4+3
local LO=0x7EAC42+6*4
local HI=0x7EAC42+24*4+3
local curPC=-1
local writers={}   -- pc -> count
local frame=0
local function onExec(a) curPC=a end
local function onWrite(a,v) writers[curPC]=(writers[curPC] or 0)+1 end
local function dump()
  local h=io.open(OUT,"w"); if not h then return end
  h:write(string.format("# writers of Boy OAM-shadow slots 6-24 ($%06X-$%06X), map=%d\n",LO,HI,emu.read(0x0ADB,WR)))
  local k={}; for x in pairs(writers) do k[#k+1]=x end
  table.sort(k,function(a,b) return writers[a]>writers[b] end)
  for _,x in ipairs(k) do h:write(string.format("  $%06X  writes=%d\n",x,writers[x])) end
  if #k==0 then h:write("(no writes yet - walk the Boy)\n") end
  h:close()
end
local function onFrame() frame=frame+1; if frame%30==0 then dump() end end
emu.addMemoryCallback(onExec,emu.callbackType.exec,0x000000,0xFFFFFF)
emu.addMemoryCallback(onWrite,emu.callbackType.write,LO,HI)
emu.addEventCallback(onFrame,emu.eventType.startFrame)
emu.log("boy OAM-slot writer trap loaded - WALK the Boy now")
