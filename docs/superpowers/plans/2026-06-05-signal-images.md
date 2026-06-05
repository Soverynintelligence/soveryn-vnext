# Signal Image Vision Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the vision loop for Aetheria across all three surfaces: inbound from Signal photos, outbound `signal_send` with images, UI image upload from the chat composer.

**Architecture:** Widen `ChatMessage.content` to `str | list[dict]` (OpenAI vision parts); add `attachments` kwarg to AgentLoop's sync + stream paths that splices image parts into the current user message at request build; add `attachments` field to `/chat` and `/chat_stream` routes; three thin adapter layers (Signal inbound encoder, Signal outbound -a flag, UI composer paperclip).

**Tech Stack:** Python (stdlib), Flask, vanilla JS/HTML, signal-cli, llama-server vision via Gemma 4 + mmproj.

**Spec:** `docs/superpowers/specs/2026-06-05-signal-images-design.md`

---

## Task 1: Widen `ChatMessage.content` type

**Files:**
- Modify: `soveryn/platform/inference/llama_server_client.py:64-69`
- Modify: `soveryn/platform/inference/llama_server_client.py:213` (`prepare_wire_messages` content join)
- Test: `tests/platform/inference/test_llama_server_client.py`

- [ ] **Step 1: Write failing test for list-content passthrough**

```python
def test_wire_message_passes_list_content_through_unchanged():
    """OpenAI vision parts list is passed to JSON as-is."""
    from soveryn.platform.inference.llama_server_client import ChatMessage, _wire_message
    vision_content = [
        {"type": "text", "text": "what's this?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]
    msg = ChatMessage(role="user", content=vision_content)
    wire = _wire_message(msg)
    assert wire == {"role": "user", "content": vision_content}


def test_wire_message_passes_str_content_unchanged():
    """str content is wired through unchanged (regression)."""
    from soveryn.platform.inference.llama_server_client import ChatMessage, _wire_message
    msg = ChatMessage(role="user", content="hello")
    wire = _wire_message(msg)
    assert wire == {"role": "user", "content": "hello"}


def test_prepare_wire_messages_folds_only_str_prelude():
    """prepare_wire_messages is only ever invoked on string-content prelude (system) +
    string-content history. If a list-content message slips into prelude, fold safely."""
    from soveryn.platform.inference.llama_server_client import ChatMessage, prepare_wire_messages
    from soveryn.platform.inference.routing import ModelServer
    # qwen3.6 server triggers the fold path; gemma doesn't
    server = ModelServer(name="aetheria", port=54459, model_alias="aetheria", chat_template="qwen3.6")
    messages = (
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="system", content="pinned"),
        ChatMessage(role="user", content=[
            {"type": "text", "text": "what's this?"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
        ]),
    )
    wired = prepare_wire_messages(messages, server)
    # First wired message is folded system (persona\n\npinned), then user with list intact.
    assert wired[0].role == "system"
    assert wired[0].content == "persona\n\npinned"
    assert wired[1].role == "user"
    assert isinstance(wired[1].content, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/platform/inference/test_llama_server_client.py -v -k "list_content or str_content_unchanged or only_str_prelude"`
Expected: type-error or assertion failure (current ChatMessage rejects list, prepare_wire_messages may crash on list `m.content`).

- [ ] **Step 3: Implement type widening + defensive prelude fold**

`soveryn/platform/inference/llama_server_client.py:64-69`:

```python
@dataclass(frozen=True)
class ChatMessage:
    role: str          # "system" | "user" | "assistant" | "tool"
    content: str | list[dict]   # str = plain text; list = OpenAI vision-format parts
    tool_call_id: str | None = None
    tool_calls: tuple[dict, ...] | None = None
```

`soveryn/platform/inference/llama_server_client.py:213` — in the prelude-fold loop (current code does `m.content for m in messages[:prelude_end] if m.content`):

