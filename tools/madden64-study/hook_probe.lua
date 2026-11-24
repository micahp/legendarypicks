-- Disposable capability probe; data and states stay in E:/emu/madden64/.
-- Hook semantics and virtual versus physical addresses are not established.
local root = "E:/emu/madden64/"
local out = assert(io.open(root .. "hook-probe.txt", "w"))
local ok, scopes = pcall(event.availableScopes)
out:write("scopes_ok=", tostring(ok), " scopes=", tostring(scopes), "\n")
if ok and type(scopes) == "table" then
  for k, v in pairs(scopes) do out:write(tostring(k), "=", tostring(v), "\n") end
end
local hits = 0
local registered, result = pcall(event.on_bus_exec, function(addr, value, flags)
  hits = hits + 1
end, 0x80025B10, "candidate_event_prepare")
out:write("registered=", tostring(registered), " result=", tostring(result), "\n")
out:flush()
savestate.load(root .. "cpu10.state")
for i = 1, 1500 do emu.frameadvance() end
out:write("frames=1500 hits=", tostring(hits), "\n")
out:close()
client.exit()
