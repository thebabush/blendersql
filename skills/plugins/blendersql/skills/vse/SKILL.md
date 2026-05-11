---
name: vse
description: "The Video Sequence Editor — vse_strips plus the per-type side tables (sound/movie/image/scene/text/color). Use to inspect a sequencer timeline or add strips."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

A scene's sequencer timeline. `vse_strips` is the spine — one row per strip with the common timeline fields — and each strip type has a side table with its type-specific settings, joined on `(scene, strip)` (the strip name).

---

## Tables

| Table | Key columns |
|---|---|
| `vse_strips` | `scene`, `name`, `type` (`SOUND`/`MOVIE`/`IMAGE`/`SCENE`/`TEXT`/`COLOR`/`META`/effects), `channel`, `frame_start`, `frame_final_duration`, `frame_final_end`, `frame_offset_start`, `frame_offset_end`, `mute`, `lock`, `select`, `blend_type`, `blend_alpha`, `parent_meta` |
| `vse_strip_sound` | `scene`, `strip`, `sound`, `volume`, `pan`, `pitch_correction`, `show_waveform` |
| `vse_strip_movie` | `scene`, `strip`, `filepath`, `stream_index`, `fps` |
| `vse_strip_image` | `scene`, `strip`, `directory`, `frame_offset_start`, `animation_offset_start` |
| `vse_strip_scene` | `scene`, `strip`, `source_scene`, `scene_camera`, `scene_input` |
| `vse_strip_text` | `scene`, `strip`, `text`, `font`, `font_size`, `color_r/g/b/a`, `location_x/y`, `wrap_width`, `alignment_x`, `anchor_x`, `anchor_y`, `use_shadow`, `use_outline` |
| `vse_strip_color` | `scene`, `strip`, `color_r/g/b` |

All read-only. `select` is a SQL keyword — quote it. `scenes.sequence_strip_count` tells you which scenes have a sequencer. Discovery: `PRAGMA table_info(vse_strips);`

---

## Common Queries

```sql
-- Strips on a scene's timeline, sorted by channel/time
SELECT name, type, channel, frame_start, frame_final_duration, frame_final_end, mute, lock
FROM vse_strips WHERE scene='Edit' ORDER BY channel, frame_start;

-- Strip-type histogram
SELECT type, COUNT(*) FROM vse_strips WHERE scene='Edit' GROUP BY type ORDER BY 2 DESC;

-- Sound strips with their volume / source sound
SELECT s.name, s.channel, s.frame_start, snd.sound, snd.volume, snd.pan
FROM vse_strips s JOIN vse_strip_sound snd ON snd.scene=s.scene AND snd.strip=s.name
WHERE s.scene='Edit' ORDER BY s.frame_start;

-- Movie strips and the files they reference
SELECT s.name, m.filepath, m.fps FROM vse_strips s
JOIN vse_strip_movie m ON m.scene=s.scene AND m.strip=s.name WHERE s.type='MOVIE';

-- Text overlays and their content
SELECT s.name, s.frame_start, t.text, t.font_size, t.alignment_x FROM vse_strips s
JOIN vse_strip_text t ON t.scene=s.scene AND t.strip=s.name WHERE s.type='TEXT';

-- Scene strips: which scene is nested where, and with what camera
SELECT s.name, sc.source_scene, sc.scene_camera, sc.scene_input FROM vse_strips s
JOIN vse_strip_scene sc ON sc.scene=s.scene AND sc.strip=s.name;

-- Strips inside a meta strip
SELECT name, type, channel, frame_start FROM vse_strips WHERE scene='Edit' AND parent_meta='Intro';

-- Timeline gaps on a channel (consecutive strips on channel 1)
SELECT name, frame_start, frame_final_end,
       frame_start - LAG(frame_final_end) OVER (ORDER BY frame_start) AS gap_before
FROM vse_strips WHERE scene='Edit' AND channel=1 ORDER BY frame_start;
```

---

## Writing

The VSE tables are read-only. To build a timeline, use the `vse_add_*` verbs (SQL functions returning a `{ok, result, error}` JSON envelope — failure is *in the JSON*). Each takes the *scene name*, a source, a channel, and a start frame; `frame_end` is optional and converted to a length internally. A sequence editor is auto-created on the scene if it has none.

```sql
-- Sound strip: needs a sound datablock that already exists in bpy.data.sounds
SELECT vse_add_sound('Edit', 'voiceover.wav', 2, 1);            -- channel 2, starts at frame 1

-- Movie strip: takes a filepath directly (not a datablock)
SELECT vse_add_movie('Edit', '/footage/take01.mp4', 1, 1);

-- Scene strip: nest another scene
SELECT vse_add_scene_strip('Edit', 'Shot_010', 3, 24);         -- source scene 'Shot_010', channel 3, frame 24

-- Text strip (optional frame_end as the 5th arg)
SELECT vse_add_text('Edit', 'Title Card', 4, 1);
SELECT vse_add_text('Edit', 'Title Card', 4, 1, 60);           -- ends at frame 60

-- Color strip (color is a JSON [r,g,b])
SELECT vse_add_color('Edit', '[0,0,0]', 1, 1);
SELECT vse_add_color('Edit', '[1,1,1]', 1, 1, 30);
```

For anything else — splitting, moving, trimming, transitions, retiming, deleting strips, editing strip properties — use `bpy_op` (the `python` skill), e.g. `bpy_op('sequencer.split', ...)`, or `bpy_exec` to poke `scene.sequence_editor.strips['X'].volume = 0.5`.

---

## Gotchas

- The side tables join to `vse_strips` on **`(scene, strip)`** where `strip` is the strip *name* — strip names are unique within a scene's sequencer.
- `vse_add_sound` wants a `bpy.data.sounds` datablock by name; if you only have a file path, create the sound first (`bpy_exec('bpy.data.sounds.load("/path.wav")')`) or use `bpy_op('sequencer.sound_strip_add', ...)`.
- `frame_final_duration` / `frame_final_end` reflect offsets and speed effects; `frame_start` + raw length isn't always `frame_final_end`.
- META and effect strips (`CROSS`, `WIPE`, `SPEED`, `TRANSFORM`, …) appear in `vse_strips` but have no dedicated side table — read their extra fields with `bpy_exec`.
- Editing strip properties or removing strips isn't a row write here — go through `bpy_op`/`bpy_exec`.
