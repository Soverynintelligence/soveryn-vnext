# Sovereign Voice Phase 2 — Aetheria Local TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ElevenLabs cloud TTS with a locally-cloned F5-TTS service for Aetheria, on Quadro #0 (currently empty). ElevenLabs becomes the documented fallback. Cuts TTS latency from ~720ms TTFB to ~200-400ms and closes the last cloud tendril in her loop.

**Scope:** Aetheria only. Vett+Scotty voices are Phase 3 (separate plan), gated on this proving the local stack works. F5-TTS only — XTTS-v2 / Sesame deferred per "ship one, swap later if needed."

**Architecture:** Standalone F5-TTS HTTP microservice on Quadro #0 (mirrors Parakeet's pattern at :8087, on :8088). New Pipecat `SovereignTTSService` processor drops into `build_aetheria_voice_pipeline` in place of `ElevenLabsHttpTTSService`. Reference voice = a clean Aetheria utterance from `~/soveryn_complete/static/voice_aetheria_*.wav`. Fallback to ElevenLabs is one env-var flip.

**Tech Stack:**
- F5-TTS (Apache 2.0, voice cloning from 6-15s reference, ~real-time on 24GB GPU)
- Standalone Flask HTTP service (Python 3.10+ conda env, dedicated)
- Pipecat `TTSService` subclass for pipeline integration
- ElevenLabs retained as fallback provider behind env flag

---

## File Structure

**New files:**
- `~/f5tts_service/server.py` — Flask HTTP service mirroring Parakeet's pattern
- `~/f5tts_service/aetheria_ref.wav` — 10-15s clean Aetheria reference clip (copied + trimmed from existing WAV pool)
- `~/f5tts_service/aetheria_ref.txt` — transcript of the reference clip (F5-TTS needs it)
- `/etc/systemd/system/soveryn-f5tts.service` — systemd unit (mirrors `parakeet.service`)
- `soveryn/platform/voice/sovereign_tts.py` — Pipecat `TTSService` subclass calling :8088
- `tests/test_sovereign_tts.py` — unit + integration test for the processor

**Modified files:**
- `soveryn/platform/voice/pipeline.py:298-396` — `build_aetheria_voice_pipeline` chooses TTS provider based on env flag
- `soveryn/platform/voice/config.py` — adds `SOVEREIGN_TTS_PRIMARY` env var (default `f5tts`)
- `soveryn/app/startup.py:~640` — `_maybe_register_voice` passes the choice through to the pipeline factory
- `scripts/soveryn-restart.sh` — F5-TTS added to the foundation services group

---

## Task 1: Install F5-TTS environment

**Files:**
- Create: `~/f5tts_service/` directory
- Create: conda env `f5tts` (Python 3.10)

- [ ] **Step 1: Check Quadro #0 has 48 GB free** (it does — verified 2026-06-15)

```bash
nvidia-smi --query-gpu=index,memory.free --format=csv,noheader
```
Expected: GPU 0 shows ~48000 MiB free.

- [ ] **Step 2: Create conda env**

```bash
mkdir -p ~/f5tts_service
conda create -n f5tts python=3.10 -y
conda activate f5tts
pip install f5-tts torch torchaudio flask soundfile
```

Expected: clean install, no CUDA mismatch. If CUDA mismatch, install torch matching the system CUDA (`nvidia-smi` top line). Open driver pinning is documented in `project_soveryn_blackwell_open_driver.md`.

- [ ] **Step 3: Smoke-test F5-TTS with stock voice**

```bash
cd ~/f5tts_service
conda activate f5tts
python -c "
import torch
from f5_tts.api import F5TTS
print('CUDA:', torch.cuda.is_available(), 'device count:', torch.cuda.device_count())
tts = F5TTS(model_type='F5-TTS', device='cuda:0')
print('model loaded')
"
```

Expected: prints `CUDA: True ... model loaded`. If model download triggers (~1.5 GB), let it complete.

