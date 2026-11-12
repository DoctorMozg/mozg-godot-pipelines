# Game audio implementation (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.0–4.7), the 4.3–4.7 release notes, Godot audio source on master and the FMOD/Wwise integration repos. Loudness targets rest on secondary sources; probes are UNTESTED on 4.7.2.

## Executive summary

Godot audio is built on named buses stored in `res://default_bus_layout.tres`. Sends only flow leftward toward Master, and players pick their bus by name. A misspelled or missing bus name fails silently to Master. Since 4.3 the engine has adaptive-music resources (AudioStreamInteractive, AudioStreamPlaylist, AudioStreamSynchronized), the AudioEffectHardLimiter, and web "Sample" playback. Sample playback skips all bus effects. Since 4.4, WAV imports default to lossy QOA compression, and `volume_linear` exists on players. Most audio quality problems can be checked from files: the bus layout, the `.import` params, the `bus =` lines in `.tscn` files, and asset loudness measured with ffmpeg `ebur128`. Headless runs use the Dummy driver. The source shows it still mixes on a thread, so bus capture is plausible, but nobody has tried it in practice yet (UNVERIFIED).

## 1. Buses and layout

- The leftmost bus is Master. "Routing always passes audio from buses on the right to buses further to the left." Keep the Master bus below 0 dB. Effects on a bus run in order. The layout is saved automatically to `res://default_bus_layout.tres`. Source: https://docs.godotengine.org/en/stable/tutorials/audio/audio_buses.html (4.7)
- Players store the bus **name**. "At runtime, if no bus with the given name exists, all sounds will fall back on 'Master'." Renaming a bus therefore breaks every player that used the old name. Source: https://docs.godotengine.org/en/stable/classes/class_audiostreamplayer.html (4.7)
- In the mixer, a send to a bus that doesn't exist, or to a bus at the same index or further right, goes to Master. The code is `if (!bus_map.has(bus->send)) send = buses[0];` with the comment "Invalid, send to master". Source: https://raw.githubusercontent.com/godotengine/godot/master/servers/audio/audio_server.cpp (master, read 2026-11)
- Serialized keys are `bus/<i>/name|solo|mute|bypass_fx|volume_db|send` and `bus/<i>/effect/<j>/effect|enabled`. Source: https://raw.githubusercontent.com/godotengine/godot/master/servers/audio/audio_bus_layout.cpp
- The project settings `audio/buses/default_bus_layout` = `res://default_bus_layout.tres`, `channel_disable_threshold_db` = -60 and `channel_disable_time` = 2.0 control auto-disable. A bus that stays silent for that long is disabled, including its effects. Source: https://docs.godotengine.org/en/stable/classes/class_projectsettings.html (4.7)
- A typical layout is `Master` ← `Music`, `SFX`, `Voice`, `UI`, `Ambience`, with reverb buses fed by Area3D. This naming is common practice, not something the engine requires.
- **Master limiter:** "Adding a limiter as the last effect of the Master bus is good practice." AudioEffectHardLimiter has `ceiling_db` = -0.3, `pre_gain_db` = 0 and `release` = 0.1 s. AudioEffectLimiter is deprecated, and its properties "have no effect". Sources: https://docs.godotengine.org/en/stable/tutorials/audio/audio_effects.html, https://docs.godotengine.org/en/stable/classes/class_audioeffecthardlimiter.html, https://docs.godotengine.org/en/stable/classes/class_audioeffectlimiter.html (4.7). HardLimiter exists in the 4.3 docs and not in 4.2 (the 4.2 page returns 404).
- **Ducking:** put an AudioEffectCompressor on `Music` and set `sidechain` to `&"Voice"`. Defaults are threshold 0 dB, ratio 4, attack 20 µs, release 250 ms. Lower the threshold, because at 0 dB the compressor barely triggers. Source: https://docs.godotengine.org/en/stable/classes/class_audioeffectcompressor.html (4.7)

