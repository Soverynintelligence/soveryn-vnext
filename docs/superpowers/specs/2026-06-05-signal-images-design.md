# Signal Image Vision Pipeline — Design

**Status:** approved (Jon + Aetheria, 2026-06-05)
**Author:** Claude (drafted), Jon (locked scope), Aetheria (reviewed)
**Goal:** Close the vision loop across all three of Aetheria's surfaces: inbound from Signal, outbound to Signal, and UI upload from the chat composer.

---

## Problem

Aetheria's main model (Gemma 4 31B-Q8_0 with `mmproj-google_gemma-4-31B-it-bf16.gguf`, loaded via `~/soveryn_complete/router-presets.ini` `[aetheria]`; **note:** the metadata in `soveryn/config/runtime.py` references a Qwen3.6 mmproj path that pre-dates the 2026-06-01 Gemma 4 swap — the launcher preset is authoritative, the Python metadata is stale tech debt) is vision-capable, but:

1. **Inbound Signal:** The `signal_bridge` daemon receives attachments in `InboundMessage.attachment_paths`, but only surfaces them as a placeholder line in the user's text turn:
   `"[Signal: 1 attachment(s) attached — vision pipeline integration pending]"`.
   She can't actually see what Jon sends.

2. **Outbound Signal:** The `signal_send` tool only accepts a text body. Aetheria can't send an image even when relevant.

3. **UI chat:** No file input on the chat composer. Jon can't upload an image to a chat session — only Signal photos exercise her vision at all.

