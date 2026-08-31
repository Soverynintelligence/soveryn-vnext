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