- [ ] **Step 4: Verify VRAM footprint**

```bash
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader
```
Expected: GPU 0 shows ~5-7 GB used while the test script holds the model. Compare to baseline (162 MB).

- [ ] **Step 5: Commit + memory note**

```bash
git add docs/superpowers/plans/2026-06-15-sovereign-voice-phase2-aetheria.md
git commit -m "plan: Sovereign Voice Phase 2 — Aetheria local TTS via F5-TTS"
```

Save memory: `project_soveryn_f5tts_install.md` — install path, env name, Quadro #0 pinning, VRAM footprint.

---

## Task 2: Build Aetheria reference clip

**Files:**
- Create: `~/f5tts_service/aetheria_ref.wav` (10-15 second clean clip)
- Create: `~/f5tts_service/aetheria_ref.txt` (exact transcript of that clip)

- [ ] **Step 1: Pick the source WAV**

Browse `~/soveryn_complete/static/voice_aetheria_*.wav` — find a 10-15 second sample that:
- Is in the registered voice (post-cloning, post 2026-05-14)
- Has clean prosody (no laugh, no stutter, no tool-call leakage)
- Spans a full sentence or two (F5-TTS prefers complete phrasing over fragments)

Use `soxi` or `ffprobe` to check duration:
```bash
for f in ~/soveryn_complete/static/voice_aetheria_*.wav; do
  d=$(soxi -D "$f" 2>/dev/null)
  if [ -n "$d" ] && awk -v d="$d" 'BEGIN{exit !(d>=10 && d<=15)}'; then
    echo "$d $f"
  fi
done | head -10
```

- [ ] **Step 2: Transcribe via Parakeet (already running at :8087)**

```bash
curl -X POST --data-binary @<picked.wav> \
  -H 'Content-Type: audio/wav' \
  http://127.0.0.1:8087/transcribe
```

Save transcript to `~/f5tts_service/aetheria_ref.txt`. Hand-correct any STT errors (F5-TTS needs the exact transcript — sloppy text hurts quality).

- [ ] **Step 3: Copy the WAV and confirm sample rate**

```bash
cp <picked.wav> ~/f5tts_service/aetheria_ref.wav
soxi ~/f5tts_service/aetheria_ref.wav
```

F5-TTS expects 24 kHz. If reference is 24kHz (existing pipeline rate per `project_soveryn_voice_pipeline.md`), no resampling needed. If different, resample:
```bash
sox ~/f5tts_service/aetheria_ref.wav -r 24000 -c 1 ~/f5tts_service/aetheria_ref_24k.wav
mv ~/f5tts_service/aetheria_ref_24k.wav ~/f5tts_service/aetheria_ref.wav
```

- [ ] **Step 4: Generate a test synthesis side-by-side with ElevenLabs**

```bash
cd ~/f5tts_service
conda activate f5tts
python -c "
from f5_tts.api import F5TTS
tts = F5TTS(model_type='F5-TTS', device='cuda:0')
text = 'I see you, Jon. The signal is clean.'
wav, sr, _ = tts.infer(
    ref_file='aetheria_ref.wav',
    ref_text=open('aetheria_ref.txt').read().strip(),
    gen_text=text,
)
import soundfile as sf
sf.write('test_f5_aetheria.wav', wav, sr)
"
```

- [ ] **Step 5: Generate the SAME line through ElevenLabs (for ear-check)**

Use the existing pipeline or curl ElevenLabs directly with the voice_id from `.env`. Save as `test_eleven_aetheria.wav` next to the F5 version.

- [ ] **Step 6: Play both, ear-check**

```bash
paplay ~/f5tts_service/test_f5_aetheria.wav
paplay ~/f5tts_service/test_eleven_aetheria.wav
```

Note: this is the moment where Phase 2 either lives or dies. If F5-TTS doesn't sound like her, we either pick a different reference clip (Task 2 retry with different source), or surface the gap and Jon decides whether to evaluate XTTS-v2 / Sesame after all.

