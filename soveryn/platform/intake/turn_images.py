"""Turn-scoped in-flight image attachments for desk tools.

Vision attachments live on the current chat turn only (AgentLoop splices
them onto the wire message; they are not saved to the conversations DB).
This ContextVar is the house pattern for making that in-flight data
reachable to a tool without dumping a multi-megabyte data URL into the
model's tool-call JSON.

Set by AgentLoop around each tool invoke. Tools read it when the caller
passes image=\"current\".
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from collections.abc import Iterator

in_flight_images: ContextVar[tuple[str, ...]] = ContextVar(
    "intake_in_flight_images", default=(),
)

# Tool results may attach thumbnails for the *next* model round (look_at).
# Queued separately from in_flight_images so a look_at call does not dump
# megabyte data URLs into the tool JSON the model reads.
_queued_tool_vision: ContextVar[tuple[str, ...]] = ContextVar(
    "intake_queued_tool_vision", default=(),
)


def bind_turn_images(urls: tuple[str, ...] | None) -> Token:
    return in_flight_images.set(tuple(urls) if urls else ())


def reset_turn_images(token: Token) -> None:
    in_flight_images.reset(token)


def current_turn_images() -> tuple[str, ...]:
    return in_flight_images.get()


@contextmanager
def turn_images_bound(urls: tuple[str, ...] | None) -> Iterator[None]:
    token = bind_turn_images(urls)
    try:
        yield
    finally:
        reset_turn_images(token)


def pop_tool_vision(result: object) -> tuple[object, tuple[str, ...]]:
    """Strip `_vision` data URLs from a tool payload. Bytes stay off the JSON."""
    if not isinstance(result, dict):
        return result, ()
    raw = result.get("_vision")
    if not raw:
        return result, ()
    if isinstance(raw, str):
        seq: tuple[object, ...] = (raw,)
    elif isinstance(raw, (list, tuple)):
        seq = tuple(raw)
    else:
        seq = ()
    urls = tuple(
        u for u in seq
        if isinstance(u, str) and u.startswith("data:image/")
    )
    stripped = {k: v for k, v in result.items() if k != "_vision"}
    return stripped, urls


def queue_tool_vision(urls: tuple[str, ...]) -> None:
    if not urls:
        return
    _queued_tool_vision.set(_queued_tool_vision.get() + urls)


def take_queued_tool_vision() -> tuple[str, ...]:
    urls = _queued_tool_vision.get()
    if urls:
        _queued_tool_vision.set(())
    return urls
