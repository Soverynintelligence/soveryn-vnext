"""SOVERYN vNext — conversation and session persistence.

SQLite-backed store for conversation history, tool call logs, and session
identity. Backs the /chat_stream session-minting flow so conversations survive
restarts. Wraps soveryn_memory/persistent.db and soveryn_memory/conversations.db.
Placeholder; implementation comes in a later vNext step.
"""
