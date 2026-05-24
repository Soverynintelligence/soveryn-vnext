"""SOVERYN vNext — concrete tool implementations.

Each tool is a self-contained module. Tools shared by all agents live here
directly; agent-specific tools are named <agent>_<tool>.py. Tool consolidation
note: the legacy crawl cluster (crawl_tool, crawl4ai_tool, smart_crawl_tool,
browser_tool, web_fetch_tool) is reimplemented as a single tool with a
mode parameter (spec §10 Bucket C). Placeholder; implementations come in
later vNext steps.
"""
