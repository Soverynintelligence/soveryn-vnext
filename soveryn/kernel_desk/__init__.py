"""Kernel desk — one Pi session shared by the Desk UI and the SOVERYN CLI.

The Pi JSONL session file *is* the thread. A lease file next to the sessions
enforces a single writer (Pi documents no locking of its own).
"""
