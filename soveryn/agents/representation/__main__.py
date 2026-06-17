"""Entry point: `python -m soveryn.agents.representation` starts the daemon.

Mirrors soveryn/agents/dream/__main__.py / daemon.py pattern:
  - config from_env(os.environ)
  - LatticeStore + ConversationStore at well-known default paths
  - real embed_fn wired to embed_text (calls nomic-embed server at :8086)
  - daemon.run() blocks until SIGTERM/SIGINT
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.daemon import RepresentationDaemon
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore

logger = logging.getLogger(__name__)

DEFAULT_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
DEFAULT_CONV_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = RepresentationConfig.from_env(dict(os.environ))

    lattice_db = Path(os.environ.get("SOVERYN_LATTICE_DB", DEFAULT_LATTICE_DB))
    conv_db = Path(os.environ.get("SOVERYN_CONV_DB", DEFAULT_CONV_DB))

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    # embed_fn: wire to the app's standard nomic-embed helper (calls :8086).
    # embed_text does a lazy import of the inference client so importing this
    # module is safe even when the embeddings server is not running; the error
    # surfaces only when the daemon tries to embed a conclusion node.
    try:
        from soveryn.memory.lattice import embed_text as _embed_fn
        embed_fn = _embed_fn
        logger.info("representation daemon: embed_fn wired to embed_text (nomic-embed :8086)")
    except ImportError:
        embed_fn = None
        logger.warning(
            "representation daemon: could not import embed_text — embed_fn=None. "
            "Conclusion nodes will be written without embeddings."
        )

    daemon = RepresentationDaemon(
        conv_store=conv_store,
        lattice_store=lattice_store,
        chat_fn=None,   # uses _default_chat_fn (cognition surface) inside cognition.py
        embed_fn=embed_fn,
        config=config,
    )

    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
