#!/usr/bin/env python3
"""Ingest the intake drop-folder into the reference KB. Does not touch the lattice.

    python -m scripts.kb_ingest
    python -m scripts.kb_ingest --root docs --root soveryn/platform/pondwright

Default walk is data/intake/ (md/txt/pdf text layer). Extra --root dirs are
additive. Embeds via the same embed_text() path as the lattice, writes
data/kb/turbovec.idx + chunks.db.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="Extra directory to walk (repeatable). Default always includes data/intake/",
    )
    parser.add_argument(
        "--kb-dir",
        default=None,
        help="Override data/kb path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk only; do not embed or write",
    )
    args = parser.parse_args(argv)

    from soveryn.platform.kb.chunk import chunk_markdown, iter_doc_files, read_doc_text
    from soveryn.platform.kb.store import KBStore, default_intake_dir, default_kb_dir
    from soveryn.platform.lattice.legacy import embed_text

    intake = default_intake_dir()
    roots: list[Path] = [intake]
    for raw in args.root:
        p = Path(raw)
        roots.append(p if p.is_absolute() else ROOT / p)

    kb_dir = Path(args.kb_dir) if args.kb_dir else default_kb_dir()
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for path in iter_doc_files(root):
            if path.name.lower() == "readme.md" and path.parent.name == "intake":
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)

    planned: list[tuple[str, str, str]] = []
    skipped_empty = 0
    for path in files:
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        text = read_doc_text(path)
        if not text.strip():
            skipped_empty += 1
            continue
        for chunk_id, body in chunk_markdown(text, source_path=rel):
            planned.append((chunk_id, body, rel))

    print(
        f"kb_ingest: {len(files)} files, {len(planned)} chunks"
        + (f", {skipped_empty} empty" if skipped_empty else "")
    )
    if args.dry_run:
        for chunk_id, body, _rel in planned[:8]:
            print(f"  {chunk_id}  {len(body)} chars")
        if len(planned) > 8:
            print(f"  … {len(planned) - 8} more")
        return 0

    if not planned:
        print("kb_ingest: nothing to embed (drop md/txt/pdf into data/intake/)")
        return 0

    store = KBStore(kb_dir)
    for i, (chunk_id, body, rel) in enumerate(planned, 1):
        vec = embed_text(body, prompt="document")
        store.add(chunk_id, vec, body, source_path=rel, metadata={"kind": "doc"})
        if i % 25 == 0 or i == len(planned):
            print(f"  embedded {i}/{len(planned)}")
    path = store.sync()
    print(f"kb_ingest: synced {len(store)} chunks → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