```python
def _content_as_str(c: str | list[dict]) -> str:
    """Best-effort text extraction for fold paths (system prelude only)."""
    if isinstance(c, str):
        return c
    # list[dict] vision-format: take text parts
    return "\n\n".join(
        part.get("text", "")
        for part in c
        if isinstance(part, dict) and part.get("type") == "text"
    )

joined = "\n\n".join(_content_as_str(m.content) for m in messages[:prelude_end] if m.content)
```

`_wire_message` needs no change — its `out["content"] = m.content` passes list through unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/platform/inference/test_llama_server_client.py -v`
Expected: PASS (no regressions on existing tests, new tests pass).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/inference/llama_server_client.py tests/platform/inference/test_llama_server_client.py
git commit -m "platform: widen ChatMessage.content to str | list[dict] for vision parts

Adds defensive _content_as_str helper for the prelude-fold path; transport
serialization (_wire_message) is unchanged since json.dumps handles both forms."
```

---

## Task 2: AgentLoop attachments kwarg (sync + stream)

**Files:**
- Modify: `soveryn/agents/loop.py:336` (process_message)
- Modify: `soveryn/agents/loop.py:553` (process_message_stream)
- Test: `tests/agents/test_loop.py`

- [ ] **Step 1: Write failing test for sync-path splice**

```python
def test_process_message_with_attachments_splices_into_current_user_message():
    """When attachments are passed, the wire-level user message becomes a list
    with text + image_url parts; the DB still gets the text-only version."""
    from soveryn.agents.loop import AgentLoop
    # Build a loop fixture (existing helper pattern in test file)
    captured_request = {}
    def fake_chat(req, server, *, timeout):
        captured_request["messages"] = req.messages
        return _make_fake_response("ok")
    loop = _build_test_loop(chat_fn=fake_chat, agent_name="aetheria")
    session_id = loop.conv_store.new_session("aetheria")

    img = "data:image/jpeg;base64,AAAA"
    loop.process_message(session_id, "what's this?", attachments=(img,))

    # DB has text-only user turn
    history = loop.conv_store.load_history(session_id)
    assert history[-1].role == "user"
    assert history[-1].content == "what's this?"  # text only, no JSON

    # Wire request shows the LAST user message as list-content
    sent_user = captured_request["messages"][-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, list)
    text_parts = [p for p in sent_user.content if p["type"] == "text"]
    img_parts = [p for p in sent_user.content if p["type"] == "image_url"]
    assert text_parts == [{"type": "text", "text": "what's this?"}]
    assert img_parts == [{"type": "image_url", "image_url": {"url": img}}]


def test_process_message_without_attachments_unchanged():
    """Regression: attachments=None preserves prior behavior."""
    loop = _build_test_loop(agent_name="aetheria")
    session_id = loop.conv_store.new_session("aetheria")
    loop.process_message(session_id, "plain text")
    history = loop.conv_store.load_history(session_id)
    assert history[-1].content == "plain text"


def test_process_message_attachments_on_non_aetheria_agent_raises():
    """Non-Aetheria agents have no mmproj loaded; loud-fail at the loop layer."""
    from soveryn.agents.loop import AgentLoopError
    loop = _build_test_loop(agent_name="vett")
    session_id = loop.conv_store.new_session("vett")
    with pytest.raises(AgentLoopError, match="attachments only supported"):
        loop.process_message(session_id, "hi", attachments=("data:image/jpeg;base64,AAAA",))
    # No user turn saved on guard rejection.
    assert loop.conv_store.load_history(session_id) == ()
```

