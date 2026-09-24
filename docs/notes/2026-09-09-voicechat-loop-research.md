# VoiceChat canned loops — what people actually do

*2026-09-09. House observation: spark1 Pipecat VoiceChat is fast; after a few turns it collapses to “I am here to help.” Jon out; this is the research dump.*

## Verdict

Nobody is “fixing” NemotronLabs VoiceChat-11B’s brain on a Spark. NVIDIA documented the loops as **model** behavior. Pipecat’s Spark recipe adds watchdogs and still says they **cannot eliminate model-level errors**. The working pattern in 2026 is: **keep the fast fused mouth, put policy and hard work in an application layer** (or don’t use this checkpoint as the product LLM).

## What NVIDIA and Pipecat already admit

NVIDIA-NeMo/Speech `nemotron-labs-voicechat` README (limitations):

- Repeat canned / irrelevant replies; clarification / refusal loops
- Runaway continuation / self-talk (new agent turns with no user input), including during tool calling
- Word/sentence loops; gibberish after several turns
- ~2 minute audio context — past that, retention is unreliable
- Mixed chat + tools: often answers from its own knowledge instead of calling the tool
- Max ~5 tools/session; cannot reliably call several at once
- User cannot barge in during tool execution

Pipecat `nemotron-voicechat-dgx-spark` + HF `NVIDIA-NemotronLabs-VoiceChat-11B-Spark`:

- Same list. “Deployment adds bounded watchdog and recovery but cannot eliminate model-level errors.”
- Open TODO: **application-layer tool routing** instead of trusting the function head
- Open TODO: session rollover / compaction when context degrades

That matches our traces: `get_current_time` never fired (`completed_calls: 0`); she *said* she would set Eastern and asked herself the time; later every user turn got the same canned help line. Transcription of Jon was fine.

## What people are doing (ranked for us)

### 1. Application router (the one that matches the house)

Do not wait for the 9B function head to pick Kernel/Aetheria.

- Classify the user transcript in **our** code (keywords, small classifier, or a house LLM).
- Easy chat → stay on VoiceChat audio.
- Time / weather / “look this up” → run the tool ourselves, inject the result (NVIDIA on-hold line while it runs).
- Hard / house / code → `ask_aetheria` / `ask_kernel`, speak the return.

Pipecat’s own Spark TODO is this. NVIDIA Voice Agent Blueprint’s **Frontend/Backend Agent** example is the same idea: fast frontend talks; specialized backend does the work.

NVIDIA’s **production** Spark blueprint is **not** fused VoiceChat-11B. It is cascade: Nemotron ASR + vLLM LLM + Magpie TTS, with an Omni+subagents variant where the voice loop stays live while a thinker handles hard turns. That is the tell.

### 2. Turn and echo guards (helps self-talk / echo, not canned collapse)

These stop “she hears herself and starts a new turn,” which is a different loop than “I am here to help” on a real user utterance.

- Headphones / AEC / mute mic while she speaks (OpenAI Realtime community, same class of bug).
- Ignore STT that matches last TTS (classic TTS→STT echo gate).
- `llama-voicechat.cpp`: `VC_NO_BARGE=1` + `VC_FORCE_BOS=1` — model may not open a turn while user audio is still playing; force BOS at the clip edge. Authors say unguarded barge-in answers the first second, then repeats, then **every later turn degenerates**.
- Pipecat already: client-owned turn commits, Smart Turn, silence watchdogs, 12k-frame session cap.

Do these. They will not stop a canned reply to “that’s good.”

### 3. Session hygiene

NVIDIA: 2-minute audio window. Pipecat: after a bad post-tool recovery, **fresh stack** passed; the poisoned session did not. Hard rollover (new WebRTC session) every couple of minutes or after N canned hits is the cheap fix. Compaction of fused audio state is still a research TODO.

### 4. Prompt is a weak lever

Persona “don’t echo” rules help chat UIs. We already saw the opposite: a long tool/time prompt got **read aloud**, then collapse. Keep the spoken system prompt tiny. Ban the canned line. Do not explain rules in the prompt.

### 5. Retrain / bigger fused brain — not tonight

- arXiv 2607.07148: RL on duplex start/stop, **built on the VoiceChat recipe**, 64× A800. Research scale.
- Pipecat **PhoneLLM**: fine-tune of Nemotron 3 Nano **30B-A3B** as a **cascade** voice LLM for tool calling without thinking. Different architecture; aimed at the “said it booked the table and didn’t” failure. Candidate later if we put a bigger brain behind Parakeet/F5 or behind VoiceChat-as-mouth.
- Freeze-Omni pattern: freeze a good text LLM, bolt speech on so spoken IQ ≈ text IQ. That is “Aetheria stays the brain, speech is a shell” — our duplex-shell design from 2026-08-16.

Nobody has published a Spark-sized patch that makes VoiceChat-11B stop canned loops.

## House recommendation when Jon is back

Keep spark1 VoiceChat as the **fast mouth**. Do not put Aetheria on the latency path for hellos.

Next build, in order:

1. Echo/AEC + hard session reset after 2 identical assistant lines (setup).
2. **Our** router on the RNNT transcript: time/tool/house/code vs chitchat. Do not trust the function head.
3. `ask_kernel` / `ask_aetheria` with on-hold audio.
4. Optional later: PhoneLLM or Freeze-Omni-style shell if we need the cascade to feel closer to fused latency without the 9B IQ.

Latency we measured is the fused stack. Circles are the Nano backbone. The field is wrapping that, not waiting for NVIDIA to ship an arm64 NIM that also thinks.

## Sources

- https://github.com/NVIDIA-NeMo/Speech/tree/nemotron-labs-voicechat (limitations)
- https://github.com/pipecat-ai/nemotron-voicechat-dgx-spark (TODO + known-limitations)
- https://huggingface.co/pipecat-ai/NVIDIA-NemotronLabs-VoiceChat-11B-Spark
- https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent (cascade + frontend/backend + omni subagents)
- https://github.com/sansamour/llama-voicechat.cpp/blob/voicechat/tools/voicechat/README.md (`VC_NO_BARGE` / `VC_FORCE_BOS`)
- https://www.daily.co/blog/announcing-pipecat-phonellm-alpha-1/
- https://community.openai.com/t/real-time-model-is-hearing-and-talking-to-itself-in-a-loop/1066520
- arXiv:2607.07148 (RL duplex on VoiceChat recipe)
- House traces: `spark:~/.local/state/nemotron-voicechat/traces/model/`
