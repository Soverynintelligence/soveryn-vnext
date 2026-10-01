#!/usr/bin/env python3
"""Minimal OpenAI-style tool loop with ActTruth — no API key required.

Simulates a tool that fails twice (timeout), then shows the soft lesson
and a proof-style recall brief.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from acttruth import ActTruth
from acttruth.openai_tools import inject_lessons_message, record_openai_tool_result
from acttruth.paths import set_default_root


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="acttruth-demo-"))
    set_default_root(root)
    at = ActTruth.open(root)

    messages: list[dict] = [
        {"role": "user", "content": "Generate a cosmic brain image."},
    ]

    def fake_generate_image(prompt: str) -> dict:
        return {"error": "ComfyUI generation timed out after 180s"}

    for i in range(3):
        result = fake_generate_image("cosmic brain")
        lesson = record_openai_tool_result(
            agent="demo",
            tool_name="generate_image",
            arguments={"prompt": "cosmic brain"},
            result=result,
            acttruth=at,
        )
        print(f"call {i + 1}: result={result!r}")
        if lesson:
            print(f"  soft lesson → {lesson}")

    inject_lessons_message(messages, "demo")
    print("\n--- messages after inject ---")
    for m in messages:
        print(m["role"], ":", str(m["content"])[:240])

    print("\n--- recall brief ---")
    print(at.ledger.recall_brief("demo") or "(empty)")
    print(f"\nledger root: {root}")


if __name__ == "__main__":
    main()