Equivalent tests for `process_message_stream` (mirror shape; assert the stream-path request also gets list-content).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_loop.py -v -k "attachments"`
Expected: FAIL (process_message has no attachments kwarg yet).

- [ ] **Step 3: Add kwarg + agent guard + splice in sync path**

`soveryn/agents/loop.py:336`:

```python
def process_message(
    self,
    session_id: str,
    user_message: str,
    attachments: tuple[str, ...] | None = None,
) -> ChatResponse:
    # ... existing session validation ...

    # Vision guard — only Aetheria has mmproj loaded. Reject BEFORE save_turn
    # so guard rejections don't pollute history.
    if attachments and self.agent_name != "aetheria":
        raise AgentLoopError(
            f"attachments only supported for aetheria "
            f"(agent {self.agent_name!r} has no vision model loaded)"
        )

    # 1. Save user turn (text only — vision parts live in-flight)
    self.conv_store.save_turn(session_id, self.agent_name, "user", user_message)

    # ... existing history load, recall, prelude build, history budget ...
    messages: tuple[ChatMessage, ...] = prelude + history_messages

    # ── Vision splice ── replace the last (current) user message's content
    # with a list-form that carries text + image_url parts. Past turns stay
    # str-content; only the live turn gets vision parts.
    if attachments:
        last = messages[-1]
        assert last.role == "user", "last message must be the current user turn"
        text_part = {"type": "text", "text": user_message}
        image_parts = [
            {"type": "image_url", "image_url": {"url": url}} for url in attachments
        ]
        spliced_content = [text_part, *image_parts]
        messages = messages[:-1] + (
            ChatMessage(role="user", content=spliced_content),
        )

    # 4. Dispatch chat ... (unchanged)
```

Mirror the same pattern in `process_message_stream` (line 553).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_loop.py -v`
Expected: PASS (existing tests unaffected; new attachments tests pass).

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/loop.py tests/agents/test_loop.py
git commit -m "agents/loop: add attachments kwarg to process_message{,_stream}

DB stores text-only user turn unchanged. At request-build time the current
user message's content is rewritten to OpenAI vision-format list when
attachments are present. Aetheria-only guard fires before save_turn so
guard rejections don't pollute history."
```

---

## Task 3: `/chat` and `/chat_stream` routes accept `attachments`

**Files:**
- Modify: `soveryn/app/routes/chat.py:132` (`/chat`)
- Modify: `soveryn/app/routes/chat.py:227` (`/chat_stream`)
- Test: `tests/app/routes/test_chat.py`

- [ ] **Step 1: Write failing test**

```python
def test_chat_accepts_attachments_passes_to_loop(client, mock_aetheria_loop):
    """/chat plumbs attachments through to AgentLoop.process_message."""
    img = "data:image/jpeg;base64,AAAA"
    response = client.post("/chat", json={
        "agent": "aetheria",
        "session_id": "<existing aetheria session>",
        "message": "what's this?",
        "attachments": [img],
    })
    assert response.status_code == 200
    assert mock_aetheria_loop.last_call["attachments"] == (img,)


def test_chat_rejects_non_image_data_url():
    """Only data:image/... data URLs accepted."""
    response = client.post("/chat", json={
        "agent": "aetheria",
        "session_id": "<existing>",
        "message": "hi",
        "attachments": ["data:application/pdf;base64,AAAA"],
    })
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_attachments"


def test_chat_rejects_attachments_on_non_aetheria_agent():
    response = client.post("/chat", json={
        "agent": "vett",
        "session_id": "<existing vett>",
        "message": "hi",
        "attachments": ["data:image/jpeg;base64,AAAA"],
    })
    assert response.status_code == 400
    assert response.json["error"]["code"] == "agent_does_not_support_vision"


def test_chat_rejects_oversized_attachment():
    """data: URL > 33MB rejected client-side at the route boundary."""
    big = "data:image/jpeg;base64," + ("A" * 35_000_000)
    response = client.post("/chat", json={
        "agent": "aetheria",
        "session_id": "<existing>",
        "message": "hi",
        "attachments": [big],
    })
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_attachments"
```

Mirror for `/chat_stream`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/app/routes/test_chat.py -v -k "attach"`
Expected: FAIL.

- [ ] **Step 3: Add validation + plumb-through**

`soveryn/app/routes/chat.py`, in both `/chat` and `/chat_stream` handlers, after the existing message validation:

