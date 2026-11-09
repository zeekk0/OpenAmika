# TTS: the contract, the voice server, and the voice adapter

**Her voice is one command away.** `envs\brain\Scripts\python.exe scripts\setup_tts.py` (after the core setup,
`powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1`; any Python 3.11 runs it) installs Amika's voice
and her Live2D model from Hugging Face
(personal-use license, 18+; the script shows it and asks you to accept it first) and the OpenAmika voice server
(`vendor/tts-engine`, a MekaHime build of GPT-SoVITS, MIT), and `settings.example.json` already has the launcher
start that server on port 8002. Without a voice server she still works in text: her replies appear as live
subtitles and the Live2D avatar still acts them out, but her voice is an essential part, so the launcher's
`TTS (voice)` row and the health light show it red with the command that installs it.

## The contract the speech layer speaks

OpenAmika's speech layer is a **Socket.IO client** to the TTS server (`settings.json → tts_url`).
With the default settings (voice adapter ON → old-vocabulary voice ids), the wire looks like:

```jsonc
// emit("tts_request_gateway", …)
{
  "task_id":      "uuid",
  "turn_id":      "<brain turn>-<idx>",
  "text":         "【happy2】.今日もおつかれさま。",   // emotion tag first, then the sentence
  "character_id": "MekaHime_Amika",                      // settings.json → tts_character (adapter may swap it)
  "audio_format": "wav",                                  // browsers decode containers, not raw opus
  "language":     "Japanese"                              // optional: Chinese | English | Japanese | Korean
}

// on("audio_ready")   — one per request (filter by task_id)
{ "task_id", "turn_id", "audio": <bytes>, "audio_format", "audio_duration", "text", "is_final": true }
// plus "task_queued" (accepted) and "error" { task_id, turn_id, error, code }
```

- One request per sentence; `turn_id` lets a server keep one turn's sentences in order.
- `GET /ping` answering `ok` is what the launcher and the Setup page poll for health.
- `audio` is the encoded file (WAV by default); `audio_duration` is in seconds.
- Voice failures add `code: "korean_voice_unavailable"` for Korean prerequisite
  failures or `"tts_unavailable"` for general failures. The gateway carries these
  allowlisted codes in `tts_error`; the existing `error` text field remains for
  older clients. Unknown/missing vendor codes become `tts_unavailable`.

## The OpenAmika voice server

### Korean readiness is not acoustic acceptance

`GET /api/tts_probe` on the speech gateway keeps the existing `ok`/`status` ping
reachability fields and adds a `korean` object. The bundled voice server exposes
the same object directly at `GET /api/korean_readiness`:

```json
{"state":"frontend_ready","code":"korean_frontend_ready","acoustic_acceptance":"unverified"}
```

| State | Code | Meaning |
|---|---|---|
| `unavailable` | `tts_unavailable` | Engine is absent, loading, failed or unreachable. |
| `unknown` | `korean_probe_unsupported` | Vendor has no compatible endpoint, redirects, times out or returns invalid data. Ping alone proves nothing about Korean. |
| `unavailable` | `korean_probe_failed` | The isolated Korean frontend check failed or its helper is missing. |
| `unavailable` | `korean_probe_timeout` | The frontend child exceeded its two-second budget. This is not proof that Korean can never work. |
| `frontend_ready` | `korean_frontend_ready` | The ready engine's interpreter produced Korean phonemes in the guarded child. No audio was synthesized. |

The vendor probe uses the existing read-only `scripts/korean_voice_probe.py` in an
isolated `-I -B` child, not a model load, installer, downloader or microphone. It
rejects network/process creation and file writes inside the child. Local hostname
reads are allowed. NumPy's optional, no-argument `lscpu` discovery is stopped before
process creation and receives `FileNotFoundError`; no CPU command is executed.
Other process/network/write attempts remain sticky failures even if a dependency
catches the exception. Third-party imports still run with the guard active. Concurrent
requests share one child. Results are cached in memory for at most 30 seconds per
resolved checkout, never persisted. Changing engine state or checkout invalidates
in-flight success. Cancelling one HTTP caller does not cancel another caller's
shared probe, and the child remains bounded. Output is capped at 8 KiB and only
allowlisted state/code fields cross the gateway. Redirects are not followed and
the request cannot supply another URL. A failed check does not change the voice,
language routing, text protocol, model files or consent.

