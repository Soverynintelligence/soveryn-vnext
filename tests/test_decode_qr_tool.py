"""Tests for Eve's decode_qr desk tool."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from soveryn.platform.intake.qr import decode_qr_bytes
from soveryn.platform.intake.tools import build_decode_qr_tool, register_qr_tools
from soveryn.platform.intake.turn_images import turn_images_bound
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


PAYLOAD = "https://soveryn.example/qr-desk-test"


def _make_qr_png(payload: str) -> bytes:
    enc = cv2.QRCodeEncoder.create()
    img = enc.encode(payload)
    img = cv2.copyMakeBorder(img, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    img = cv2.resize(
        img,
        (img.shape[1] * 10, img.shape[0] * 10),
        interpolation=cv2.INTER_NEAREST,
    )
    ok, buf = cv2.imencode(".png", img)
    assert ok, "cv2.imencode failed"
    return buf.tobytes()


def _make_blank_png() -> bytes:
    img = np.full((160, 160, 3), 180, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _tool(tmp_path: Path):
    return build_decode_qr_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
    )


def test_decode_qr_bytes_reads_generated_code():
    png = _make_qr_png(PAYLOAD)
    result = decode_qr_bytes(png)
    assert result.ok is True
    assert result.miss is None
    assert result.symbology == "QR"
    assert PAYLOAD in result.payloads


def test_decode_qr_bytes_no_code_image():
    result = decode_qr_bytes(_make_blank_png())
    assert result.ok is False
    assert result.payloads == ()
    assert result.miss == "no_code_found"
    assert result.symbology is None


def test_tool_decodes_path_under_allowed_root(tmp_path):
    png = _make_qr_png(PAYLOAD)
    path = tmp_path / "jon-qr.png"
    path.write_bytes(png)
    result = _tool(tmp_path).handler({"path": str(path)})
    assert result["ok"] is True
    assert result["miss"] is None
    assert result["symbology"] == "QR"
    assert PAYLOAD in result["payloads"]


def test_tool_no_code_image_is_explicit_miss(tmp_path):
    path = tmp_path / "blank.png"
    path.write_bytes(_make_blank_png())
    result = _tool(tmp_path).handler({"path": str(path)})
    assert result["ok"] is False
    assert result["payloads"] == []
    assert result["miss"] == "no_code_found"


def test_tool_path_outside_roots_rejected(tmp_path):
    outside = Path("/etc/hostname")
    if not outside.is_file():
        outside = Path("/etc/passwd")
    tool = _tool(tmp_path)
    with pytest.raises(ToolArgError, match="outside allowed intake roots"):
        tool.handler({"path": str(outside)})


def test_tool_decodes_in_flight_data_url_via_current(tmp_path):
    url = _data_url(_make_qr_png(PAYLOAD))
    tool = _tool(tmp_path)
    with turn_images_bound((url,)):
        result = tool.handler({"image": "current"})
    assert result["ok"] is True
    assert PAYLOAD in result["payloads"]
    assert result["symbology"] == "QR"


def test_tool_omitted_args_use_in_flight_attachment(tmp_path):
    url = _data_url(_make_qr_png(PAYLOAD))
    tool = _tool(tmp_path)
    with turn_images_bound((url,)):
        result = tool.handler({})
    assert result["ok"] is True
    assert PAYLOAD in result["payloads"]


def test_tool_current_without_in_flight_is_explicit_miss(tmp_path):
    result = _tool(tmp_path).handler({"image": "current"})
    assert result["ok"] is False
    assert result["payloads"] == []
    assert result["miss"] == "no_in_flight_image"


def test_tool_never_invents_payload_on_blank_data_url(tmp_path):
    url = _data_url(_make_blank_png())
    result = _tool(tmp_path).handler({"image": url})
    assert result["ok"] is False
    assert result["payloads"] == []
    assert result["miss"] == "no_code_found"


def test_register_qr_tools_eve_only():
    reg = ToolRegistry(
        active_agents=("eve", "kernel", "aetheria"),
        audit_hook=lambda _e: None,
    )
    register_qr_tools(reg, owner_agent="eve")
    eve = {t.name for t in reg.iter_tools_for_agent("eve")}
    kernel = {t.name for t in reg.iter_tools_for_agent("kernel")}
    aetheria = {t.name for t in reg.iter_tools_for_agent("aetheria")}
    assert {"decode_qr", "make_qr", "compose_image"} <= eve
    assert "decode_qr" not in kernel
    assert "make_qr" not in kernel
    assert "compose_image" not in kernel
    assert "decode_qr" not in aetheria


def test_loop_in_flight_attachment_reaches_decode_qr(tmp_path):
    """A Messages-style turn: image is in-flight only; decode_qr(image=current)."""
    from soveryn.agents.loop import AgentLoop
    from soveryn.memory.conversation_store import ConversationStore
    from soveryn.platform.inference.llama_server_client import ChatResponse

    png_url = _data_url(_make_qr_png(PAYLOAD))
    reg = ToolRegistry(active_agents=("aetheria",), audit_hook=lambda _e: None)
    reg.register(
        build_decode_qr_tool(owner_agent="aetheria", allowed_roots=(tmp_path,))
    )

    def _tool_call(call_id, name, args_obj):
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args_obj)},
        }

    class _Scripted:
        def __init__(self):
            self.calls = []
            self._responses = [
                ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=(_tool_call("c1", "decode_qr", {"image": "current"}),),
                    usage={},
                    raw={},
                ),
                ChatResponse(
                    content="payload from tool",
                    finish_reason="stop",
                    tool_calls=None,
                    usage={},
                    raw={},
                ),
            ]

        def __call__(self, request, server, timeout=60.0):
            self.calls.append(request)
            return self._responses.pop(0)

    store = ConversationStore(tmp_path / "conv.db")
    sid = store.new_session("aetheria")
    fake = _Scripted()
    loop = AgentLoop(
        "aetheria",
        store,
        chat_fn=fake,
        tool_registry=reg,
        system_prompt="",
    )
    response = loop.process_message(
        sid, "decode this QR", attachments=(png_url,),
    )
    tool_msgs = [m for m in fake.calls[1].messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    body = json.loads(tool_msgs[0].content)
    assert body["ok"] is True
    assert PAYLOAD in body["payloads"]
    assert response.content == "payload from tool"
    # In-flight only — DB row is text, no data URL persisted.
    history = store.load_history(sid)
    user_rows = [t for t in history if t.role == "user"]
    assert all("data:image" not in (t.content or "") for t in user_rows)