These three are the same architectural problem (`/chat` doesn't accept images) plus three thin surfaces on top.

---

## Shared core

### `ChatMessage.content` widening

`soveryn/platform/inference/llama_server_client.py`:

```python
# Before
@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    ...

# After
@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str | list[dict]   # list form = OpenAI vision parts
    ...
```

When `content` is a list, it's the OpenAI vision-format parts array:

```json
[
  {"type": "text", "text": "What do you see?"},
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
]
```

`_wire_message` already does `out["content"] = m.content` — `json.dumps` serializes either form correctly. No transport-layer change.

`prepare_wire_messages` joins prelude content with `\n\n`. Audit: prelude messages are always system messages built from string sources (persona/pinned/soul/recall). Splice in a defensive check — if any prelude message has non-str content (shouldn't happen but be honest), fold its text parts only.

`_apply_history_budget` operates on history messages loaded from the conversations DB, which are always str-content. No change needed but add an assertion.

### `AgentLoop.process_message{,_stream}` attachments kwarg

`soveryn/agents/loop.py`:

```python
def process_message(
    self,
    session_id: str,
    user_message: str,
    attachments: tuple[str, ...] | None = None,
) -> ChatResponse: ...

def process_message_stream(
    self,
    session_id: str,
    user_message: str,
    attachments: tuple[str, ...] | None = None,
) -> "Iterator[AgentStreamEvent]": ...
```

`attachments` is a tuple of OpenAI image_url URLs — either `data:image/...;base64,...` or `file:///abs/path` (but only base64 for v1; file:// deferred).

Semantics:
- The user-text portion is persisted to the conversations DB **unchanged** (no schema migration, no list-content serialization).
- At request-build time, if `attachments` is non-empty AND the last message of `messages` has role=user (it always does in practice), replace its content with the OpenAI vision-format list.
- If `attachments` is non-empty but the agent isn't `aetheria`, raise `AgentLoopError("attachments only supported for aetheria (only model with mmproj)")` BEFORE save_turn.

### `/chat` and `/chat_stream` route fields

`soveryn/app/routes/chat.py`:

Both routes accept an optional `attachments` field in the JSON body:

```json
{
  "agent": "aetheria",
  "session_id": "...",
  "message": "What's this?",
  "attachments": ["data:image/jpeg;base64,..."]
}
```

Validation:
- Type: `list[str]` if present
- Each entry must start with `data:image/` (image/jpeg, image/png, image/webp, image/gif accepted)
- Reject base64 segment > 25MB pre-decoded (`data:` URL strings up to ~33MB)
- Empty list = treated same as missing

Errors return 400 with `invalid_attachments` code.

If `attachments` is present and the agent isn't `aetheria`, return 400 with `agent_does_not_support_vision`.

---

## Inbound (Signal photo → Aetheria sees it)

`soveryn/agents/signal_bridge/daemon.py`:

For each inbound message:
- For each `attachment_path` in `msg.attachment_paths`:
  - Stat the file; if missing, log and skip.
  - Detect MIME via file extension (`.jpg`/`.jpeg` → `image/jpeg`, `.png` → `image/png`, `.webp` → `image/webp`, `.gif` → `image/gif`). Non-image MIMEs are skipped (audio/video deferred).
  - base64-encode → `f"data:{mime};base64,{b64}"`
- Replace the `"[Signal: N attachment(s) attached — vision pipeline integration pending]"` text with a concise hint line ONLY for non-image attachments (e.g., "[Signal: 1 non-image attachment skipped]"). Pure image messages get no hint line.
- Pass the resulting attachments list via the `attachments` field of the `/chat` POST.
- Bridge audit log `attachment_count` continues to report total (including images).

---

## Outbound (Aetheria sends an image via `signal_send`)

`soveryn/agents/signal_bridge/client.py`:

```python
def send_once(
    *, signal_cli_bin: str, bot_number: str, recipient_e164: str, body: str,
    attachments: tuple[str, ...] = (),
) -> None:
    args = [signal_cli_bin, "-a", bot_number, "send", "-m", body, recipient_e164]
    for path in attachments:
        args = args[:1] + ["-a", bot_number, "send", "-m", body] + \
               sum((["-a", p] for p in attachments), []) + [recipient_e164]
        break  # build once
    ...
```

(simplified — single args build with `-a path` repeated per attachment)

`soveryn/agents/signal_bridge/tools.py`:

`signal_send` tool gains `attachments: list[str] | None = None`:
- Local absolute paths only.
- Each path must exist, be a regular file, and be readable.
- Size cap: 16MB per file (signal-cli's documented limit-ish).
- Reject paths with traversal segments (`..`).
- Reject relative paths.

Schema update so Aetheria sees the new param via the OpenAI tools schema.

---

## UI (chat composer image upload)

`soveryn/app/templates/chat.html`:

- Composer gets a paperclip button (📎) next to send.
- Click → triggers a hidden `<input type="file" accept="image/*" multiple>`.
- Selected files become small thumbnail previews above the textarea, each with a × to remove.
- Visual style: matches the existing composer palette (olive accents for Aetheria's chat).
- Selecting attachments and clicking send POSTs to `/chat_stream` with `attachments: [base64_data_url, ...]`.
- File read happens client-side via `FileReader.readAsDataURL`; cap 4 files / 16MB each on the client (server still validates).
- After send, the sent bubble shows the image inline (small, click-to-zoom optional, deferred).

Restrict the paperclip to Aetheria's chat tab. Other agents' tabs hide it (Aetheria-only vision per the shared-core gate).

---

## What's deferred

- **Multimodal history persistence:** images are NOT stored in the conversations table. Past turns re-loaded for context show their text only — the image is live-only. Same as most chat-with-vision clients today.
- **`file://` path attachments via /chat:** v1 only accepts `data:image/...` data URLs through the route. The bridge encodes file → base64 internally.
- **Outbound URL fetching:** `signal_send` accepts file paths only. No "send the image at this URL" affordance (SSRF surface punt).
- **Non-image attachments (audio/video/PDF):** dropped with audit log entry. Future tasks.
- **Click-to-zoom in UI:** deferred.
- **Multi-agent vision:** only Aetheria has mmproj. Other agents → 400 when attachments sent.

---

## Why this shape

- Single shared core (ChatMessage type widening + AgentLoop splice + /chat field), three thin adapter layers (~50-80 LOC each).
- Storage stays string-typed — no schema migration, no JSON-serialize/deserialize burden.
- Transport (`_wire_message`) already polymorphic via JSON serialization — zero changes.
- Files-only outbound + base64-only inbound keeps SSRF surface flat (no URL-fetching anywhere on the new code paths).
- Aetheria-only gating at the route layer means no model-routing branching downstream — her loop is the only one configured against an mmproj-bearing server.

---

## Re-evaluation triggers

- **Multimodal history:** if Jon notices Aetheria forgetting prior images during multi-turn conversations, revisit (probably JSON-serialize list content in conversations.content, deserialize on load).
- **Streaming with vision:** `/chat_stream` is unchanged in v1; if tokens-per-second on vision requests is slow enough that sync `/chat` UX suffers, plumb attachments through the stream path too.
- **Multi-agent vision:** when DGX Spark adds a second mmproj-bearing model, expand the route's allowed-agent check.

---

## See also

- [project_soveryn_qwen36_vision.md](memory) — prior Qwen vision wiring (now replaced by Gemma 4)
- [project_soveryn_signal_bot.md](memory) — Signal bridge architecture
- [project_soveryn_embeddings_batch_size.md](memory) — recent root-cause that unblocked this work