Windows uses `python-mecab-ko==1.3.7` (including its dictionary), the same Korean
tokenizer as the other platforms, rather than building `eunjeon`. The probe and
Korean synthesis share this adapter; neither invokes the upstream tokenizer
installer or its `eunjeon` dictionary-copy workaround. Re-run the normal
`scripts/setup_tts.py` installer to update an existing voice environment, then
restart the voice server and run `scripts/setup_tts.py --verify`. Verification
alone does not install the newly required Windows package. This fixes frontend
prerequisites; Windows synthesis and pronunciation still need hardware acceptance.

The HTTP readiness child has a **two-second** budget to keep Setup responsive.
The explicit `scripts/setup_tts.py --verify` Korean check has a **30-second**
budget and also never installs or downloads anything. A cold frontend import or
initial G2P construction can exceed two seconds even when dependencies are
installed. Therefore `korean_probe_timeout` means only that this bounded check
did not finish, not that packages or dictionaries are missing. Use the longer
read-only verification for diagnosis rather than automatically installing assets.
Neither timeout budget establishes synthesis or pronunciation acceptance.

한국어 안내: `frontend_ready`는 한국어 전처리 점검 통과이며 실제 음성 품질 합격이
아닙니다. `acoustic_acceptance`는 항상 `unverified`입니다. 사전이나 패키지가 없으면
텍스트 대화를 계속 사용할 수 있습니다. 설치와 라이선스 동의는 사용자가 별도로
결정해야 합니다. `scripts/setup_tts.py --verify`는 설치 없이 더 긴 30초 한도로
진단합니다. HTTP 점검의 2초 제한은 첫 전처리 초기화만으로도 초과할 수 있으므로,
시간 초과를 패키지나 사전 누락으로 단정하거나 자동 설치하지 않습니다.
허가받은 자산, 실제 Mac/Windows 오디오 기기, 원어민 독립 청취 평가
전까지 발음·음질·마이크 인식·지연·끼어들기 인수는 **미검증**입니다.

OpenAmika ships its own: the **OpenAmika voice server** (`vendor/tts-engine/main.py`, a MekaHime build of
GPT-SoVITS v2ProPlus, MIT), derived from the OpenSakura voice server. One command installs it with Amika's voice:

```text
envs\brain\Scripts\python.exe scripts\setup_tts.py     type yes to accept her license; --cpu without an NVIDIA GPU
```

