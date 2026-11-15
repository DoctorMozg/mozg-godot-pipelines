# Batch details

Prompt template, fal endpoint inputs and the register flow. `falkit estimate` and `falkit schema <endpoint>` are the authority on prices and inputs; the figures here carry their date and go stale.

## Prompt template

```text
<what is heard>, <how it starts and how it ends>, <length> seconds, <mood or material>.
<recording character>. No music, no voice.
```

Write the sound, not the scene: "a short wooden knock, dry, sharp attack, fast decay" rather than "the player opens a door". Keep the cue's brief beside the prompt so a retake can be compared with what was asked.

## Endpoints

| Use                   | Endpoint                               | Inputs                                                                                                                                                                              | Price (source, date)                                                                               |
| --------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Effects, UI, stingers | `elevenlabs/sound-effects/v3`          | `text` (at most 450 characters), `duration_seconds` 0.5 to 30, `prompt_influence` (default 0.3), `loop`, `output_format` (default `mp3_44100_128`; `pcm_48000` gives WAV-ready PCM) | $0.002 per output second (fal model page, 2026-11-12)                                              |
| Beds, ambience        | `fal-ai/stable-audio-25/text-to-audio` | `prompt`, `seconds_total` 1 to 190 (default 190), `seed`, `num_inference_steps` 4 to 8, `guidance_scale`                                                                            | $0.20 per request whatever the length (fal model page, 2026-11-05; UNTESTED against a billed call) |

Set `seconds_total` on Stable Audio: the default writes 190 s for the same price.

What came back on 2026-11-15 (one call each, measured by `audiokit register`): ElevenLabs sound effects at `mp3_44100_192` gave 44.1 kHz stereo MP3 of the asked length plus about 0.03 s, peaks -6.3 to -0.6 dBFS; Stable Audio 2.5 gave a 20 s 44.1 kHz stereo WAV peaking at 0 dBFS (4 clipped samples, +0.02 dBTP, -8.8 LUFS). Both rates differ from a 48 kHz mix, so `audiokit audit` reports them after promotion; converting is the owner's call.

## Flow per fal cue

```text
falkit plan check <plan>
falkit estimate --plan <plan>
fal-assets: one call under the spend guard
falkit fetch <call> --kind sound --out <folder outside res://>
falkit ledger export --plan <plan> --call <tool use id> --out <new file>
audiokit register <cue> --ledger <file> --request-id <request id> --prompt '<prompt>'
```

Register refuses, before anything is staged: an unknown request, a call that has no result (states other than completed, fetched or verified), a fetched file whose sha256 differs from the ledger, a cue that fails lint, a fal cue registered without a ledger, an asset that holds another kind, and a repeat of the same request. A refused `version add` removes the staged copy.

## What a version records

- Provenance: origin `generated` with digital source type `trainedAlgorithmicMedia` for fal; `procedural` for synth; the license.
- Generation: provider `fal` and the endpoint as model, the request id as job id, the prompt, and `usd_charged` from the ledger; for synth, provider `audiokit`, the generator as model, the seed and the recipe params.
- Media: `duration_s`, `rate`, `channels`, `peak_dbfs`, `rms_dbfs`, `clipped`, `dc_offset`, `lead_silence_s`, `trail_silence_s`, `lufs_i`, `true_peak_dbtp`. A figure that cannot be measured (an MP3 without ffmpeg) is left out, never guessed.

## Hub

The review hub plays the first audio file of a version, draws its waveform, shows duration and peak, plays the seam (the last second looped), and compares A/B with the parent version. The owner's decision is recorded there; `status` in the cue sheet is never copied from it.