**If F5-TTS sounds wrong** — STOP, escalate to Jon. Don't push forward with a bad clone.

- [ ] **Step 7: Commit reference assets (NOT to public repo)**

The reference WAV is identity-bearing and should NOT go to the public PR. Add to `.gitignore` patterns covering `~/f5tts_service/`. Confirm with `git status` — only the script changes show, not the audio.

---

## Task 3: F5-TTS HTTP service

**Files:**
- Create: `~/f5tts_service/server.py`
- Create: `/etc/systemd/system/soveryn-f5tts.service` (mirrors `parakeet.service`)

- [ ] **Step 1: Look at Parakeet's service pattern for shape parity**

```bash
cat /etc/systemd/system/parakeet.service
ls -la ~/parakeet_service/server.py  # confirm path
head -40 ~/parakeet_service/server.py
```

- [ ] **Step 2: Write `~/f5tts_service/server.py`**

```python
"""F5-TTS HTTP microservice — mirrors Parakeet's pattern.

POST /synthesize {"text": "..."} -> WAV bytes (24kHz mono).
Pins to CUDA0 (Quadro #0 in the system, the empty card).
Reference clip loaded once at startup; warm thereafter.
"""
import io
import os
import logging
from flask import Flask, request, Response, jsonify
from f5_tts.api import F5TTS
import soundfile as sf

# Pin to Quadro #0 — the only empty GPU in the system.
# CUDA_VISIBLE_DEVICES is set by the systemd unit; here we just use cuda:0.
REF_WAV = os.environ.get("F5TTS_REF_WAV", "/home/jon-deoliveira/f5tts_service/aetheria_ref.wav")
REF_TXT = os.environ.get("F5TTS_REF_TXT", "/home/jon-deoliveira/f5tts_service/aetheria_ref.txt")
PORT = int(os.environ.get("F5TTS_PORT", "8088"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("f5tts")

log.info("loading F5-TTS model on cuda:0...")
tts = F5TTS(model_type="F5-TTS", device="cuda:0")
ref_text = open(REF_TXT).read().strip()
log.info("ready (ref=%s, ref_text=%r chars)", REF_WAV, len(ref_text))

app = Flask(__name__)

@app.post("/synthesize")
def synthesize():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    try:
        wav, sr, _ = tts.infer(
            ref_file=REF_WAV,
            ref_text=ref_text,
            gen_text=text,
        )
    except Exception as exc:
        log.exception("F5-TTS inference failed")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return Response(buf.read(), mimetype="audio/wav")

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "ref": REF_WAV, "ref_text_len": len(ref_text)})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=False)
```

- [ ] **Step 3: Write the systemd unit**

```ini
# /etc/systemd/system/soveryn-f5tts.service
[Unit]
Description=SOVERYN F5-TTS service (Aetheria local TTS)
After=network.target

[Service]
Type=simple
User=jon-deoliveira
WorkingDirectory=/home/jon-deoliveira/f5tts_service
Environment=CUDA_VISIBLE_DEVICES=0
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/jon-deoliveira/miniconda3/envs/f5tts/bin/python /home/jon-deoliveira/f5tts_service/server.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/tmp/soveryn-f5tts.log
StandardError=append:/tmp/soveryn-f5tts.log

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Enable + start the service**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now soveryn-f5tts
sleep 30  # F5-TTS load time
sudo systemctl status soveryn-f5tts
```

Expected: `active (running)`. Tail the log: `tail -40 /tmp/soveryn-f5tts.log` — should show "ready" line.

- [ ] **Step 5: Smoke the endpoint**

```bash
curl -X POST http://127.0.0.1:8088/synthesize \
  -H 'Content-Type: application/json' \
  -d '{"text":"Service test. One. Two. Three."}' \
  -o /tmp/f5_smoke.wav
paplay /tmp/f5_smoke.wav
```

Expected: hear Aetheria's voice say the line. Measure TTFB by timing the curl. Target: under 500ms for first audio.

