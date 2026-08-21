"""Tool registration for house document intake."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.intake.pdf import extract_pdf_path
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec

# Paths agents may read for intake (house-local only).
_DEFAULT_ALLOWED_ROOTS: tuple[Path, ...] = (
    Path.home() / "soveryn_vnext" / "data",
    Path.home() / "soveryn_citizens",
    Path.home() / "historys-ledger",
    Path.home() / "historysledger-site",
    Path.home() / "Downloads",
)


def _resolve_allowed(path: Path, allowed_roots: tuple[Path, ...]) -> Path:
    resolved = path.expanduser().resolve()
    for root in allowed_roots:
        try:
            root_r = root.expanduser().resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root_r)
            return resolved
        except ValueError:
            continue
    raise ToolArgError(
        f"path {path} is outside allowed intake roots "
        f"(house data, citizens desks, History's Ledger, Downloads)"
    )


def build_intake_extract_pdf_tool(
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
) -> ToolSpec:
    roots = allowed_roots if allowed_roots is not None else _DEFAULT_ALLOWED_ROOTS

    def handler(args: Mapping[str, Any]) -> Any:
        raw = args.get("path", "")
        if not isinstance(raw, str) or not raw.strip():
            raise ToolArgError("path must be a non-empty string")
        resolved = _resolve_allowed(Path(raw.strip()), roots)
        if resolved.suffix.lower() != ".pdf":
            raise ToolArgError("intake_extract_pdf only accepts .pdf files in v0")
        result = extract_pdf_path(resolved)
        return result.as_dict()

    return ToolSpec(
        name="intake_extract_pdf",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to a PDF on the house disk "
                        "(data/, citizens desks, History's Ledger, or Downloads). "
                        "Returns extracted text + page map. status=failed|partial "
                        "with an explicit gap when there is no text layer — "
                        "never invent page content."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Extract text from a held PDF (text layer only in v0). "
            "Use when Jon attaches or points at a PDF. If status is failed "
            "(scan/encrypted/empty), report the gap — do not invent quotations."
        ),
    )


def register_intake_tools(
    registry: ToolRegistry,
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
) -> None:
    """Register intake tools for one agent."""
    registry.register(
        build_intake_extract_pdf_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
        )
    )
