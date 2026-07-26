"""Vett's own tool surface.

Distinct from the cross-agent platform tools (web_search/fetch_url,
library, coordination) — these are tools only Vett gets, scoped to his
patrol workflow.
"""

from soveryn.agents.vett.tools.patrol_sources import (
    build_mark_source_visited_tool,
    build_read_patrol_sources_tool,
    register_vett_patrol_tools,
)
from soveryn.agents.vett.tools.pdf import (
    build_convert_to_pdf_tool,
    build_read_pdf_tool,
    build_pdf_to_editable_doc_tool,
    register_vett_pdf_tools,
)
from soveryn.agents.vett.tools.git import (
    build_git_status_tool,
    build_git_log_tool,
    build_git_diff_tool,
    register_vett_git_tools,
)


__all__ = [
    "build_mark_source_visited_tool",
    "build_read_patrol_sources_tool",
    "register_vett_patrol_tools",
    "build_convert_to_pdf_tool",
    "build_read_pdf_tool",
    "build_pdf_to_editable_doc_tool",
    "register_vett_pdf_tools",
    "build_git_status_tool",
    "build_git_log_tool",
    "build_git_diff_tool",
    "register_vett_git_tools",
]