```gdscript
var comp := AudioEffectCompressor.new()
comp.sidechain = &"Voice"; comp.threshold = -24.0; comp.ratio = 6.0
AudioServer.add_bus_effect(AudioServer.get_bus_index(&"Music"), comp)
```

## 2. Players, polyphony, voice management

- **AudioStreamPlayer** is non-positional: UI and music. **AudioStreamPlayer2D** pans by screen position. **AudioStreamPlayer3D** supports stereo, 5.1 and 7.1, Doppler and Area3D reverb. Source: https://docs.godotengine.org/en/stable/tutorials/audio/audio_streams.html (4.7, which says it is "not yet updated for 4.7")
- `max_polyphony` defaults to 1. Calling `play()` past the limit "cuts off the oldest sounds", which is the built-in voice stealing. The property has existed since 4.0. Sources: the class page above, https://docs.godotengine.org/en/4.0/classes/class_audiostreamplayer.html
- `finished` is not emitted after `stop()`, when the node exits the tree, or for looping streams. Sources: the AudioStreamPlayer page and the import docs.
- **AudioStreamPolyphonic** (since 4.0, default polyphony 32): `play_stream(stream, from_offset, volume_db, pitch_scale, playback_type, bus)` returns an id, or `INVALID_ID` (-1) when it is full. Source: https://docs.godotengine.org/en/stable/classes/class_audiostreamplaybackpolyphonic.html. One polyphonic player on an autoload can replace a hand-rolled node pool for fire-and-forget SFX.

```gdscript
# Autoload "Sfx" with an AudioStreamPlayer whose stream = AudioStreamPolyphonic
func play(s: AudioStream, db := 0.0) -> int:
    if not $P.playing: $P.play()
    var pb := $P.get_stream_playback() as AudioStreamPlaybackPolyphonic
    return pb.play_stream(s, 0.0, db, 1.0, AudioServer.PLAYBACK_TYPE_DEFAULT, &"SFX")
```

- **AudioStreamRandomizer** (since 4.0) has `playback_mode` (default RANDOM_NO_REPEATS), `random_pitch`, `random_volume_offset_db`, and weighted `add_stream(i, s, weight)`. `random_pitch_semitones` arrived in **4.6**: it is listed in the 4.6 docs and not in 4.5. Source: https://docs.godotengine.org/en/stable/classes/class_audiostreamrandomizer.html
- CONFLICT DETECTED: the 4.0 docs give `random_pitch` = 1.1 and `random_volume_offset_db` = 5.0, while the 4.7 docs give 1.0 and 0.0. Check which defaults the project's version actually uses. Sources: https://docs.godotengine.org/en/4.0/classes/class_audiostreamrandomizer.html vs the stable page.

## 3. Adaptive music (4.3+)

- The 4.3 release added AudioStreamInteractive, AudioStreamPlaylist and AudioStreamSynchronized "to build your own dynamic music system". Source: https://godotengine.org/releases/4.3/
- **Interactive** has clips, `initial_clip` and `add_transition(from, to, from_time, to_time, fade_mode, fade_beats, use_filler, filler, hold_previous)`.
  - from_time: IMMEDIATE, NEXT_BEAT, NEXT_BAR, END.
  - to_time: SAME_POSITION, START, PREVIOUS_POSITION.
  - Auto-advance is ignored on looping clips.
  - `get_playback_position()` always returns 0 for this stream.
  - At runtime, switch clips with `AudioStreamPlaybackInteractive.switch_to_clip_by_name()` on the player's `get_stream_playback()`. That page was not fetched, so the exact signature is UNVERIFIED.
  - Source: https://docs.godotengine.org/en/stable/classes/class_audiostreaminteractive.html