```python
ALLOWED_IMAGE_MIME_PREFIXES = ("data:image/jpeg", "data:image/png",
                                "data:image/webp", "data:image/gif")
MAX_ATTACHMENT_DATA_URL_BYTES = 33_000_000  # ~25MB pre-decode

raw_attachments = body.get("attachments")
attachments: tuple[str, ...] | None = None
if raw_attachments is not None:
    if not isinstance(raw_attachments, list) or not all(
        isinstance(a, str) for a in raw_attachments
    ):
        return _err("invalid_attachments",
                    "attachments must be a list of data: URL strings", 400)
    for a in raw_attachments:
        if not a.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
            return _err("invalid_attachments",
                        "only data:image/{jpeg,png,webp,gif} accepted", 400)
        if len(a) > MAX_ATTACHMENT_DATA_URL_BYTES:
            return _err("invalid_attachments",
                        f"attachment exceeds {MAX_ATTACHMENT_DATA_URL_BYTES} bytes", 400)
    if raw_attachments:
        if agent != "aetheria":
            return _err("agent_does_not_support_vision",
                        f"agent={agent!r} has no vision model loaded", 400)
        attachments = tuple(raw_attachments)
```

Then in the loop call:

```python
response = loop.process_message(session_id, message, attachments=attachments)
```

(and the stream variant accordingly).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/app/routes/test_chat.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/chat.py tests/app/routes/test_chat.py
git commit -m "routes: accept attachments on /chat + /chat_stream

Only data:image/{jpeg,png,webp,gif} accepted. Bounded to ~25MB pre-decode.
Aetheria-only — other agents return 400 agent_does_not_support_vision."
```

---

## Task 4: Signal bridge — inbound image encoding

**Files:**
- Modify: `soveryn/agents/signal_bridge/daemon.py:126` (`_handle_inbound`)
- Modify: `soveryn/agents/signal_bridge/daemon.py:237` (`_call_vnext_chat`)
- Test: `tests/agents/signal_bridge/test_daemon.py`

- [ ] **Step 1: Write failing test**

```python
def test_inbound_image_attachment_encodes_and_passes_to_chat(tmp_path):
    """An image file referenced in InboundMessage.attachment_paths is
    base64-encoded and forwarded to /chat as a data: URL attachment."""
    from soveryn.agents.signal_bridge.daemon import SignalBridgeDaemon
    from soveryn.agents.signal_bridge.client import InboundMessage

    img_path = tmp_path / "photo.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0fake jpeg payload")

    posted = {}
    daemon = SignalBridgeDaemon(_test_config(allowed=["+15555550100"]))
    daemon._post_json = lambda path, body, *, timeout: (
        posted.update({"path": path, "body": body}) or
        {"content": "I see it", "session_id": "sess1"}
    )
    daemon._ensure_session = lambda sender: "sess1"

    msg = InboundMessage(
        source_e164="+15555550100",
        body="check this out",
        attachment_paths=(str(img_path),),
        envelope={},
    )
    daemon._handle_inbound(msg)

    # /chat got attachments parameter with one data:image/jpeg URL
    assert posted["path"] == "/chat"
    assert posted["body"]["message"] == "check this out"
    attachments = posted["body"]["attachments"]
    assert len(attachments) == 1
    assert attachments[0].startswith("data:image/jpeg;base64,")
    # No placeholder line in message body
    assert "vision pipeline integration pending" not in posted["body"]["message"]


def test_inbound_non_image_attachment_keeps_placeholder():
    """A .pdf attachment is logged but kept as a placeholder line in text."""
    # ... similar structure ...
    assert "non-image attachment" in posted["body"]["message"]
    assert posted["body"].get("attachments") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/signal_bridge/test_daemon.py -v -k "attachment"`
Expected: FAIL (daemon currently only emits placeholder text).

- [ ] **Step 3: Encode attachments + drop placeholder for images**

In `signal_bridge/daemon.py`, replace the current attachment-placeholder block in `_handle_inbound` (around line 156-161) with:

```python
_IMAGE_EXT_TO_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}

def _encode_image_attachment(path: Path) -> str | None:
    """Returns data:image/...;base64,... or None if not a supported image."""
    ext = path.suffix.lower()
    mime = _IMAGE_EXT_TO_MIME.get(ext)
    if mime is None:
        return None
    try:
        data = path.read_bytes()
    except (OSError, IOError) as e:
        logger.warning("failed to read attachment %s: %s", path, e)
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
```

Then in `_handle_inbound`:

```python
body = msg.body or ""
image_data_urls: list[str] = []
skipped_count = 0
for raw_path in msg.attachment_paths:
    p = Path(raw_path)
    url = _encode_image_attachment(p)
    if url is None:
        skipped_count += 1
    else:
        image_data_urls.append(url)

