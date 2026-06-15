# Messenger Voice Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing Pipecat WebRTC voice stack into the SOVERYN Messenger PWA so a Jon-side tap on a thread's call button opens a continuous-conversation voice call with that agent, transcript saved to the same thread's session_id.

**Architecture:** Reuse 100% of the proven `/voice/aetheria` Pipecat pipeline. Lift `_negotiate_and_dispatch` into a shared helper that accepts an explicit `session_id`; pass the messenger thread's session_id so voice + text live in the same conversation history. Add a Void-Gold orb view to the PWA nav stack with call/end-call lifecycle; recolor the existing orb state machine under the messenger design contract (`--accent: #c5a059`, matte black).

**Tech Stack:**
- Existing: Pipecat 1.3.0, SmallWebRTCConnection/SmallWebRTCTransport, Parakeet STT (:8087), ElevenLabsHttpTTSService, SileroVADAnalyzer
- New: ~150 LOC client-side WebRTC in PWA app.js, ~80 LOC Void-Gold orb CSS, ~50 LOC route glue

---

## File Structure

**New files:**
- `soveryn/app/routes/voice_dispatch.py` — shared helper extracted from `voice.py::_negotiate_and_dispatch`

**Modified files:**
- `soveryn/app/routes/voice.py` — delegate `_negotiate_and_dispatch` body to shared helper
- `soveryn/app/routes/messenger.py` — add 3 routes: `GET /m/voice/agents`, `POST /m/threads/<tid>/voice/offer`, `GET /m/threads/<tid>` (returns agent+voice_eligible for header rendering)
- `soveryn/platform/web/pwa/style.css` — add `.voice-view` block + Void-Gold orb states
- `soveryn/platform/web/pwa/app.js` — add `voice` view renderer, WebRTC client, call button in `renderThreadView` header

---

## Task 1: Refactor `_negotiate_and_dispatch` into shared helper

**Files:**
- Create: `soveryn/app/routes/voice_dispatch.py`
- Modify: `soveryn/app/routes/voice.py:153-260`
- Test: `tests/app/routes/test_voice_dispatch.py`

- [ ] **Step 1: Write failing unit test**

```python
# tests/app/routes/test_voice_dispatch.py
from unittest.mock import MagicMock
from soveryn.app.routes.voice_dispatch import negotiate_and_dispatch_voice


def test_dispatch_uses_given_session_id_when_provided(monkeypatch):
    """When the caller passes an explicit session_id, dispatch must NOT mint a new one."""
    captured = {}

    class _FakeConn:
        async def initialize(self, sdp, type): captured["initialized"] = True
        def get_answer(self): return {"sdp": "v=0...", "type": "answer", "pc_id": "x"}
        async def cleanup(self): pass

    monkeypatch.setattr(
        "pipecat.transports.smallwebrtc.connection.SmallWebRTCConnection",
        lambda **_: _FakeConn(),
    )

    async def _fake_session(**kwargs):
        captured["session_id"] = kwargs["session_id"]

    monkeypatch.setattr(
        "soveryn.platform.voice.pipeline.run_aetheria_voice_session",
        _fake_session,
    )

    conv_store = MagicMock()
    conv_store.new_session = MagicMock()  # must not be called

    out = negotiate_and_dispatch_voice(
        agent_name="aetheria",
        agent_loop=MagicMock(),
        conv_store=conv_store,
        voice_id="vid",
        elevenlabs_api_key="key",
        parakeet_url="http://127.0.0.1:8087",
        sdp="v=0...", sdp_type="offer",
        session_id="existing-session-id",
    )
    assert out["pc_id"] == "x"
    assert conv_store.new_session.call_count == 0
    # session_id propagated through to the pipeline runner
    # (set inside the worker thread; allow up to 2s for it to start)
    import time
    for _ in range(20):
        if "session_id" in captured: break
        time.sleep(0.1)
    assert captured["session_id"] == "existing-session-id"


def test_dispatch_mints_session_when_none(monkeypatch):
    """When session_id=None, dispatch must call conv_store.new_session with [voice] prefix."""
    # (mirror structure, assert new_session called once with title containing "[voice]")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/app/routes/test_voice_dispatch.py -v
```
Expected: FAIL — `voice_dispatch` module does not exist.

