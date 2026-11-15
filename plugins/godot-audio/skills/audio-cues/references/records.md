# Audio records

The two JSON files audiokit reads, the rules each command applies, and the Godot facts behind them. The agent writes the JSON; `audiokit lint` checks it.

## Cue sheet: `audio/cues.json`

```json
{
  "mix_rate": 48000,
  "buses": ["Master", "Music", "SFX", "UI"],
  "cues": {
    "ui_click": {
      "kind": "ui",
      "bus": "UI",
      "gain_db": -5,
      "files": ["audio/ui/ui_click.wav"],
      "source": {"type": "procedural", "generator": "audiokit:click", "seed": 7,
                 "params": {"seconds": 0.03, "hz": 400, "peak_dbfs": -6}},
      "brief": "a soft, short tick for menu focus",
      "caption": "[click]"
    },
    "music_arena": {
      "kind": "music",
      "bus": "Music",
      "files": ["audio/music/music_arena.ogg"],
      "loop": {"mode": "forward", "begin_s": 0.0},
      "source": {"type": "fal", "endpoint": "fal-ai/stable-audio-25/text-to-audio"}
    }
  }
}
```

| Field                        | Rule                                                                                                    |
| ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| `mix_rate`                   | Hz; files at another rate are reported, since Godot resamples them at runtime.                          |
| `buses`                      | Must include Master; names unique. `audiokit buses` checks each against the layout.                     |
| cue id                       | snake_case; the files are `<id>.<ext>` or `<id>_<n>.<ext>` (variations).                                |
| `kind`                       | sfx, ui, music, ambience or stinger.                                                                    |
| `bus`                        | One of `buses`.                                                                                         |
| `gain_db`                    | A number, applied by the game's player code.                                                            |
| `files`                      | Paths under `audio/`, never under `audio/local/`, ending in .wav, .ogg or .mp3.                         |
| `loop`                       | `mode` none, forward, pingpong or backward; `begin_s`, optional `end_s`. Ogg and MP3 loop forward only. |
| `source.type`                | procedural (needs `generator` and an integer `seed`), fal (needs `endpoint`), licensed or human.        |
| `source.params`              | For an `audiokit:` generator: `seconds`, `hz`, `peak_dbfs` (at most 0).                                 |
| `asset`                      | Written by `audiokit register`: the registry asset of the cue.                                          |
| `brief`, `caption`, `prompt` | Free text kept with the cue; lint does not read them.                                                   |

Synth recipes: `blip` is a sine falling an octave as it decays (UI confirm); `click` is differenced noise whose decay rate is `hz`; `noise` is low-passed noise at `hz` that decays over its length (a puff or hit); `tone` is a sine moved to whole periods so it loops without a seam.

## Policy: `audio/policy.json`

```json
{
  "rules": [
    {"glob": "audio/ui/*", "codecs": ["pcm"], "channels": 1, "max_duration_s": 1.0,
     "max_peak_dbfs": -3, "compress_modes": [2]},
    {"glob": "audio/music/*", "codecs": ["vorbis"], "min_duration_s": 30, "lufs_i": [-20, -14]}
  ]
}
```

Rules match by `fnmatch` glob, first match wins; a file no rule matches is checked only against `mix_rate`. Fields: `codecs` (pcm, float, vorbis, mp3), `channels`, `min_duration_s`, `max_duration_s`, `max_peak_dbfs`, `max_edge_silence_s`, `compress_modes` (WAV `.import` `compress/mode`), `lufs_i` ([low, high]), `max_true_peak_dbtp`. The figures above are examples, not targets.

## Commands and what they report

| Command    | Reports                                                                                                                                                                                                                                                                                                                                         |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `audit`    | unreadable files; rate against `mix_rate`; codec, channels, duration against the policy                                                                                                                                                                                                                                                         |
| `levels`   | clipped samples, silent files, peak over the ceiling, edge silence over the limit                                                                                                                                                                                                                                                               |
| `loops`    | seam ratio over 1.5, edge RMS delta over 1.0 dB, `.import` loop keys that differ from the cue, compress mode outside the policy                                                                                                                                                                                                                 |
| `loudness` | integrated LUFS outside the band, true peak over the ceiling; `--ffmpeg` adds ffmpeg's figures                                                                                                                                                                                                                                                  |
| `buses`    | missing layout, duplicate names, Master not ending with a HardLimiter, deprecated Limiter, an effect shared between buses, volume over 0 dB, a send not to a bus on its left, a sidechain on a missing bus, a compressor threshold at or over 0, cue buses missing from the layout, unknown buses in scenes and scripts, players left on Master |

Exit codes: 0 ok, 1 problems found, 2 setup (a tool missing), 3 refused (records broken or a request unsafe).

## Godot 4.7.2 facts (measured 2026-11-15)

- WAV `.import`: `force/8_bit`, `force/mono`, `force/max_rate`, `force/max_rate_hz=44100`, `edit/trim`, `edit/normalize`, `edit/loop_mode=0`, `edit/loop_begin=0`, `edit/loop_end=-1`, `compress/mode=2` (QOA is the default). Loop points are in frames.
- Ogg `.import`: `loop=false`, `loop_offset=0`, `bpm=0`, `beat_count=0`, `bar_beats=4`.
- Loop values written into `.import` survive a reimport, also after the source is touched.
- The bus layout `.tres` stores only non-default values; Master has no name line. A send reads `bus/2/send = &"Music"`; an effect `bus/0/effect/0/effect = SubResource("AudioEffectHardLimiter_x")`.
- A scene player stores its bus as `bus = &"SFX"`; without that line it plays on Master.
- `AudioStreamRandomizer` defaults: pitch 1.0, volume offset 0.0, semitones 0.0.
- Readers matched ffprobe on Ogg, float WAV and 24-bit WAV; MP3 reads longer than its content because of encoder padding (0.784 s for 0.75 s).
