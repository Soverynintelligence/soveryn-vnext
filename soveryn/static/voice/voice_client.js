// soveryn/app/static/voice/voice_client.js
//
// Pipecat WebRTC client for the SOVERYN orb UI. Phase 1: Aetheria-only.
// State machine driven from audio amplitude analysis (Phase 3 may parse
// Pipecat's data channel for richer state events).

(() => {
    const agent = document.body.dataset.agent || "aetheria";
    const orb = document.getElementById("orb");
    const statusEl = document.getElementById("status");
    const errorEl = document.getElementById("error");

    const STATES = {
        IDLE: "idle",
        LISTENING: "listening",
        HEARING: "hearing",
        THINKING: "thinking",
        SPEAKING: "speaking",
        INTERRUPTED: "interrupted",
    };

    let pc = null;
    let micStream = null;
    let audioContext = null;
    let outboundAnalyser = null;
    let inboundAnalyser = null;
    let currentState = STATES.IDLE;
    let speakingFrame = null;

    function setState(state) {
        currentState = state;
        orb.dataset.state = state;
        if (statusEl) statusEl.textContent = state;
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
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
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
        analyser.fftSize = 256;
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

    const VOICE_THRESHOLD = 0.04;
    const SILENCE_TIMEOUT_MS = 800;
    let lastSpeakingAt = 0;

    function tickStateMachine() {
        if (!outboundAnalyser) return;
        const outAmp = avgAmplitude(outboundAnalyser);
        const inAmp = inboundAnalyser ? avgAmplitude(inboundAnalyser) : 0;
        const now = performance.now();

        const userSpeaking = outAmp > VOICE_THRESHOLD;
        const botSpeaking = inAmp > VOICE_THRESHOLD;

        if (botSpeaking && userSpeaking && currentState === STATES.SPEAKING) {
            // Barge-in detection
            setState(STATES.INTERRUPTED);
            setTimeout(() => setState(STATES.HEARING), 200);
            lastSpeakingAt = now;
        } else if (botSpeaking) {
            setState(STATES.SPEAKING);
            // Drive scale from amplitude (subtle pulse)
            const scale = 1.0 + Math.min(0.15, inAmp * 1.5);
            orb.style.transform = `scale(${scale})`;
        } else if (userSpeaking) {
            setState(STATES.HEARING);
            lastSpeakingAt = now;
            orb.style.transform = "";
        } else {
            // No one speaking
            if (currentState === STATES.HEARING && now - lastSpeakingAt > SILENCE_TIMEOUT_MS) {
                setState(STATES.THINKING);
            } else if (currentState === STATES.SPEAKING) {
                setState(STATES.LISTENING);
                orb.style.transform = "";
            } else if (currentState === STATES.THINKING && now - lastSpeakingAt > 6000) {
                // Backend didn't respond — fall back to listening
                setState(STATES.LISTENING);
            } else if (currentState === STATES.IDLE) {
                // wait for user gesture
            }
        }

        speakingFrame = requestAnimationFrame(tickStateMachine);
    }

    async function start() {
        try {
            micStream = await getMic();
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            outboundAnalyser = makeAnalyser(audioContext, micStream);

            pc = new RTCPeerConnection({
                iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
            });

            // CRITICAL: BOTH audio AND video transceivers required by SmallWebRTCTransport.
            // (Per docs/superpowers/notes/2026-06-10-pipecat-spike.md Q4.)
            //
            // Audio: create the transceiver explicitly and attach the mic track
            // via replaceTrack on its sender. Do NOT also call pc.addTrack(track) —
            // that would auto-create a SECOND audio transceiver, leaving one
            // empty and one with the mic, and Pipecat may subscribe to the
            // wrong one. Single-transceiver-per-direction is the right shape.
            const audioTransceiver = pc.addTransceiver("audio", { direction: "sendrecv" });
            const micTrack = micStream.getAudioTracks()[0];
            if (micTrack) {
                await audioTransceiver.sender.replaceTrack(micTrack);
            }
            // Video transceiver required even for voice-only sessions
            pc.addTransceiver("video", { direction: "sendrecv" });

            // Handle inbound TTS audio
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

            // Negotiate SDP
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);

            const resp = await fetch(`/voice/${agent}/offer`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ sdp: offer.sdp, type: offer.type }),
            });
            if (!resp.ok) {
                const err = await resp.text();
                throw new Error(`signaling failed (${resp.status}): ${err}`);
            }
            const answer = await resp.json();
            await pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp });

            setState(STATES.LISTENING);
            tickStateMachine();
        } catch (err) {
            console.error("voice client start failed:", err);
            showError(err.message || "voice connection failed");
            setState(STATES.IDLE);
        }
    }

    // Browsers require a user gesture before getUserMedia + autoplay
    orb.addEventListener("click", () => {
        if (currentState === STATES.IDLE) {
            start();
        }
    });

    setState(STATES.IDLE);
    if (statusEl) statusEl.textContent = "click to begin";
})();