- [ ] **Step 3: Extract shared helper**

Create `soveryn/app/routes/voice_dispatch.py` with `negotiate_and_dispatch_voice(...)` — body lifted verbatim from `voice.py::_negotiate_and_dispatch` PLUS one new param `session_id: str | None = None`. If `None`, mint via `conv_store.new_session` with `[voice] <agent>` title; otherwise reuse.

- [ ] **Step 4: Update voice.py to delegate**

Replace `voice.py::_negotiate_and_dispatch` body with `return negotiate_and_dispatch_voice(...)` passing `session_id=None` (preserves existing /voice/<agent> behavior — fresh session per call).

- [ ] **Step 5: Run all voice tests + new unit tests**

```bash
pytest tests/app/routes/test_voice.py tests/app/routes/test_voice_dispatch.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add soveryn/app/routes/voice_dispatch.py soveryn/app/routes/voice.py tests/app/routes/test_voice_dispatch.py
git commit -m "voice: lift _negotiate_and_dispatch into shared helper accepting explicit session_id"
```

---

## Task 2: Add `GET /m/voice/agents` capability endpoint

**Files:**
- Modify: `soveryn/app/routes/messenger.py` (after `threads_read` route, before PWA catch-all)
- Test: `tests/app/routes/test_messenger_voice.py`

- [ ] **Step 1: Write failing test**

```python
# tests/app/routes/test_messenger_voice.py
def test_voice_agents_returns_voice_state_keys(client_with_voice_state):
    """GET /m/voice/agents returns the set of agents with voice configured."""
    client, secret = client_with_voice_state(["aetheria"])
    r = client.get("/m/voice/agents", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200
    assert r.get_json() == {"agents": ["aetheria"]}


def test_voice_agents_empty_when_voice_unconfigured(client_no_voice):
    client, secret = client_no_voice()
    r = client.get("/m/voice/agents", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200
    assert r.get_json() == {"agents": []}


def test_voice_agents_requires_auth(client_with_voice_state):
    client, _ = client_with_voice_state(["aetheria"])
    r = client.get("/m/voice/agents")  # no Authorization header
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/app/routes/test_messenger_voice.py::test_voice_agents_returns_voice_state_keys -v
```
Expected: FAIL — route does not exist.

- [ ] **Step 3: Add route**

