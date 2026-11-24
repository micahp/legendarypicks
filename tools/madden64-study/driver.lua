-- Command-file driver: Claude writes E:/emu/madden64/cmd.txt, this executes it and writes done.txt.
-- Commands (one per line):
--   press <buttons comma-separated> <frames>   hold buttons for N frames, then release 1 frame
--   wait <frames>
--   shot <path.png>
--   save <path.state> | load <path.state>
--   speed <percent>                            e.g. 100, 400, 6400
--   seed <decimal>                             write candidate RNG word (experimental)
--   record <path.csv> <frames>                 sample candidate team counters each frame
--   hookrecord <path.csv> <frames>             capture raw staged records at candidate routine
--   game <path.csv> <maxframes>                stop on experimental end transition
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
      elseif c == "hookrecord" or c == "game" then
        local count = assert(tonumber(b), "hookrecord requires a frame count")
        local out = assert(io.open(a, "w"))
        out:write("frame,quarter,clock,down,distance,yard,team,kind,index,value\n")
        local hits = 0
        local hook = event.on_bus_exec(function()
          hits = hits + 1
          local q = memory.read_u16_be(0x876dc, "RDRAM")
          local clock = memory.read_u16_be(0x87aac, "RDRAM")
          local down = memory.read_s32_be(0x89544, "RDRAM")
          local distance = memory.read_s32_be(0x89548, "RDRAM")
          local yard = memory.read_s32_be(0x8954c, "RDRAM")
          for team = 0, 1 do
            local base = 0x82ca8 + team * 0x214c
            local n = memory.read_s16_be(base, "RDRAM")
            assert(n >= 0 and n <= 30, "invalid staged event count")
            for i = 0, n - 1 do
              local p = base + 2 + i * 4
              local slot = memory.read_u8(p, "RDRAM")
              local kind = memory.read_u8(p + 1, "RDRAM")
              local value = memory.read_s16_be(p + 2, "RDRAM")
              out:write(string.format("%d,%d,%d,%d,%d,%d,%d,event,%d:%d,%d\n",
                emu.framecount(), q, clock, down, distance, yard, team, slot, kind, value))
            end
            for i = 0, 22 do
              local value = memory.read_s16_be(0x82d50 + team * 0x214c + i * 2, "RDRAM")
              if value ~= 0 then
                out:write(string.format("%d,%d,%d,%d,%d,%d,%d,staged,%d,%d\n",
                  emu.framecount(), q, clock, down, distance, yard, team, i, value))
              end
            end
          end
        end, 0x80025b10, "madden_event_prepare")
        assert(hook, "execution hook registration failed")
        local previous = {}
        local saw_fourth_zero, stopped = false, false
        for frame = 1, count do
          emu.frameadvance()
          local q = memory.read_s32_be(0x89538, "RDRAM")
          local clock = memory.read_s32_be(0x8953c, "RDRAM")
          local down = memory.read_s32_be(0x89544, "RDRAM")
          local distance = memory.read_s32_be(0x89548, "RDRAM")
          local yard = memory.read_s32_be(0x8954c, "RDRAM")
          if q == 4 and clock == 0 then saw_fourth_zero = true end
          local state = string.format("%d,%d,%d,%d,%d", q, clock, down, distance, yard)
          if previous.state ~= state then
            out:write(string.format("%d,%s,-1,state,0,0\n", emu.framecount(), state))
            previous.state = state
          end
          for team = 0, 1 do
            for _, index in ipairs({0,1,2,3,4,5,6,7,10,11,12,57}) do
              local key = team * 100 + index
              local value = memory.read_u16_be(0x82d22 + team * 0x214c + 2 * index, "RDRAM")
              if previous[key] ~= value then
                out:write(string.format("%d,%s,%d,total,%d,%d\n", emu.framecount(), state, team, index, value))
                previous[key] = value
              end
            end
          end
          if frame % 600 == 0 then
            out:flush()
            local progress = assert(io.open(W .. "hook-progress.txt", "w"))
            progress:write(string.format("%d/%d frame=%d q=%d clock=%d hits=%d\n", frame, count, emu.framecount(), q, clock, hits))
            progress:close()
          end
          if c == "game" and saw_fourth_zero and q == 6 then
            out:flush()
            client.screenshot(a .. ".end.png")
            savestate.save(a .. ".end.state")
            stopped = true
            break
          end
        end
        assert(event.unregisterbyid(hook), "execution hook unregister failed")
        out:close()
        local status = assert(io.open(W .. "hookrecord-status.txt", "w"))
        status:write("limit=", count, " hits=", hits, " candidate_end=", tostring(stopped), "\n")
        status:close()
        if c == "game" then assert(stopped, "no candidate end transition before frame limit") end
      elseif c == "record" then
        local count = assert(tonumber(b), "record requires a frame count")
        local out = assert(io.open(a, "w"))
        local indices = {0,1,2,3,4,5,6,7,10,11,12,57}
        out:write("frame,team,index,value,rng\n")
        local previous = {}
        for frame = 1, count do
          emu.frameadvance()
          local rng = memory.read_u32_be(0x87998, "RDRAM")
          -- Candidate runtime fields; sentinel rows are not validated event labels.
          for _, field in ipairs({{-1, 0x876DC}, {-2, 0x87AAC}}) do
            local value = memory.read_u16_be(field[2], "RDRAM")
            if previous[field[1]] ~= value then
              out:write(string.format("%d,-1,%d,%d,%u\n", emu.framecount(), field[1], value, rng))
              previous[field[1]] = value
            end
          end
          -- Display-state candidates: down, distance, yard, and play clock.
          -- Negative values occur in kick and transition states; retain them.
          for _, field in ipairs({{-3, 0x89544}, {-4, 0x89548}, {-5, 0x8954C}, {-6, 0x89540}}) do
            local value = memory.read_s32_be(field[2], "RDRAM")
            if previous[field[1]] ~= value then
              out:write(string.format("%d,-1,%d,%d,%u\n", emu.framecount(), field[1], value, rng))
              previous[field[1]] = value
            end
          end
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
          if frame % 600 == 0 then
            out:flush()
            local progress = assert(io.open(W .. "record-progress.txt", "w"))
            progress:write(string.format("%d/%d frame=%d\n", frame, count, emu.framecount()))
            progress:close()
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