- **Playlist:** `fade_time` 0.3, `loop` true, `shuffle` false, MAX_STREAMS 64. **Synchronized** plays sub-streams in sync, with `set_sync_stream_volume(i, db)` for vertical layering. Sources: https://docs.godotengine.org/en/stable/classes/class_audiostreamplaylist.html, https://docs.godotengine.org/en/stable/classes/class_audiostreamsynchronized.html
- Beat-aware transitions need `bpm`, `beat_count` and `bar_beats` on the Ogg/MP3 stream. `beat_count` "sets the end of the audio for looping and for AudioStreamPlaylist and AudioStreamInteractive." Source: https://docs.godotengine.org/en/stable/classes/class_audiostreamoggvorbis.html
- CONFLICT DETECTED: the import tutorial (4.2 and 4.4 pages) says BPM, beat count and bar beats are "currently unused", while the class reference says Playlist and Interactive use them. The tutorial looks stale, so trust the class reference. Sources: https://docs.godotengine.org/en/4.4/tutorials/assets_pipeline/importing_audio_samples.html and the OggVorbis class page.

## 4. Import settings

- WAV importer `wav` options and defaults (from source):
  - `force/8_bit` = false, `force/mono` = false
  - `force/max_rate` = false, `force/max_rate_hz` = 44100
  - `edit/trim` = false, `edit/normalize` = false
  - `edit/loop_mode` = 0 (Detect), `edit/loop_begin` = 0, `edit/loop_end` = -1
  - `compress/mode` = 2 (QOA)
  - Source: https://raw.githubusercontent.com/godotengine/godot/master/editor/import/resource_importer_wav.cpp
- Ogg importer `oggvorbisstr` options: `loop` = false, `loop_offset` = 0, `bpm` = 0, `beat_count` = 0, `bar_beats` = 4. MP3 has the same options. Ogg/MP3 support forward looping only, with a loop-begin point. Sources: https://raw.githubusercontent.com/godotengine/godot/master/modules/vorbis/resource_importer_ogg_vorbis.cpp, https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_audio_samples.html
- Recommended formats:
  - WAV for short, frequent SFX, because it is cheap on the CPU.
  - Ogg for music, voice and long SFX.
  - MP3 for low-CPU mobile or web with many simultaneous compressed streams.
  - Source: the same import page (4.7).
- Version notes:
  - QOA became available in **4.3** (listed on the 4.3 page, not on 4.2).
  - QOA became the **default in 4.4**. The 4.4 class reference says "By default, Godot imports WAV files using the lossy Quite OK Audio compression." The 4.4 tutorial still says "Disabled (default)", which is a CONFLICT DETECTED.
  - Runtime WAV loading arrived in 4.4; Ogg could already load at runtime.
  - Sources: https://docs.godotengine.org/en/4.4/classes/class_resourceimporterwav.html, https://godotengine.org/releases/4.4/
- Streaming vs preloaded: Ogg and MP3 are decoded during playback, while WAV is decoded in memory and costs the least CPU. Godot has no explicit "stream from disk" toggle. UNVERIFIED: whether Ogg data stays compressed in RAM rather than being read from disk. No 4.7 doc states this.

## 5. 3D audio

- AudioStreamPlayer3D defaults:
  - `attenuation_model` inverse, `unit_size` 10, `max_db` 3, `max_distance` 0 (meaning unlimited)
  - `attenuation_filter_cutoff_hz` 5000 (set 20500 to disable), `attenuation_filter_db` -24
  - `doppler_tracking` disabled, `area_mask` 0
  - emission angle off (45°)
  - Source: https://docs.godotengine.org/en/stable/classes/class_audiostreamplayer3d.html
- Doppler must be enabled on both the player and the Camera3D. Use Physics tracking when the emitter moves in `_physics_process`. Area3D sends dry and wet signal to reverb buses, and each reverb bus needs a Reverb effect. Source: audio_streams.html (4.7)
- Pan strength comes from the project settings `audio/general/2d_panning_strength` and `3d_panning_strength`, both 0.5. Source: the ProjectSettings page (4.7)

## 6. Latency, sync, web