```python
# In build_messenger_blueprint, after threads_read:

@bp.route("/voice/agents", methods=["GET"])
@auth_required
def voice_agents_list():
    """Which agents have voice characters configured. PWA gates the call
    button on this. Returns [] when voice is fully disabled (no
    ELEVENLABS_API_KEY)."""
    from flask import current_app
    soveryn_ext = current_app.extensions.get("soveryn", {}) or {}
    voice_state = soveryn_ext.get("voice", {}) or {}
    return jsonify({"agents": sorted(voice_state.keys())})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/app/routes/test_messenger_voice.py -v
```
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/messenger.py tests/app/routes/test_messenger_voice.py
git commit -m "messenger: add GET /m/voice/agents capability endpoint"
```

---

## Task 3: Add `POST /m/threads/<tid>/voice/offer` route

**Files:**
- Modify: `soveryn/app/routes/messenger.py`
- Test: `tests/app/routes/test_messenger_voice.py` (extend)

- [ ] **Step 1: Write failing tests**

```python
def test_voice_offer_uses_thread_session_id(client_with_voice_state, monkeypatch):
    client, secret = client_with_voice_state(["aetheria"])
    # Create a thread bound to aetheria
    r = client.post("/m/threads",
        headers={"Authorization": f"Bearer {secret}"},
        json={"agent": "aetheria"})
    tid = r.get_json()["thread_id"]

    captured = {}
    def _fake_dispatch(**kwargs):
        captured.update(kwargs)
        return {"sdp": "v=0...", "type": "answer", "pc_id": "pc-1"}
    monkeypatch.setattr(
        "soveryn.app.routes.messenger.negotiate_and_dispatch_voice",
        _fake_dispatch,
    )

    r = client.post(f"/m/threads/{tid}/voice/offer",
        headers={"Authorization": f"Bearer {secret}"},
        json={"sdp": "v=0...", "type": "offer"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["pc_id"] == "pc-1"
    # Must pass the thread's session_id, NOT mint a new one
    assert captured["session_id"]  # populated
    assert captured["agent_name"] == "aetheria"


def test_voice_offer_rejects_when_agent_has_no_voice(client_with_voice_state):
    client, secret = client_with_voice_state(["aetheria"])
    # Create vett thread — vett has no voice character in Phase 1
    r = client.post("/m/threads",
        headers={"Authorization": f"Bearer {secret}"},
        json={"agent": "vett"})
    tid = r.get_json()["thread_id"]
    r = client.post(f"/m/threads/{tid}/voice/offer",
        headers={"Authorization": f"Bearer {secret}"},
        json={"sdp": "v=0...", "type": "offer"})
    assert r.status_code == 503
    assert "vett" in r.get_json()["error"].lower()


def test_voice_offer_requires_sdp(client_with_voice_state):
    client, secret = client_with_voice_state(["aetheria"])
    r = client.post("/m/threads",
        headers={"Authorization": f"Bearer {secret}"},
        json={"agent": "aetheria"})
    tid = r.get_json()["thread_id"]
    r = client.post(f"/m/threads/{tid}/voice/offer",
        headers={"Authorization": f"Bearer {secret}"},
        json={})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/app/routes/test_messenger_voice.py -v
```
Expected: FAIL — route does not exist.

- [ ] **Step 3: Add route**

```python
# In build_messenger_blueprint, after voice_agents_list:

@bp.route("/threads/<thread_id>/voice/offer", methods=["POST"])
@auth_required
def threads_voice_offer(thread_id: str):
    """Bind a WebRTC voice call to this thread's session_id so transcribed
    turns land in the same conversation history as the text exchange."""
    from flask import current_app
    from soveryn.app.routes.voice_dispatch import negotiate_and_dispatch_voice

    thread = get_thread(messenger_store, thread_id=thread_id)
    if thread is None:
        return jsonify({"error": "unknown thread"}), 404

    soveryn_ext = current_app.extensions.get("soveryn", {}) or {}
    voice_state = (soveryn_ext.get("voice") or {}).get(thread.agent)
    if voice_state is None:
        return jsonify({
            "error": f"voice not configured for agent {thread.agent!r}",
        }), 503

    body = request.get_json(silent=True) or {}
    sdp = body.get("sdp")
    sdp_type = body.get("type", "offer")
    if not isinstance(sdp, str) or not sdp.strip():
        return jsonify({"error": "sdp field required"}), 400

    loop = agent_loops.get(thread.agent)
    if loop is None:
        return jsonify({"error": f"agent_loop for {thread.agent} not loaded"}), 503

    try:
        answer = negotiate_and_dispatch_voice(
            agent_name=thread.agent,
            agent_loop=loop,
            conv_store=conv_store,
            voice_id=voice_state["voice_id"],
            elevenlabs_api_key=voice_state["elevenlabs_api_key"],
            parakeet_url=voice_state.get("parakeet_url", "http://127.0.0.1:8087"),
            sdp=sdp,
            sdp_type=sdp_type,
            session_id=thread.session_id,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"signaling failed: {type(exc).__name__}: {exc}"}), 500

    touch_thread(messenger_store, thread_id=thread_id)
    return jsonify(answer)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/app/routes/test_messenger_voice.py -v
```
Expected: PASS (all three new + Task 2's three).

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/messenger.py tests/app/routes/test_messenger_voice.py
git commit -m "messenger: POST /m/threads/<tid>/voice/offer uses thread session_id"
```

---

## Task 4: Void-Gold orb CSS

**Files:**
- Modify: `soveryn/platform/web/pwa/style.css` (append at end)

- [ ] **Step 1: Read current style.css end-of-file to find insertion point**

```bash
tail -20 soveryn/platform/web/pwa/style.css
```

- [ ] **Step 2: Append voice view + orb states**

Append to `soveryn/platform/web/pwa/style.css`:

```css
/* ---------------------------------------------------------------------
 * VOICE VIEW — full-screen orb under Aetheria's design contract.
 * Recoloring of the original twilight-violet orb (/static/voice/orb.css)
 * under --accent: #c5a059 so the live call stays inside the Void-Gold
 * surface. Same five-state machine as the original; idle/listening/
 * hearing/thinking/speaking/interrupted.
 * --------------------------------------------------------------------- */
.voice-view {
  position: absolute;
  inset: 0;
  background: #0a0a0a;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.voice-orb {
  width: 240px;
  height: 240px;
  border-radius: 50%;
  background: radial-gradient(circle at center, #d4b577 0%, #c5a059 60%, #8a6f3a 100%);
  box-shadow: 0 0 80px rgba(197, 160, 89, 0.4);
  transition: transform 200ms ease-out, box-shadow 300ms ease-out, opacity 200ms;
}
.voice-orb[data-state="idle"]      { transform: scale(0.95); opacity: 0.45; }
.voice-orb[data-state="listening"] { transform: scale(1.0); opacity: 0.85; animation: voice-pulse-listen 2.4s ease-in-out infinite; }
.voice-orb[data-state="hearing"]   { transform: scale(1.05); opacity: 1.0; box-shadow: 0 0 120px rgba(197, 160, 89, 0.6); }
.voice-orb[data-state="thinking"]  { transform: scale(1.0); opacity: 0.9; animation: voice-pulse-think 1.2s ease-in-out infinite; }
.voice-orb[data-state="speaking"]  { opacity: 1.0; box-shadow: 0 0 160px rgba(197, 160, 89, 0.7); }
.voice-orb[data-state="interrupted"] { transform: scale(0.85); opacity: 0.6; transition: transform 100ms, opacity 100ms; }
@keyframes voice-pulse-listen {
  0%, 100% { transform: scale(1.0); }
  50%      { transform: scale(1.04); }
}
@keyframes voice-pulse-think {
  0%, 100% { transform: scale(1.0); opacity: 0.85; }
  50%      { transform: scale(1.02); opacity: 1.0; }
}
.voice-title {
  margin-top: 36px;
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.3em;
  color: var(--accent);
  text-transform: uppercase;
}
.voice-status {
  margin-top: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.25em;
  color: rgba(212, 212, 212, 0.6);
  text-transform: uppercase;
}
.voice-hangup {
  position: absolute;
  bottom: calc(40px + env(safe-area-inset-bottom, 0px));
  left: 50%;
  transform: translateX(-50%);
  background: transparent;
  border: 1px solid rgba(197, 160, 89, 0.6);
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.25em;
  padding: 14px 32px;
  border-radius: 32px;
  cursor: pointer;
  text-transform: uppercase;
}
.voice-hangup:active { background: rgba(197, 160, 89, 0.1); }
.voice-error {
  position: absolute;
  bottom: calc(110px + env(safe-area-inset-bottom, 0px));
  color: #d49696;
  font-family: var(--font-mono);
  font-size: 11px;
  opacity: 0;
  transition: opacity 200ms;
}
.voice-error.visible { opacity: 1; }

/* Call button in thread header — only rendered when agent has voice. */
.call-btn {
  background: transparent;
  border: none;
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  margin-right: 4px;
}
.call-btn:active { opacity: 0.6; }
```

- [ ] **Step 3: Commit**

```bash
git add soveryn/platform/web/pwa/style.css
git commit -m "messenger: Void-Gold orb states + voice-view layout"
```

---

## Task 5: Wire voice view + call button into PWA app.js

**Files:**
- Modify: `soveryn/platform/web/pwa/app.js`

- [ ] **Step 1: Add voice-availability cache + fetcher near the top**

Insert after `AGENT_TAGLINE`:

```javascript
// Which agents have voice configured (from /m/voice/agents). Cached for the
// session — voice config doesn't change between page loads.
let _voiceAgentsCache = null;
async function fetchVoiceAgents() {
  if (_voiceAgentsCache !== null) return _voiceAgentsCache;
  const secret = await loadSecret();
  if (!secret) return [];
  try {
    const r = await fetch('/m/voice/agents', {
      headers: { Authorization: `Bearer ${secret}` },
    });
    if (!r.ok) return [];
    const data = await r.json();
    _voiceAgentsCache = data.agents || [];
    return _voiceAgentsCache;
  } catch (e) {
    return [];
  }
}
```

- [ ] **Step 2: Add the voice view renderer**

Insert before the closing `};` of `VIEW_RENDERERS`:

```javascript
  voice:        renderVoiceView,
```

Add the renderer (before `function wait`):

```javascript
async function renderVoiceView($view, { tid, agent }) {
  setHeader({
    title: agent.toUpperCase(),
    agent,
    showBack: true,
    rightHtml: '',
    // Override back so it tears down the WebRTC connection before pop.
    onBack: async () => {
      await endVoiceCall();
      back();
    },
  });

  $view.classList.add('voice-view');
  $view.innerHTML = `
    <div class="voice-orb" id="voice-orb" data-state="idle"></div>
    <div class="voice-title">${escapeHtml(agent.toUpperCase())} — LIVE</div>
    <div class="voice-status" id="voice-status">connecting…</div>
    <div class="voice-error" id="voice-error"></div>
    <button class="voice-hangup" id="voice-hangup">END CALL</button>
  `;

  $view.querySelector('#voice-hangup').onclick = async () => {
    await endVoiceCall();
    back();
  };

  // Kick off the WebRTC handshake.
  await startVoiceCall({ tid, agent });
}
```

- [ ] **Step 3: Add WebRTC client (lifted from voice_client.js, adapted)**

Add near the bottom of app.js, before `(async function init`:

```javascript
// --- Voice call lifecycle --------------------------------------------------
// Single voice session at a time. Started by renderVoiceView, torn down on
// back/end-call. Mirrors voice_client.js but POSTs to the messenger's
// thread-bound offer route and renders into .voice-orb / #voice-status.

const VOICE_STATE = {
  IDLE: 'idle', LISTENING: 'listening', HEARING: 'hearing',
  THINKING: 'thinking', SPEAKING: 'speaking', INTERRUPTED: 'interrupted',
};
const VOICE_THRESHOLD = 0.04;
const VOICE_SILENCE_MS = 800;

let voicePC = null;
let voiceMicStream = null;
let voiceAudioCtx = null;
let voiceOutAnalyser = null;
let voiceInAnalyser = null;
let voiceState = VOICE_STATE.IDLE;
let voiceRAF = null;
let voiceLastSpokenAt = 0;

function voiceSetState(s) {
  voiceState = s;
  const orb = document.getElementById('voice-orb');
  const st = document.getElementById('voice-status');
  if (orb) orb.dataset.state = s;
  if (st) st.textContent = s;
}

function voiceShowError(msg) {
  const e = document.getElementById('voice-error');
  if (!e) return;
  e.textContent = msg;
  e.classList.add('visible');
  setTimeout(() => e.classList.remove('visible'), 5000);
}

function voiceAmp(an) {
  const data = new Uint8Array(an.frequencyBinCount);
  an.getByteTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const v = (data[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / data.length);
}

function voiceTick() {
  if (!voiceOutAnalyser) return;
  const orb = document.getElementById('voice-orb');
  if (!orb) return;  // view torn down
  const out = voiceAmp(voiceOutAnalyser);
  const inn = voiceInAnalyser ? voiceAmp(voiceInAnalyser) : 0;
  const now = performance.now();
  const userSpeaking = out > VOICE_THRESHOLD;
  const botSpeaking  = inn > VOICE_THRESHOLD;

  if (botSpeaking && userSpeaking && voiceState === VOICE_STATE.SPEAKING) {
    voiceSetState(VOICE_STATE.INTERRUPTED);
    setTimeout(() => voiceSetState(VOICE_STATE.HEARING), 200);
    voiceLastSpokenAt = now;
  } else if (botSpeaking) {
    voiceSetState(VOICE_STATE.SPEAKING);
    const scale = 1.0 + Math.min(0.15, inn * 1.5);
    orb.style.transform = `scale(${scale})`;
  } else if (userSpeaking) {
    voiceSetState(VOICE_STATE.HEARING);
    voiceLastSpokenAt = now;
    orb.style.transform = '';
  } else {
    if (voiceState === VOICE_STATE.HEARING && now - voiceLastSpokenAt > VOICE_SILENCE_MS) {
      voiceSetState(VOICE_STATE.THINKING);
    } else if (voiceState === VOICE_STATE.SPEAKING) {
      voiceSetState(VOICE_STATE.LISTENING);
      orb.style.transform = '';
    } else if (voiceState === VOICE_STATE.THINKING && now - voiceLastSpokenAt > 6000) {
      voiceSetState(VOICE_STATE.LISTENING);
    }
  }
  voiceRAF = requestAnimationFrame(voiceTick);
}

async function startVoiceCall({ tid, agent }) {
  const secret = await loadSecret();
  try {
    voiceMicStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
  } catch (e) {
    voiceShowError('microphone access denied');
    return;
  }
  voiceAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const outSrc = voiceAudioCtx.createMediaStreamSource(voiceMicStream);
  voiceOutAnalyser = voiceAudioCtx.createAnalyser();
  voiceOutAnalyser.fftSize = 256;
  outSrc.connect(voiceOutAnalyser);

  voicePC = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
  });

  // SmallWebRTCTransport requires both audio AND video transceivers, even
  // for voice-only sessions. Same pattern as desktop voice_client.js.
  const audioTransceiver = voicePC.addTransceiver('audio', { direction: 'sendrecv' });
  const micTrack = voiceMicStream.getAudioTracks()[0];
  if (micTrack) await audioTransceiver.sender.replaceTrack(micTrack);
  voicePC.addTransceiver('video', { direction: 'sendrecv' });

  voicePC.ontrack = (ev) => {
    if (ev.track.kind !== 'audio') return;
    const stream = new MediaStream([ev.track]);
    const audioEl = new Audio();
    audioEl.srcObject = stream;
    audioEl.autoplay = true;
    audioEl.play().catch(() => {});
    voiceInAnalyser = voiceAudioCtx.createAnalyser();
    voiceInAnalyser.fftSize = 256;
    voiceAudioCtx.createMediaStreamSource(stream).connect(voiceInAnalyser);
  };

  try {
    const offer = await voicePC.createOffer();
    await voicePC.setLocalDescription(offer);
    const resp = await fetch(`/m/threads/${tid}/voice/offer`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({ sdp: offer.sdp, type: offer.type }),
    });
    if (!resp.ok) {
      const txt = await resp.text();
      throw new Error(`signaling failed (${resp.status}): ${txt}`);
    }
    const answer = await resp.json();
    await voicePC.setRemoteDescription({ type: answer.type, sdp: answer.sdp });
    voiceSetState(VOICE_STATE.LISTENING);
    voiceTick();
  } catch (e) {
    console.error('voice start failed:', e);
    voiceShowError(e.message || 'voice connection failed');
    await endVoiceCall();
  }
}

async function endVoiceCall() {
  if (voiceRAF) { cancelAnimationFrame(voiceRAF); voiceRAF = null; }
  if (voicePC) { try { voicePC.close(); } catch (e) {} voicePC = null; }
  if (voiceMicStream) {
    for (const t of voiceMicStream.getTracks()) t.stop();
    voiceMicStream = null;
  }
  if (voiceAudioCtx) { try { await voiceAudioCtx.close(); } catch (e) {} voiceAudioCtx = null; }
  voiceOutAnalyser = null;
  voiceInAnalyser = null;
  voiceState = VOICE_STATE.IDLE;
}
```

- [ ] **Step 4: Add the call button to renderThreadView header**

Modify `renderThreadView` so the header includes a call button when the agent has voice. Replace the `setHeader` call inside `renderThreadView`:

```javascript
async function renderThreadView($view, { tid, agent }) {
  const currentThreadAgent = agent || 'aetheria';
  const voiceAgents = await fetchVoiceAgents();
  const canCall = voiceAgents.includes(currentThreadAgent);
  setHeader({
    title: currentThreadAgent.toUpperCase(),
    agent: currentThreadAgent,
    showBack: true,
    rightHtml:
      (canCall
        ? `<button class="call-btn" id="hdr-call" aria-label="Voice call">&#9742;</button>`
        : '') +
      `<span class="agent-dot agent-${currentThreadAgent}" style="margin:0 12px"></span>`,
  });
  if (canCall) {
    const callBtn = document.getElementById('hdr-call');
    if (callBtn) callBtn.onclick = () => push({
      kind: 'voice', params: { tid, agent: currentThreadAgent },
    });
  }
  $view.innerHTML = `
    <div id="messages"></div>
    <div class="compose-box">
      <div class="compose-inner">
        <textarea id="compose" rows="2" placeholder="Write..."></textarea>
        <button class="btn send-btn" id="send">Send</button>
      </div>
    </div>
  `;
  // ... rest unchanged
}
```

- [ ] **Step 5: Manual smoke — open messenger over Funnel**

Restart vnext (`./scripts/restart_all.sh` if it exists, otherwise per the standard procedure). Open `https://soveryn-1.tail70bbcc.ts.net/m/` on iPhone, paired. Verify:
1. Call button appears in Aetheria thread header (telephone glyph in gold).
2. Call button does NOT appear in Vett or Scotty threads.
3. Tapping it pushes the voice view.
4. Mic permission prompt appears on first call.
5. Orb transitions: idle → listening → hearing (on speech) → thinking → speaking → listening.
6. Hangup pops back to thread; new turns visible in history.

