-- Command-file driver: Claude writes E:/emu/madden64/cmd.txt, this executes it and writes done.txt.
-- Commands (one per line):
--   press <buttons comma-separated> <frames>   hold buttons for N frames, then release 1 frame
--   wait <frames>
--   shot <path.png>
--   save <path.state> | load <path.state>
--   speed <percent>                            e.g. 100, 400, 6400
--   seed <decimal>                             write candidate RNG word (experimental)
--   record <path.csv> <frames>                 sample candidate team counters each frame
--   dumpram <path>                             first 0x90000 bytes of N64 RDRAM
local W = "E:/emu/madden64/"
client.SetSoundOn(false)
local f = io.open(W .. "buttons.txt", "w")
for k, _ in pairs(joypad.get()) do f:write(k .. "\n") end
f:close()

local function exists(p) local h = io.open(p, "r"); if h then h:close(); return true end; return false end
local function hold(btns, n)
  local t = {}
  for b in string.gmatch(btns, "[^,]+") do t["P1 " .. b] = true end
  for i = 1, n do joypad.set(t); emu.frameadvance() end
  emu.frameadvance()
end

while true do
  if exists(W .. "cmd.txt") then
    local lines = {}
    for l in io.lines(W .. "cmd.txt") do lines[#lines + 1] = l end
    os.remove(W .. "cmd.txt")
    local log = {}
    for _, l in ipairs(lines) do
      local c, a, b = string.match(l, "^(%S+)%s+(.+)%s+(%d+)$"); if not c then c, a = string.match(l, "^(%S+)%s*(%S*)"); b = nil end
      if c == "press" then hold(a, tonumber(b) or 4)
      elseif c == "wait" then for i = 1, tonumber(a) do emu.frameadvance() end
      elseif c == "shot" then client.screenshot(a)
      elseif c == "save" then savestate.save(a)
      elseif c == "load" then savestate.load(a)
      elseif c == "speed" then client.speedmode(tonumber(a))
      elseif c == "seed" then
        local seed = tonumber(a)
        assert(seed and seed >= 0 and seed <= 0xFFFFFFFF, "invalid RNG seed")
        memory.write_u32_be(0x87998, seed, "RDRAM")
      elseif c == "record" then
        local count = assert(tonumber(b), "record requires a frame count")
        local out = assert(io.open(a, "w"))
        local indices = {0,1,2,3,4,5,6,7,10,11,12,57}
        out:write("frame,team,index,value,rng\n")
        local previous = {}
        for frame = 1, count do
          emu.frameadvance()
          local rng = memory.read_u32_be(0x87998, "RDRAM")
          for team = 0, 1 do
            for _, index in ipairs(indices) do
              local key = team * 100 + index
              local value = memory.read_u16_be(0x82d22 + team * 0x214c + index * 2, "RDRAM")
              if previous[key] ~= value then
                out:write(string.format("%d,%d,%d,%d,%u\n", emu.framecount(), team, index, value, rng))
                previous[key] = value
              end
            end
          end
        end
        out:close()
      elseif c == "dumpram" then
        local h = io.open(a, "wb")
        for i = 0, 0x8FFFF do h:write(string.char(memory.read_u8(i, "RDRAM"))) end
        h:close()
      end
      log[#log + 1] = l
    end
    local d = io.open(W .. "done.txt", "w"); d:write(emu.framecount() .. "\n" .. table.concat(log, "\n")); d:close()
  end
  emu.frameadvance()
end


