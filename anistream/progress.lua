-- anistream: records how much of the video was watched, for AniList sync.
-- Loaded with  --script=...  and  --script-opts=anistream-out=<file>.  Writes a small JSON file when playback ends.
local utils = require 'mp.utils'

local out = mp.get_opt('anistream-out')
local heal = mp.get_opt('anistream-heal') ~= '0'
local prev, expect_jump, heals = nil, false, {}
local skipped = 0
local last = { position = 0, duration = 0, eof = false, early = false, reason = '', started = false }

local function save()
  if not out or out == '' then return end
  local percent = 0
  if last.duration and last.duration > 0 then
    percent = 100 * last.position / last.duration
  end
  if last.eof and percent < 99.9 then percent = 99.9 end   -- a real ending counts as 100%
  local tmp = out .. '.tmp'
  local f = io.open(tmp, 'w')
  if not f then return end
  f:write(utils.format_json({
    percent = percent, position = last.position, duration = last.duration, eof = last.eof, early = last.early, skipped = skipped,
    reason = last.reason, started = last.started,
  }))
  f:close()
  os.remove(out)                       -- os.rename does not overwrite on Windows
  os.rename(tmp, out)
end

-- A segment that keeps timing out is SKIPPED by ffmpeg's HLS demuxer, which shows up as time-pos jumping forward without a
-- seek. Seek back to the start of the gap so the segment is requested again (the source usually has it; it just timed
-- out). Gives up after 3 tries per gap and reports the skipped seconds instead.
mp.register_event('seek', function() expect_jump = true end)
mp.register_event('playback-restart', function() expect_jump = false; prev = nil end)
mp.observe_property('time-pos', 'number', function(_, v)
  if not v then return end
  last.position = v; last.started = true
  if prev and not expect_jump and v - prev > 2.5 and v - prev < 900 and not mp.get_property_bool('seeking', false) then
    local key = tostring(math.floor(prev))
    heals[key] = (heals[key] or 0) + 1
    if heal and heals[key] <= 3 then
      mp.osd_message('Source skipped ' .. math.floor(v - prev) .. 's - retrying', 3)
      expect_jump = true
      local target = math.max(0, prev - 1)
      -- Wait a few seconds first: a rate-limited source (429) only gets angrier if the same request is repeated at once.
      mp.add_timeout(4, function() mp.commandv('seek', tostring(target), 'absolute') end)
      prev = v
      return
    end
    skipped = skipped + (v - prev)
  end
  prev = v
end)
mp.observe_property('duration', 'number', function(_, v)
  if v then last.duration = v end
end)
mp.register_event('end-file', function(ev)
  local reason = ev and ev.reason or ''
  last.reason = reason
  if reason == 'eof' or reason == 'error' then
    -- A broken HLS stream (missing segments) is reported by mpv as 'eof' too. Only a position near the real end is a
    -- finished episode; anything earlier is a stream that died, which must NOT be recorded as watched.
    if last.duration > 0 and last.position < last.duration - 90 then
      last.early = true
    elseif reason == 'eof' then
      last.eof = true
    end
  end
  save()
end)
mp.register_event('shutdown', save)