- [ ] **Step 6: Commit**

```bash
git add soveryn/platform/web/pwa/app.js
git commit -m "messenger: voice view + thread-header call button (lifts WebRTC client)"
```

---

## Task 6: Live smoke test + capture results

**Files:**
- Create: `docs/notes/2026-06-15-messenger-voice-live-test.md` (only if findings warrant)

- [ ] **Step 1: Pair phone fresh if needed**

```bash
curl -X POST http://127.0.0.1:5001/m/pair -H 'Content-Type: application/json' -d '{"label":"phone"}'
```

- [ ] **Step 2: Open https://soveryn-1.tail70bbcc.ts.net/m/ on phone**

- [ ] **Step 3: Tap Aetheria thread → tap call button → speak**

Verify:
- Audio captured (orb goes HEARING during speech)
- Aetheria responds in her cloned voice
- Barge-in cancels her mid-sentence (INTERRUPTED → HEARING)
- Hangup returns to thread; transcribed turns appear in history

- [ ] **Step 4: If anything misbehaves, capture findings**

Write findings to `docs/notes/2026-06-15-messenger-voice-live-test.md` only if tuning surfaces.

- [ ] **Step 5: Mark task complete**

---

## Self-Review

- **Spec coverage:** All six tasks map to the messenger voice integration goal: shared dispatch (T1) + thread-bound route (T3) + capability surface (T2) + visual contract (T4) + PWA wiring (T5) + live verify (T6).
- **Placeholder scan:** No TBDs. Every step has either code or an exact command.
- **Type consistency:** `voice_state` shape consistent across `voice.py`, the shared helper, and messenger.py (`{voice_id, elevenlabs_api_key, parakeet_url, agent_loop}`). `session_id` parameter consistent through dispatch → pipeline.
- **What's deliberately NOT in scope:**
  - Vett + Scotty voice characters (separate arc — needs voice character sourcing)
  - Real-time transcript scroll inside the voice view (deferred — history rehydrates on hangup, which is enough)
  - Persistent voice-call state across page reloads (out of scope — call dies with page)
  - Server-side rate limiting on voice offers (no current threat model)