if skipped_count > 0:
    body = (body + "\n\n" if body else "") + \
           f"[Signal: {skipped_count} non-image attachment(s) skipped]"
if not body.strip() and not image_data_urls:
    body = "(empty message)"
elif not body.strip():
    body = "(image only)"
```

Modify `_call_vnext_chat` signature:

```python
def _call_vnext_chat(
    self, session_id: str, body: str,
    attachments: tuple[str, ...] = (),
) -> str:
    payload = {"agent": SIGNAL_AGENT, "session_id": session_id, "message": body}
    if attachments:
        payload["attachments"] = list(attachments)
    resp = self._post_json("/chat", payload, timeout=self.config.chat_timeout_seconds)
    return resp.get("content", "") if isinstance(resp, dict) else ""
```

Update the call site in `_handle_inbound`:

```python
response_content = self._call_vnext_chat(
    session_id, body, attachments=tuple(image_data_urls),
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/signal_bridge/test_daemon.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/signal_bridge/daemon.py tests/agents/signal_bridge/test_daemon.py
git commit -m "signal_bridge: encode inbound image attachments as data: URLs

Inbound .jpg/.jpeg/.png/.webp/.gif are base64-encoded and forwarded via
/chat's attachments field. Non-image attachments still surface as a count
hint in the text body."
```

---

## Task 5: Signal client — outbound `-a` flag

**Files:**
- Modify: `soveryn/agents/signal_bridge/client.py` (`send_once`)
- Test: `tests/agents/signal_bridge/test_client.py`

- [ ] **Step 1: Write failing test**

```python
def test_send_once_passes_attachments_as_repeated_a_flags(monkeypatch):
    """signal-cli takes one -a per attachment file path."""
    captured = {}
    def fake_run(args, *, capture_output, text, timeout):
        captured["args"] = args
        return _ok_completed_process()
    monkeypatch.setattr(subprocess, "run", fake_run)

    send_once(
        signal_cli_bin="/usr/bin/signal-cli",
        bot_number="+15555550000",
        recipient_e164="+15555550100",
        body="here you go",
        attachments=("/tmp/a.jpg", "/tmp/b.png"),
    )

    args = captured["args"]
    # Two -a flags appearing back-to-back for attachments (path follows each -a)
    a_indices = [i for i, x in enumerate(args) if x == "-a"]
    # The first -a is signal-cli's --account flag for bot_number. Subsequent
    # -a flags are the attachments. Verify by matching values.
    attached_values = [args[i + 1] for i in a_indices if args[i + 1] not in ("+15555550000",)]
    assert "/tmp/a.jpg" in attached_values
    assert "/tmp/b.png" in attached_values
```

Wait — `signal-cli`'s `-a` flag is overloaded: at the top level it's `--account`, after `send` it's `--attachment`. Verify the actual command syntax with `signal-cli send --help` before finalizing the test:

```bash
signal-cli send --help | head -30
```

The attachment flag is likely `--attachment` (long form) or `-a` (short form, post-subcommand). Use the long form (`--attachment`) for clarity to avoid the account/attachment ambiguity.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/signal_bridge/test_client.py -v -k "attachments"`
Expected: FAIL (send_once has no attachments param yet).

- [ ] **Step 3: Implement**

In `signal_bridge/client.py`'s `send_once`:

```python
def send_once(
    *,
    signal_cli_bin: str,
    bot_number: str,
    recipient_e164: str,
    body: str,
    attachments: tuple[str, ...] = (),
    timeout_seconds: float = 30.0,
) -> None:
    args = [signal_cli_bin, "-a", bot_number, "send", "-m", body]
    for path in attachments:
        args.extend(["--attachment", path])
    args.append(recipient_e164)
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds)
    if result.returncode != 0:
        raise SignalCliError(f"signal-cli send failed: {result.stderr.strip()}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/signal_bridge/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/signal_bridge/client.py tests/agents/signal_bridge/test_client.py
git commit -m "signal_bridge/client: send_once accepts attachments tuple

Each path becomes a --attachment flag on signal-cli send. Long-form to
avoid ambiguity with -a/--account."
```

---

## Task 6: `signal_send` tool — attachments param + path safety

**Files:**
- Modify: `soveryn/agents/signal_bridge/tools.py` (`signal_send` callable + schema)
- Test: `tests/agents/signal_bridge/test_tools.py`

- [ ] **Step 1: Write failing test**

```python
def test_signal_send_accepts_attachment_paths(tmp_path, monkeypatch):
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    sent = {}
    monkeypatch.setattr(
        "soveryn.agents.signal_bridge.tools.send_once",
        lambda **kw: sent.update(kw),
    )
    tool = build_signal_send_tool(config=_test_config(allowed=["+15555550100"]))
    result = tool.execute({
        "recipient": "+15555550100",
        "body": "look at this",
        "attachments": [str(img)],
    })
    assert result["channel"] == "signal"
    assert sent["attachments"] == (str(img),)


def test_signal_send_rejects_relative_path():
    tool = build_signal_send_tool(config=_test_config(allowed=["+15555550100"]))
    result = tool.execute({
        "recipient": "+15555550100",
        "body": "x",
        "attachments": ["relative/path.jpg"],
    })
    assert result["error"]
    assert "absolute" in result["error"].lower()


def test_signal_send_rejects_path_traversal():
    result = tool.execute({
        "recipient": "+15555550100",
        "body": "x",
        "attachments": ["/tmp/../etc/passwd"],
    })
    assert result["error"]
    assert "traversal" in result["error"].lower() or ".." in result["error"]


def test_signal_send_rejects_nonexistent_path():
    result = tool.execute({
        "recipient": "+15555550100",
        "body": "x",
        "attachments": ["/nonexistent/file.jpg"],
    })
    assert result["error"]


def test_signal_send_rejects_oversized_file(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"x" * (17 * 1024 * 1024))  # 17MB > 16MB cap
    result = tool.execute({
        "recipient": "+15555550100",
        "body": "x",
        "attachments": [str(big)],
    })
    assert result["error"]
    assert "16" in result["error"] or "size" in result["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/signal_bridge/test_tools.py -v -k "attachment"`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `signal_bridge/tools.py`, extend `signal_send`'s callable + JSON schema. Add a path-validation helper:

```python
MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024  # signal-cli soft limit

def _validate_attachment_path(raw: str) -> str | None:
    """Returns error message on failure, None on success."""
    if not raw.startswith("/"):
        return f"path must be absolute: {raw!r}"
    if ".." in Path(raw).parts:
        return f"path contains traversal segment: {raw!r}"
    p = Path(raw)
    if not p.exists():
        return f"path does not exist: {raw!r}"
    if not p.is_file():
        return f"path is not a regular file: {raw!r}"
    try:
        size = p.stat().st_size
    except OSError as e:
        return f"cannot stat path: {e}"
    if size > MAX_ATTACHMENT_BYTES:
        return f"file exceeds {MAX_ATTACHMENT_BYTES} bytes ({size} bytes)"
    return None
```

In the tool callable:

```python
attachments_raw = args.get("attachments") or []
if not isinstance(attachments_raw, list):
    return {"error": "attachments must be a list of absolute file paths"}
attachments: list[str] = []
for raw in attachments_raw:
    if not isinstance(raw, str):
        return {"error": f"attachment entry must be a string, got {type(raw).__name__}"}
    err = _validate_attachment_path(raw)
    if err is not None:
        return {"error": err}
    attachments.append(raw)

send_once(
    signal_cli_bin=cfg.signal_cli_bin,
    bot_number=cfg.bot_number,
    recipient_e164=recipient,
    body=body,
    attachments=tuple(attachments),
)
```

And the OpenAI tool schema gains:

```python
"attachments": {
    "type": "array",
    "items": {"type": "string"},
    "description": "Optional absolute file paths to send as Signal "
                   "attachments. Image/video/audio/PDF accepted; max 16MB "
                   "per file. Must be absolute paths with no traversal.",
},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/signal_bridge/test_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/signal_bridge/tools.py tests/agents/signal_bridge/test_tools.py
git commit -m "signal_send: optional attachments param with path validation

Absolute paths only, no traversal, must exist and be readable, capped at
16MB. Schema updated so Aetheria sees the new param via the tool registry."
```

---

## Task 7: UI — composer paperclip + base64 upload

**Files:**
- Modify: `soveryn/app/templates/chat.html` (composer + sent-bubble template)
- Modify: `soveryn/app/static/js/chat.js` (file input handling + POST body)
- Test: manual (UI work)

- [ ] **Step 1: HTML — paperclip button + hidden file input + preview row**

In `chat.html`, near the composer (find by `id="composer"` or equivalent):

```html
<div class="composer-attachments-row" id="composer-attachments" hidden></div>
<div class="composer">
  <button type="button" id="composer-attach-btn"
          class="composer-icon-btn"
          title="Attach image"
          data-agent-restrict="aetheria">📎</button>
  <input type="file" id="composer-file-input"
         accept="image/jpeg,image/png,image/webp,image/gif"
         multiple hidden>
  <textarea id="composer-text" placeholder="..."></textarea>
  <button type="button" id="composer-send-btn">Send</button>
</div>
```

CSS: hide `data-agent-restrict="aetheria"` element when active agent isn't Aetheria (or use existing tab-data-attribute pattern in the file).

- [ ] **Step 2: JS — file selection + preview + base64 POST**

In `chat.js`, after the existing send-handler:

```javascript
const attachBtn = document.getElementById('composer-attach-btn');
const fileInput = document.getElementById('composer-file-input');
const attachmentsRow = document.getElementById('composer-attachments');
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_FILES = 4;

let pendingAttachments = []; // {file, dataUrl}

attachBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', async (evt) => {
  const files = Array.from(evt.target.files || []);
  if (pendingAttachments.length + files.length > MAX_FILES) {
    alert(`Max ${MAX_FILES} attachments per message`);
    return;
  }
  for (const file of files) {
    if (file.size > MAX_FILE_BYTES) {
      alert(`${file.name} exceeds 16MB`);
      continue;
    }
    const dataUrl = await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result);
      r.onerror = reject;
      r.readAsDataURL(file);
    });
    pendingAttachments.push({file, dataUrl});
  }
  renderAttachmentsRow();
  fileInput.value = '';
});

function renderAttachmentsRow() {
  if (pendingAttachments.length === 0) {
    attachmentsRow.hidden = true;
    attachmentsRow.innerHTML = '';
    return;
  }
  attachmentsRow.hidden = false;
  attachmentsRow.innerHTML = pendingAttachments
    .map((att, idx) => `
      <div class="composer-attachment-thumb">
        <img src="${att.dataUrl}" alt="">
        <button type="button" class="remove-attachment" data-idx="${idx}">×</button>
      </div>
    `).join('');
  attachmentsRow.querySelectorAll('.remove-attachment').forEach(btn => {
    btn.addEventListener('click', () => {
      pendingAttachments.splice(parseInt(btn.dataset.idx, 10), 1);
      renderAttachmentsRow();
    });
  });
}

// In the existing send handler, include attachments in the POST body:
const body = {
  agent: currentAgent,
  session_id: currentSessionId,
  message: text,
};
if (pendingAttachments.length > 0) {
  body.attachments = pendingAttachments.map(a => a.dataUrl);
}
// ... existing fetch('/chat_stream', {body: JSON.stringify(body), ...})
// On successful send, clear:
pendingAttachments = [];
renderAttachmentsRow();
```

- [ ] **Step 3: Sent bubble shows inline image**

In the message-rendering function (find by `renderUserMessage` or equivalent), if the user turn had attachments locally, inline-render them above the text. Since DB doesn't persist attachments, this is in-memory only for the current session — the next reload won't show them. Acceptable v1.

```javascript
function renderUserBubble(text, attachments) {
  const bubble = document.createElement('div');
  bubble.className = 'message user';
  if (attachments && attachments.length) {
    const imgRow = document.createElement('div');
    imgRow.className = 'message-attachments';
    for (const url of attachments) {
      const img = document.createElement('img');
      img.src = url;
      img.className = 'message-thumb';
      imgRow.appendChild(img);
    }
    bubble.appendChild(imgRow);
  }
  const txt = document.createElement('div');
  txt.className = 'message-text';
  txt.textContent = text;
  bubble.appendChild(txt);
  return bubble;
}
```

- [ ] **Step 4: CSS — palette-matched styling**

Append to existing chat.css (or inline in chat.html):

```css
.composer-attachments-row {
  display: flex; gap: 6px; padding: 6px 12px;
  border-bottom: 1px solid rgba(140, 145, 100, 0.2);
}
.composer-attachment-thumb {
  position: relative; width: 64px; height: 64px;
  border-radius: 4px; overflow: hidden;
  border: 1px solid rgba(140, 145, 100, 0.4);
}
.composer-attachment-thumb img { width: 100%; height: 100%; object-fit: cover; }
.composer-attachment-thumb .remove-attachment {
  position: absolute; top: 2px; right: 2px;
  width: 18px; height: 18px; line-height: 16px;
  border: 0; background: rgba(0,0,0,0.6); color: white;
  border-radius: 50%; cursor: pointer; font-size: 12px;
}
.composer-icon-btn {
  background: transparent; border: 0; font-size: 18px;
  cursor: pointer; opacity: 0.75; padding: 6px;
}
.composer-icon-btn:hover { opacity: 1; }
.message-attachments { display: flex; gap: 4px; margin-bottom: 4px; }
.message-thumb { max-width: 200px; border-radius: 6px; }
```

- [ ] **Step 5: Verify in browser (manual)**

Open http://localhost:5001/chat?agent=aetheria, click 📎, select an image, see preview, click Send, see image in the sent bubble + receive Aetheria's vision response.

If working: commit.

- [ ] **Step 6: Commit**

```bash
git add soveryn/app/templates/chat.html soveryn/app/static/js/chat.js soveryn/app/static/css/chat.css
git commit -m "ui: composer image upload + sent-bubble inline preview

Paperclip-triggered file input, in-memory base64 encoding, up to 4 files
per message at 16MB each, Aetheria-only (other agents hide the button)."
```

---

## Task 8: End-to-end manual verification

**Files:**
- Test: human-in-the-loop

- [ ] **Step 1: Signal inbound photo round-trip**

  1. From Jon's phone, send a photo to +19102489392 with caption "what do you see?"
  2. Watch /tmp/soveryn-signal-bridge.log: confirm the message logs as inbound with attachment_count=1.
  3. Confirm /tmp/soveryn-vnext.log shows `POST /chat` with attachments field present.
  4. Confirm Aetheria's reply (in DB + arriving on phone) describes the photo content.

- [ ] **Step 2: Signal outbound — Aetheria sends a photo**

  Direct her in a chat: "Send +<jon's number> the dream-daemon spec image. The PNG is at /tmp/dream-daemon-flow.png" (or any pre-existing local PNG).
  Expected: she calls `signal_send` with attachments=[path], Jon receives the image on phone.

- [ ] **Step 3: UI image upload**

  In her chat tab, click 📎, attach an image, send "what do you see?".
  Expected: image preview shows pre-send, sent bubble shows the inline image, Aetheria responds with vision content.

- [ ] **Step 4: Negative paths**

  - Try uploading a non-image (PDF) — should be filtered by accept attribute on the file input.
  - Try sending attachments from the Vett tab — paperclip should be hidden.
  - Try calling /chat with `attachments` on Vett's session via curl — should 400.

- [ ] **Step 5: Update memory + handoff**

  Save a project memory documenting:
  - Aetheria has vision across all three surfaces as of this date
  - mmproj is the gate; only Aetheria has one loaded
  - Multimodal history persistence is deferred (live-only)