- First Amika's voice, her Live2D model and the paper doll that stands in for her helpers, from the Hugging Face
  repository [MekaHime/MekaHime_Amika](https://huggingface.co/MekaHime/MekaHime_Amika) (one license for all three),
  file by file with the standard library and checked against `scripts/MekaHime_Amika.manifest.json` (size and
  SHA-256 of all 250 files at the pinned revision, and of the paper doll's 70 at its own): the voice into
  `vendor/tts-engine/Speakers/MekaHime_Amika/`, the model into `avatar/models/Amika/` (`--skip-avatar` leaves it
  out), the paper doll into `avatar/models/Host/` (`--skip-paper-doll`). Then it builds the rest of `vendor/tts-engine/` from public
  sources: a Python 3.11 venv with CUDA 12.8 torch, upstream GPT-SoVITS at a pinned commit with its pretrained
  models. Every download is pinned by size and SHA-256; a re-run verifies and skips what is already there, and
  `--verify` checks everything without downloading.
- `settings.example.json` lists it under `services.tts`, so the launcher starts it on port 8002 with the rest and
  waits for `GET /ping` (models plus four warm-up lines, about 20 s on a GPU). `tts_url` points at it and
  `tts_character` (`MekaHime_Amika`) names the voice.
- It needs about 2.5 GB of VRAM; `--cpu` installs a CPU build for machines without an NVIDIA GPU (slower).
- Flags, the request contract in full, how it uses upstream and measurements: `vendor/tts-engine/README.md`.

**One voice ships:** `MekaHime_Amika`, an old-vocabulary voice (the 67 V1 ids plus `happy4` and `sad4`, 69 clips).
Any other voice is yours to bring: a speaker folder in `vendor/tts-engine/Speakers/` (`character.json`, the
`.ckpt` / `.pth` weights, `references/emotions.json`), or any other server that speaks the contract above: point
`tts_url` at it and describe it under `services.tts` (command, cwd, health URL) so the launcher starts it with
the rest.

## Korean voice status

Korean conversation routing is implemented, but Korean voice remains **experimental** until synthesis,
mixed Korean/English names, microphone interruptions, and pronunciation are checked on the supported Windows
installation with the existing licensed voice. Offline routing tests do not establish intelligibility or audio/avatar
synchronization. `GET /ping` keeps its existing meaning and is not a per-language readiness certificate.

Both dialogue and `POST /api/tts_say` send `language: "Korean"` for Korean-only text. The vendor maps it to `ko`.
For ambiguous mixed or Hanja-only dialogue sentences, the brain's resolved reply language breaks the tie.
Name-preview sentences follow the selected UI locale; Korean previews use the same Korean routing.

```powershell
envs\brain\Scripts\python.exe scripts\setup_tts.py --verify
```

The separate `Korean voice` row checks platform-specific Mecab packages/dictionaries, NLTK CMU data, and
the pinned Korean frontend's G2P path in a disposable voice-interpreter process with a 30-second limit.
Verification does not install packages, download data, or modify the frontend. Missing prerequisites produce
an optional diagnostic with the voice interpreter path, not a failure of text or existing-language readiness.
Provision the reported packages/data explicitly in that environment, then verify again. In particular, the pinned
`g2pk2` may otherwise try to install Mecab during construction; importing it is not a safe generic readiness check.
An `OK` Korean G2P result is only a phoneme smoke check, not an audio-quality result.

The voice server performs the same bounded check before a Korean request can reach upstream initialization,
including Korean reference prompts and Hangul in automatic/mixed modes. Successful checks are cached per
checkout for that server process so every sentence does not launch another probe. Failures are not cached.
Restart the voice server after changing pronunciation packages or data. Custom engine installations receive the
probe helper from the installer; verification never copies or repairs it.

If Korean synthesis is unavailable, text remains visible and the audio request reports an error instead of
silently requesting a Chinese frontend. No voice retraining or new asset-license acceptance is part of this change.

## Emotion vocabularies: internal vs. old-style voices

- **Internal (V2)**: 69 `register_emotion` keys (`casual_happy`, `whisper_caring`, …). This is the
  contract the brain's templates, both streaming parsers and the Live2D banks are built on; it never
  changes regardless of which voice speaks.
- **Old-style voice ids (V1)**: 67 flat ids with intensity numbers (`happy2`, `tsun3`, `whisper1`, …),
  the vocabulary of MekaHime's GPT-SoVITS voices, Amika's included.

## The voice adapter (default: ON)

`speech/voice_adapter.py` bridges the internal vocabulary to V1-style voice ids and is **enabled by
default** (defaults in code; `config/voice_map.json` is written when you change it on the Setup page):

- the brain **always** emits the 69-key tag; the adapter rewrites **only the leading tag** of the
  outgoing TTS text into an old id via a validated 69→67 map, and swaps `character_id` to the configured
  voice;
- the `emotion` reported to the browser/avatar **stays the new key**, so face and voice never disagree;
- idempotent (an already-old tag passes through; untagged text gets `【neutral1】`);
- the map is hot-reloaded (mtime-gated, last-good on parse errors) and validated cell-by-cell on read; a
  stale or hand-edited file degrades safely to the defaults;
- Setup → Voice gives you the per-cell grid (changed cells highlight), enable/disable, and reset.

**Your own voice or server:** if it understands the 69 internal keys directly (or ignores tags), switch the
adapter off on Setup → Voice and set `tts_character` in `settings.json` to your voice id (that value is used
whenever the adapter is off). If it uses flat ids like `happy2`, keep the adapter on, set its voice on Setup →
Voice (the adapter sends its own voice id, default `MekaHime_Amika`) and tune the grid by ear; remapping is a
voice-acting decision per voice.