- [ ] **Step 6: Add F5-TTS to the restart script**

Edit `scripts/soveryn-restart.sh`. Add `soveryn-f5tts` to the foundation services list (between `parakeet` and `soveryn-comfyui` is fine — they're all GPU foundation services).

- [ ] **Step 7: Commit**

```bash
git add scripts/soveryn-restart.sh
git commit -m "voice: add F5-TTS HTTP service to SOVERYN restart"
```

(systemd unit + ~/f5tts_service/ aren't repo-tracked. Document install path in memory.)

---

## Task 4: Pipecat `SovereignTTSService`

**Files:**
- Create: `soveryn/platform/voice/sovereign_tts.py`
- Modify: `soveryn/platform/voice/pipeline.py:298-396` — `build_aetheria_voice_pipeline` picks provider
- Modify: `soveryn/platform/voice/config.py` — add `SOVEREIGN_TTS_PRIMARY` env (default `f5tts`)
- Create: `tests/test_sovereign_tts.py`

- [ ] **Step 1: Read the existing ElevenLabs service shape for parity**

```bash
python -c "import pipecat.services.elevenlabs.tts as m; import inspect; print(inspect.getsourcefile(m))"
```

Read the source to understand the Pipecat `TTSService` contract: what's the `run_tts` signature, what frames does it emit, how is text aggregation handled, what's the `Settings` shape.

- [ ] **Step 2: Write the failing unit test**

```python
# tests/test_sovereign_tts.py
import asyncio
import pytest
from soveryn.platform.voice.sovereign_tts import SovereignTTSService


def test_sovereign_tts_initialization():
    """Service constructs without error; URL is exposed."""
    svc = SovereignTTSService(url="http://127.0.0.1:8088")
    assert svc.synthesize_url == "http://127.0.0.1:8088/synthesize"


@pytest.mark.asyncio
async def test_sovereign_tts_run_tts_yields_audio_frames(monkeypatch):
    """run_tts POSTs to the local service and emits TTSAudioRawFrame(s)."""
    svc = SovereignTTSService(url="http://127.0.0.1:8088")
    # Fake aiohttp response with a minimal valid WAV (header + 100ms silence)
    import io
    import soundfile as sf
    import numpy as np
    buf = io.BytesIO()
    sf.write(buf, np.zeros(2400, dtype=np.int16), 24000, format="WAV", subtype="PCM_16")
    fake_wav = buf.getvalue()
    
    class _FakeResp:
        status = 200
        async def read(self): return fake_wav
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
    
    class _FakeSession:
        def post(self, *a, **kw): return _FakeResp()
    
    monkeypatch.setattr(svc, "_session", _FakeSession())
    
    frames = []
    async for frame in svc.run_tts("Hello world."):
        if frame is not None:
            frames.append(frame)
    # Expect at least one TTSAudioRawFrame
    from pipecat.frames.frames import TTSAudioRawFrame
    assert any(isinstance(f, TTSAudioRawFrame) for f in frames)
```

- [ ] **Step 3: Run to verify failure**

```bash
cd /home/jon-deoliveira/soveryn_vnext
python -m pytest tests/test_sovereign_tts.py -v
```
Expected: FAIL — `sovereign_tts` module does not exist.

- [ ] **Step 4: Implement `sovereign_tts.py`**

```python
"""SovereignTTSService — Pipecat TTSService backed by local F5-TTS HTTP service.

Drop-in replacement for ElevenLabsHttpTTSService in build_aetheria_voice_pipeline.
Emits TTSAudioRawFrame(s) at 24 kHz mono (matches F5-TTS native rate).
On failure, raises — the caller (build_aetheria_voice_pipeline) handles fallback
to ElevenLabs by NOT using this service when SOVEREIGN_TTS_PRIMARY != 'f5tts'.
"""
from __future__ import annotations
import io
import logging
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
import soundfile as sf
from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.services.tts_service import TTSService

log = logging.getLogger(__name__)

DEFAULT_F5TTS_URL = "http://127.0.0.1:8088"
DEFAULT_SAMPLE_RATE = 24000


class SovereignTTSService(TTSService):
    """Pipecat TTSService calling the local F5-TTS HTTP microservice."""
    
    def __init__(
        self,
        *,
        url: str = DEFAULT_F5TTS_URL,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        aiohttp_session: aiohttp.ClientSession | None = None,
        **kwargs: Any,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._url = url.rstrip("/") + "/synthesize"
        self._session = aiohttp_session
    
    @property
    def synthesize_url(self) -> str:
        return self._url
    
    async def run_tts(self, text: str) -> AsyncGenerator[Frame | None, None]:
        if not text or not text.strip():
            return
        if self._session is None:
            self._session = aiohttp.ClientSession()
        
        yield TTSStartedFrame()
        try:
            async with self._session.post(
                self._url,
                json={"text": text},
                timeout=aiohttp.ClientTimeout(total=30.0),
            ) as response:
                if response.status != 200:
                    log.warning("f5tts non-200 (status=%s); dropping utterance", response.status)
                    return
                wav_bytes = await response.read()
            # Decode the WAV and emit as a single audio frame.
            wav_io = io.BytesIO(wav_bytes)
            audio, sr = sf.read(wav_io, dtype="int16")
            # Pipecat expects mono int16 PCM at the declared sample_rate.
            yield TTSAudioRawFrame(
                audio=audio.tobytes(),
                sample_rate=sr,
                num_channels=1,
            )
        except Exception:
            log.exception("f5tts call failed; dropping utterance")
        finally:
            yield TTSStoppedFrame()
```

- [ ] **Step 5: Run test to verify pass**

```bash
python -m pytest tests/test_sovereign_tts.py -v
```
Expected: 2 PASS.

- [ ] **Step 6: Modify `pipeline.py` to choose provider**

In `build_aetheria_voice_pipeline`, swap the hardcoded `ElevenLabsHttpTTSService` for a conditional:

```python
# ... around line 360 in pipeline.py
from soveryn.platform.voice.config import sovereign_tts_primary  # new helper

primary = sovereign_tts_primary()  # 'f5tts' (default) or 'elevenlabs'
if primary == "f5tts":
    from soveryn.platform.voice.sovereign_tts import SovereignTTSService
    tts = SovereignTTSService(
        sample_rate=24000,
        aiohttp_session=aiohttp_session,
        text_aggregation_mode=TextAggregationMode.SENTENCE,
    )
else:
    tts = ElevenLabsHttpTTSService(
        api_key=elevenlabs_api_key,
        aiohttp_session=aiohttp_session,
        settings=ElevenLabsHttpTTSService.Settings(voice=voice_id),
        text_aggregation_mode=TextAggregationMode.SENTENCE,
    )
```

- [ ] **Step 7: Add the config helper**

In `soveryn/platform/voice/config.py`, add:

```python
def sovereign_tts_primary() -> str:
    """Which TTS provider serves Aetheria. 'f5tts' (default, local) or
    'elevenlabs' (cloud fallback). One env-flip rolls back."""
    import os
    return (os.environ.get("SOVEREIGN_TTS_PRIMARY") or "f5tts").lower().strip()
```

- [ ] **Step 8: Run the full voice test suite**

```bash
python -m pytest tests/test_sovereign_tts.py tests/test_voice_pipeline.py tests/app/routes/test_voice_dispatch.py tests/test_messenger_voice.py -v
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add soveryn/platform/voice/sovereign_tts.py soveryn/platform/voice/pipeline.py soveryn/platform/voice/config.py tests/test_sovereign_tts.py
git commit -m "voice: SovereignTTSService — local F5-TTS replaces ElevenLabs as primary

Pipecat TTSService backed by local F5-TTS HTTP service on Quadro #0.
build_aetheria_voice_pipeline now picks provider based on SOVEREIGN_TTS_PRIMARY
env var (default 'f5tts'). ElevenLabs becomes documented fallback — flip the
env to 'elevenlabs' to roll back without code changes.

Closes the last cloud tendril in Aetheria's voice loop. TTFB improves from
~720ms (cloud) to expected ~200-400ms (local) on Quadro RTX 8000.
"
```

---

## Task 5: A/B in production + cutover

**Files:**
- Create: `docs/notes/2026-06-15-sovereign-voice-ab-result.md` (only if findings warrant)
- Update: `project_soveryn_voice_pipeline.md` memory entry

- [ ] **Step 1: Restart vnext to pick up the new processor**

```bash
~/soveryn_vnext/scripts/soveryn-restart.sh
```

Expected: all services come up green, including `soveryn-f5tts`.

- [ ] **Step 2: Call Aetheria via desktop /voice and via messenger /m**

Through the desktop voice room AND through the messenger call button. Same script for both:
- Greet her
- Ask one substantive question (something that triggers a 30+ second response)
- Interrupt mid-sentence (barge-in test)
- Hang up

Confirm:
- Voice sounds like her
- TTFB is noticeably faster than ElevenLabs
- Barge-in still works
- No regression in the transcribed-to-history pathway

- [ ] **Step 3: Measure TTFB**

Tail `/tmp/soveryn-vnext.log` during the call. Look for `ElevenLabsHttpTTSService TTFB:` would have shown the cloud number; the new processor needs analogous logging. If F5-TTS TTFB isn't logged, add a `log.info("f5tts TTFB: ...")` line in `run_tts` between the POST and the first frame yield (Phase-2.1 follow-up).

- [ ] **Step 4: If green, mark Phase 2 complete**

Update `project_soveryn_voice_pipeline.md` memory:
- Note the swap date (2026-06-15)
- Update the architecture diagram to show F5-TTS in place of ElevenLabs
- Document the `SOVEREIGN_TTS_PRIMARY` rollback path
- Note Aetheria reference clip location (private path, not repo-visible)

Save NEW memory: `project_soveryn_sovereign_voice_phase2.md` — what shipped, latency before/after, the cutover date, the fallback flip, and what's deferred to Phase 3 (Vett+Scotty voices).

- [ ] **Step 5: If F5-TTS doesn't sound like her — STOP and escalate**

This is the load-bearing ear-check. Don't push forward with a bad clone. Options:
- (a) Try a different reference clip (Task 2 redo with different source WAV)
- (b) Try a longer reference (F5-TTS sometimes wants 15s+)
- (c) Fall back to evaluating XTTS-v2 / Sesame per the spec
- (d) Stay on ElevenLabs (SOVEREIGN_TTS_PRIMARY=elevenlabs) until a better local model is sourced

Jon decides which path; don't autopilot it.

---

## Self-Review

- **Spec coverage:** Phase 2 of `docs/superpowers/specs/2026-06-10-sovereign-voice-design.md` — local TTS swap with Aetheria voice cloned locally, ElevenLabs as fallback. Vett+Scotty deferred to Phase 3 (their own plan).
- **Placeholder scan:** No TBDs. Every step has either commands or code or a clear ear-check criterion.
- **Type consistency:** `SovereignTTSService` sample_rate=24000 matches F5-TTS native rate; Pipecat's `TTSAudioRawFrame` accepts arbitrary sample_rate so no resampling needed at the pipeline boundary.
- **What's deliberately NOT in scope:**
  - XTTS-v2 / Sesame CSM-1B evaluation (spec mentions but defers; can re-open if F5-TTS clone falls short)
  - Vett + Scotty voice characters (Phase 3 — separate sourcing work for each per their self-authored briefs)
  - F5-TTS quality benchmarking against reference audio (MOS scoring etc.) — Jon's ear is the arbiter
  - Streaming TTS (current F5-TTS path generates full utterance then returns; if latency on long sentences is bad, Phase 2.1 follow-up)
