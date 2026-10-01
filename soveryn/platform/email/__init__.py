"""House email connector — optional SMTP send + IMAP list + citizen identities."""

from soveryn.platform.email.identities import (
    allowed_from_addresses,
    board_identities,
    resolve_from_address,
)
from soveryn.platform.email.tools import register_email_tools

__all__ = [
    "register_email_tools",
    "resolve_from_address",
    "allowed_from_addresses",
    "board_identities",
]
