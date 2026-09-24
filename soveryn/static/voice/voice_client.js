// soveryn/app/static/voice/voice_client.js
//
// Pipecat WebRTC client for the SOVERYN living presence UI.
// Amplitude state machine + LivingPresence particle face field.

(() => {
    const agent = document.body.dataset.agent || "aetheria";
    const orb = document.getElementById("orb");
    const statusEl = document.getElementById("status");
    const errorEl = document.getElementById("error");

    const STATES = {
        IDLE: "idle",
        CONNECTING: "connecting",
        LISTENING: "listening",
        HEARING: "hearing",
        THINKING: "thinking",
        SPEAKING: "speaking",
        INTERRUPTED: "interrupted",
    };
    const LABELS = {
        idle: "Tap to begin",
        connecting: "Connecting…",
        listening: "Listening…",
        hearing: "Hearing you…",
        thinking: "Thinking…",
        speaking: "Speaking…",
        interrupted: "You first…",
    };

    const VOICE_ENTER = 0.055;
    const VOICE_LEAVE = 0.028;
    const SILENCE_TIMEOUT_MS = 1400;
    const MIN_DWELL_MS = 280;
    const THINK_FALLBACK_MS = 8000;
    const EMA_ALPHA = 0.22;

    let pc = null;
    let micStream = null;
    let audioContext = null;
    let outboundAnalyser = null;
    let inboundAnalyser = null;
    let currentState = STATES.IDLE;
    let speakingFrame = null;
    let lastSpeakingAt = 0;
    let stateChangedAt = 0;
    let outEma = 0;
    let inEma = 0;
    let userActive = false;
    let botActive = false;
    let presence = null;

    function ensurePresence() {
        if (!orb || typeof LivingPresence === "undefined") return null;
        if (!presence) {
            presence = LivingPresence.mount(orb, { agent });
            // Keep tap-to-start on the host after mount (canvas shouldn't steal forever).
            orb.style.cursor = "pointer";
        }
        return presence;
    }

    // Mount immediately so idle feels alive before first tap.
    ensurePresence();
    if (presence) presence.setState(STATES.IDLE);

    function setState(state, force) {
        if (!force && state === currentState) return;
        const now = performance.now();
        if (!force && currentState !== STATES.IDLE && currentState !== STATES.CONNECTING) {
            const elapsed = now - stateChangedAt;
            const sticky =
                (currentState === STATES.SPEAKING && state === STATES.LISTENING) ||
                (currentState === STATES.HEARING && state === STATES.THINKING) ||
                (currentState === STATES.THINKING && state === STATES.LISTENING) ||
                (currentState === STATES.LISTENING && state === STATES.HEARING);
            if (sticky && elapsed < MIN_DWELL_MS) return;
        }
        currentState = state;
        stateChangedAt = now;
        if (orb) orb.dataset.state = state;
        if (statusEl) statusEl.textContent = LABELS[state] || state;
        if (presence) presence.setState(state);
    }

    function showError(msg) {
        if (!errorEl) return;
        errorEl.textContent = msg;
        errorEl.classList.add("visible");
        setTimeout(() => errorEl.classList.remove("visible"), 5000);
    }

    async function getMic() {
        try {
            return await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    channelCount: 1,
                },
                video: false,
            });
        } catch (err) {
            showError("microphone access denied");
            throw err;
        }
    }

    function makeAnalyser(audioCtx, stream) {
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.65;
        source.connect(analyser);
        return analyser;
    }

    function avgAmplitude(analyser) {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
        }
        return Math.sqrt(sum / data.length);
    }

    function gate(ema, wasActive) {
        if (wasActive) return ema > VOICE_LEAVE;
        return ema > VOICE_ENTER;
    }

    function waitForIceGathering(peer, timeoutMs = 1500) {
        if (peer.iceGatheringState === "complete") return Promise.resolve();
        return new Promise((resolve) => {
            let done = false;
            const finish = () => {
                if (done) return;
                done = true;
                peer.removeEventListener("icegatheringstatechange", onChange);
                resolve();
            };
            const onChange = () => {
                if (peer.iceGatheringState === "complete") finish();
            };
            peer.addEventListener("icegatheringstatechange", onChange);
            setTimeout(finish, timeoutMs);
        });
    }

    function tickStateMachine() {
        if (!outboundAnalyser) return;
        const outRaw = avgAmplitude(outboundAnalyser);
        const inRaw = inboundAnalyser ? avgAmplitude(inboundAnalyser) : 0;
        outEma = outEma + EMA_ALPHA * (outRaw - outEma);
        inEma = inEma + EMA_ALPHA * (inRaw - inEma);
        const now = performance.now();

        const userSpeaking = gate(outEma, userActive);
        const botSpeaking = gate(inEma, botActive);
        userActive = userSpeaking;
        botActive = botSpeaking;

        if (presence) presence.setLevels({ out: outEma, inn: inEma });

        if (botSpeaking && userSpeaking && currentState === STATES.SPEAKING) {
            setState(STATES.INTERRUPTED, true);
            setTimeout(() => {
                if (pc) setState(STATES.HEARING, true);
            }, 220);
            lastSpeakingAt = now;
        } else if (botSpeaking) {
            setState(STATES.SPEAKING);
        } else if (userSpeaking) {
            setState(STATES.HEARING);
            lastSpeakingAt = now;
        } else {
            if (currentState === STATES.HEARING && now - lastSpeakingAt > SILENCE_TIMEOUT_MS) {
                setState(STATES.THINKING);
            } else if (currentState === STATES.SPEAKING) {
                setState(STATES.LISTENING);
            } else if (currentState === STATES.THINKING && now - lastSpeakingAt > THINK_FALLBACK_MS) {
                setState(STATES.LISTENING);
            }
        }

        speakingFrame = requestAnimationFrame(tickStateMachine);
    }

    async function start() {
        try {
            ensurePresence();
            setState(STATES.CONNECTING, true);
            if (statusEl) statusEl.textContent = "Microphone…";
            micStream = await getMic();
            if (statusEl) statusEl.textContent = "Connecting…";
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            if (audioContext.state === "suspended") {
                try { await audioContext.resume(); } catch (e) { /* best effort */ }
            }
            outboundAnalyser = makeAnalyser(audioContext, micStream);
            outEma = 0;
            inEma = 0;
            userActive = false;
            botActive = false;

            pc = new RTCPeerConnection({
                iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
            });

            const audioTransceiver = pc.addTransceiver("audio", { direction: "sendrecv" });
            const micTrack = micStream.getAudioTracks()[0];
            if (micTrack) {
                await audioTransceiver.sender.replaceTrack(micTrack);
            }
            pc.addTransceiver("video", { direction: "sendrecv" });

            pc.ontrack = (event) => {
                if (event.track.kind === "audio") {
                    const stream = new MediaStream([event.track]);
                    const audioEl = new Audio();
                    audioEl.srcObject = stream;
                    audioEl.autoplay = true;
                    audioEl.play().catch((e) => console.warn("inbound audio play failed:", e));
                    inboundAnalyser = makeAnalyser(audioContext, stream);
                }
            };

            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            if (statusEl) statusEl.textContent = "Negotiating…";
            await waitForIceGathering(pc, 600);
            const local = pc.localDescription || offer;

            const resp = await fetch(`/voice/${agent}/offer`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ sdp: local.sdp, type: local.type }),
            });
            if (!resp.ok) {
                const err = await resp.text();
                throw new Error(`signaling failed (${resp.status}): ${err}`);
            }
            const answer = await resp.json();
            await pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp });

            setState(STATES.LISTENING, true);
            tickStateMachine();
        } catch (err) {
            console.error("voice client start failed:", err);
            showError(err.message || "voice connection failed");
            setState(STATES.IDLE, true);
        }
    }

    function beginIfIdle() {
        if (currentState === STATES.IDLE) {
            start();
        }
    }
    orb.addEventListener("click", beginIfIdle);
    orb.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            beginIfIdle();
        }
    });

    setState(STATES.IDLE, true);
})();