- `audio/driver/output_latency` = 15 ms, with a web override of 50. `mix_rate` = 44100. Source: the ProjectSettings page (4.7)
- For sync, use `get_playback_position() + AudioServer.get_time_since_last_mix() - AudioServer.get_output_latency()` and drop values lower than the previous frame. `get_output_latency()` is expensive, so cache it. Sources: https://docs.godotengine.org/en/stable/tutorials/audio/sync_with_audio.html, https://docs.godotengine.org/en/stable/classes/class_audioserver.html
- Web (since 4.3): the default playback type is **Sample** (`audio/general/default_playback_type.web` = 1).
  - In Sample mode, "AudioEffects are not supported", and reverb, Doppler and procedural audio don't work.
  - Stream mode restores all features but adds latency when threads are disabled.
  - Browsers need a user gesture before audio can start.
  - Source: https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_web.html (4.7)
  - The `playback_type` property appears in the 4.3 docs and not in 4.2, and is still marked experimental.

## 7. Volume settings, pause, procedural audio

- `linear_to_db()` is meant for sliders. The docs example is `AudioServer.set_bus_volume_db(AudioServer.get_bus_index("Master"), linear_to_db($Slider.value))`. Because `linear_to_db(0)` is -inf, also call `set_bus_mute` at 0. Source: https://docs.godotengine.org/en/stable/classes/class_%40globalscope.html
- `volume_linear` on players arrived in **4.4**: it is on the 4.4 page and not on 4.3. `AudioServer.set_bus_volume_linear` exists in 4.7. The inference that it came from the same Dec 2024 commit is UNVERIFIED. Sources: https://docs.godotengine.org/en/4.4/classes/class_audiostreamplayer.html, https://docs.godotengine.org/en/stable/classes/class_audioserver.html
- Store settings as linear 0..1 and apply them per bus. Store by bus **name**, not index.

```gdscript
func set_bus_volume(bus: StringName, v: float) -> void:
    var i := AudioServer.get_bus_index(bus)
    assert(i != -1, "unknown bus %s" % bus)
    AudioServer.set_bus_mute(i, v <= 0.0)
    AudioServer.set_bus_volume_linear(i, v)
```

- **Pause:** when the tree pauses, "audio nodes will pause their current audio stream" and resume automatically. Give pause-menu music and UI players `process_mode = PROCESS_MODE_ALWAYS`. Source: https://docs.godotengine.org/en/stable/tutorials/scripting/pausing_games.html (4.7). `AudioServer.playback_speed_scale` does not follow `Engine.time_scale`, so slow-motion needs explicit handling. Source: the AudioServer page.
- **AudioStreamGenerator:** `buffer_length` 0.5 s, `mix_rate` 44100. Fill it with `push_frame` from `get_frames_available()`. The docs recommend C# or GDExtension. From GDScript, use 11025 or 22050 Hz. Source: https://docs.godotengine.org/en/stable/classes/class_audiostreamgenerator.html

## 8. Middleware

