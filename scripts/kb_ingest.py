#!/usr/bin/env python3
"""Manual reference-KB ingest. Does not touch the lattice.

    python -m scripts.kb_ingest
    python -m scripts.kb_ingest --root docs --root soveryn/platform/pondwright

Chunks markdown/txt, embeds via the same embed_text() path as the lattice,
writes data/kb/turbovec.idx + chunks.db.
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
        help="Directory to walk (repeatable). Default: docs/",
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

    from soveryn.platform.kb.chunk import chunk_markdown, iter_doc_files
    from soveryn.platform.kb.store import KBStore, default_kb_dir
    from soveryn.platform.lattice.legacy import embed_text

    roots = [Path(r) for r in (args.root or ["docs"])]
    kb_dir = Path(args.kb_dir) if args.kb_dir else default_kb_dir()
    files: list[Path] = []
    for root in roots:
        files.extend(iter_doc_files(ROOT / root if not Path(root).is_absolute() else root))

    planned: list[tuple[str, str, str]] = []
    for path in files:
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for chunk_id, body in chunk_markdown(text, source_path=rel):
            planned.append((chunk_id, body, rel))

    print(f"kb_ingest: {len(files)} files, {len(planned)} chunks")
    if args.dry_run:
        for chunk_id, body, _rel in planned[:8]:
            print(f"  {chunk_id}  {len(body)} chars")
        if len(planned) > 8:
            print(f"  … {len(planned) - 8} more")
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