- **FMOD:** the community extension utopia-rise/fmod-gdextension. Release 6.1.0-4.5.0 targets "Godot 4.5 / Fmod 2.03.06". FMOD says there is "no official integration" for Godot. Sources: https://github.com/utopia-rise/fmod-gdextension/releases, https://ggj.fmod.com/docs/Development/Godot/working-with-godot.html
  - Licence: free Indie tier for revenue under $200k per year. The budget cap varies by source ($500k or $600k), so the cap is UNVERIFIED (https://fmod.com/licensing was unreadable).
  - UNVERIFIED: whether a 4.7-tagged release exists.
- **Wwise:** alessandrofama/wwise-godot-integration, a GDExtension for Windows, macOS, Linux, Android and iOS, with Web marked experimental. It is promoted on the Audiokinetic blog ("What's New in Wwise 2024.1 for Godot", Jan 2025). The README states Godot 4.3 / Wwise 2024.1. Audiokinetic offers a free indie licence, but the thresholds are UNVERIFIED. Sources: https://github.com/alessandrofama/wwise-godot-integration, https://www.audiokinetic.com/en/blog/whats-new-in-wwise-2024.1-for-godot
- Both are native extensions, which adds a build and per-platform cost. Built-in buses plus the 4.3 music resources cover most indie needs. This is opinion.

## 9. Loudness targets

- PlayStation console: **-24 LUFS integrated ±2 LU**, measured over at least 30 minutes of capture (Feb 2024 guidance). Handheld: -18 LUFS. True peak at most **-1 dBTP**. Loudness range ≤ 20 LU (original ASWG-R001, BS.1770). Mobile and handheld per GANG IESD (2015): -16 LUFS ±2.
- UNVERIFIED: all of these figures come from secondary write-ups (designingsound.org 2012, the Garry Taylor ASWG slides, voxbooster 2026). The primary Sony PDF is not public, and the Audiokinetic mastering blog returned 403.
- Measurement uses ITU-R BS.1770 / EBU R128 via ffmpeg `ebur128=peak=true`, which reports I (LUFS), LRA and true peak. Command: `ffmpeg -nostats -i f.wav -filter_complex ebur128=peak=true -f null -`. Source: https://ffmpeg.org/pipermail/ffmpeg-user/2014-June/021850.html plus the ffmpeg 7.x source (https://ffmpeg.org/doxygen/7.1/f__ebur128_8c_source.html). Note that the ebur128 section of ffmpeg-filters.html could not be fetched.

## 10. Accessibility

- XAG 104 (Microsoft, updated 2026-06):
  - Subtitles for all speech, with the speaker named.
  - Captions for important non-speech sounds, with direction markers such as `<` and `>`.
  - Lines of at most 40 characters and at most 2 lines.
  - Background with adjustable opacity, and size scalable to 200%.
  - Subtitles on by default or settable before any sound plays.
  - Separate toggles for each caption category.
  - Source: https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/104
- Mono option: AudioEffectStereoEnhance `pan_pullout` = 0 "will downmix stereo to mono". Put it on Master and toggle it with `set_bus_effect_enabled`. Source: https://docs.godotengine.org/en/stable/classes/class_audioeffectstereoenhance.html
- Godot has no built-in caption system. A common pattern is a `caption` field next to each SFX resource, emitted on play.

## 11. Headless testing

- `--headless` sets the audio driver to `Dummy`. Source: the AudioServer page (4.7).
- The Dummy driver mixes on a thread when `use_threads` is set (`audio_server_process`). Without threads, a synchronous `mix_audio()` path is used instead. Source: https://raw.githubusercontent.com/godotengine/godot/master/servers/audio/audio_driver_dummy.cpp
  - UNVERIFIED: whether `use_threads` is on by default in headless runs, and therefore whether AudioEffectCapture receives frames there.
- AudioServer queries for assertions: `get_bus_count/get_bus_name/get_bus_index`, `get_bus_peak_volume_left_db/right_db`, `get_bus_effect`, `get_driver_name`, `get_mix_rate`.
- AudioEffectCapture (`buffer_length` 0.1 s) exposes `get_frames_available`, `get_buffer(n)` (samples in -1..1) and `get_discarded_frames`. Compute RMS and peak from those samples in GDScript and print one summary line. Source: https://docs.godotengine.org/en/stable/classes/class_audioeffectcapture.html
- Deterministic alternative: Movie Maker, `--write-movie out.png --fixed-fps 30`. It writes PNG frames plus a WAV, and works in exported projects too. Its mix rate must be divisible by the FPS. The WAV can then go through ffmpeg ebur128. Source: https://docs.godotengine.org/en/stable/tutorials/animation/creating_movies.html
  - UNVERIFIED: whether it works together with `--headless`, since rendering is needed.

## Version-specific features

| Feature                                                     | Version               | Source                                               |
| ----------------------------------------------------------- | --------------------- | ---------------------------------------------------- |
| max_polyphony, AudioStreamPolyphonic, AudioStreamRandomizer | 4.0                   | 4.0 class docs                                       |
| AudioStreamInteractive / Playlist / Synchronized            | 4.3                   | releases/4.3                                         |
| Web Sample playback, `playback_type` (experimental)         | 4.3                   | releases/4.3; 4.3 vs 4.2 class docs                  |
| AudioEffectHardLimiter (Limiter deprecated)                 | 4.3                   | 4.3 docs exist, 4.2 returns 404                      |
| QOA WAV compression                                         | 4.3                   | 4.3 import tutorial                                  |
| QOA as default `compress/mode`                              | 4.4                   | 4.4 ResourceImporterWAV                              |
| `volume_linear` on players                                  | 4.4                   | 4.4 vs 4.3 class docs                                |
| Runtime WAV loading                                         | 4.4                   | releases/4.4                                         |
| Editor "mute game" toggle in Game view                      | 4.5                   | releases/4.5                                         |
| `random_pitch_semitones`                                    | 4.6                   | 4.6 vs 4.5 docs                                      |
| 4.7 audio changes                                           | none in release notes | releases/4.7 (UNVERIFIED against the full changelog) |

## Checkable rules an agent should follow

1. `default_bus_layout.tres` exists and `project.godot` doesn't point `audio/buses/default_bus_layout` somewhere else without that file existing.
1. Master (`bus/0`) has an `AudioEffectHardLimiter` as its **last** enabled effect.
1. No `AudioEffectLimiter` appears anywhere, because it is deprecated and does nothing.
1. Bus names are unique and non-empty, and each is in a project allow-list such as Music, SFX, Voice, UI, Ambience.
1. Every `bus/<i>/send` names an existing bus with a lower index.
1. Every `bus = &"X"` in `.tscn`/`.tres` and every bus string literal in `.gd` names a bus in the layout.
1. No gameplay player is left on Master. A player in a scene without a `bus =` line defaults to Master.
1. A compressor with `sidechain` names an existing bus, and its `threshold` is below 0.
1. No bus `volume_db` is above 0, and Master's `volume_db` is 0 or lower.
1. Music Ogg/MP3 files have `loop=true` (or the transition logic is documented), and interactive-music clips have `bpm > 0` and `beat_count > 0`.
1. Short SFX (under ~5 s) are WAV, and music or voice longer than ~30 s is Ogg (or MP3 on mobile/web). These thresholds are project policy and still UNTESTED.
1. Each WAV's `compress/mode` is explicitly chosen for its category: PCM for very short UI clicks if the team decides so, QOA otherwise.
1. `force/8_bit=false` everywhere.
1. Settings code converts sliders with `linear_to_db` or `volume_linear`, and mutes at 0.
1. Settings persist bus volumes keyed by bus name, not index.
1. Pause-menu and UI audio players use `process_mode = PROCESS_MODE_ALWAYS`, or sit under such a node.
1. A sound that must outlive its emitter is not played from a node freed in the same frame. It goes to a pool or autoload.
1. Code that drives AudioStreamPolyphonic checks the result of `play_stream` against `INVALID_ID`.
1. A web export that uses bus effects, reverb or Doppler sets `audio/general/default_playback_type.web` to Stream, or documents the loss.
1. `get_output_latency()` is not called from `_process` every frame.
1. Every asset is within the project's loudness band (for example SFX peaks ≤ -1 dBTP) as measured by ebur128.
1. Gameplay-relevant sounds have caption text, and subtitle settings exist (XAG 104).
1. A mono toggle exists, implemented as StereoEnhance `pan_pullout=0` on Master.
1. AudioStreamGenerator is filled from compiled code, or runs at ≤ 22050 Hz in GDScript.

## What a tool could check automatically

- **Bus layout lint:** parse `bus/<i>/*` keys and `[sub_resource type=...]`. Report rules 2–5, 8 and 9: missing limiter, deprecated Limiter, invalid or rightward sends, duplicate names, positive gains.
- **Orphan bus references:** grep `.tscn`, `.tres` and `.gd` for `bus = &"..."`, `play_stream(..., &"...")` and `get_bus_index("...")`, then diff the names against the layout. An unknown name falls back to Master silently.
- **Players without a bus:** find `[node type="AudioStreamPlayer*"]` blocks that have no `bus =` line.
- **Import audit:** read the `.import` `[params]` (importer `wav` / `oggvorbisstr` / `mp3`). Flag music without loop, interactive clips without bpm/beat_count, 8-bit WAV, long uncompressed WAV, `force/max_rate_hz` below 22050 on music, and a mismatch between each asset's sample rate and `audio/driver/mix_rate`.
- **Loudness:** run `ffmpeg -nostats -i f -filter_complex ebur128=peak=true -f null -` on each source asset and parse I, LRA and true peak. Flag true peak above -1 dBTP, clipped samples, and spread across a category (for example all footsteps within ±3 LU). ffmpeg is optional and should be reported by `doctor`.
- **Web readiness:** default_playback_type.web is Sample while the layout has effects, so warn.
- **Headless smoke test:** run `godot --headless` with a script that prints the driver, bus count and names, and the effects on Master. Optionally attach an AudioEffectCapture and print a `AUDIO_SUMMARY peak_db=... rms_db=...` line. Judge the run by that line, not the exit code.
- **Pause audit:** check that players under pause-menu scenes have `process_mode = 3` (ALWAYS), either inherited or on the node itself.

## Pitfalls

- Renaming or misspelling a bus sends audio silently to Master, which bypasses its mix and ducking.
- A send pointing rightward or to a missing bus also falls back to Master.
- `max_polyphony = 1` by default, so rapid `play()` calls cut the previous sound. Raising it too far without a cap stacks voices into clipping.
- Freeing the emitter stops its sounds, and `finished` doesn't fire. This affects coin pickups and enemy death sounds.
- `finished` never fires for looping streams.
- `linear_to_db(0)` gives -inf, so mute explicitly.
- Using `volume_linear` breaks builds before 4.4.
- On the web (4.3+ default Sample mode), bus effects, the limiter, ducking, reverb and Doppler do nothing.
- Auto-disabled silent buses (-60 dB for 2 s) can confuse capture-based tests and meters.
- WAV compression defaults to lossy QOA since 4.4. Audible artifacts on critical UI sounds come from the importer default, not the asset.
- The import tutorial's claim that BPM is "unused" is stale: interactive music needs that metadata.
- AudioStreamRandomizer defaults changed between 4.0 and 4.7, so pitch/volume variation may silently disappear after an upgrade. When the defaults changed is UNVERIFIED.

## Risks and gaps

- 4.7 notes list no audio changes, but the full 4.7 changelog was not scanned.
- Middleware licence numbers and loudness targets rest on secondary sources.
- Dummy-driver capture behaviour and `switch_to_clip_by_name` details are UNVERIFIED.
- The audio_streams tutorial says it is not updated for 4.7.

## Sources

Primary: docs.godotengine.org pages for 4.0, 4.2, 4.3, 4.4, 4.5, 4.6 and stable 4.7, as cited inline; godotengine.org/releases/4.3–4.7; raw source of audio_server.cpp, audio_bus_layout.cpp, audio_driver_dummy.cpp, resource_importer_wav.cpp and resource_importer_ogg_vorbis.cpp (master, read 2026-11-13); Microsoft XAG 104; utopia-rise/fmod-gdextension releases; alessandrofama/wwise-godot-integration; the Audiokinetic blog (Jan 2025); the FMOD Godot guide.
Secondary, used only for flagged claims: designingsound.org (2012) and the ASWG slides for loudness; voxbooster (2026); the ffmpeg-user list (2014); third-party mirrors for the QOA and volume_linear commits; itechguides for the FMOD tier.
