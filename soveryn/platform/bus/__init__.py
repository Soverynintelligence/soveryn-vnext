"""Durable event bus boundary for inter-agent communication.

The intended implementation is a SQLite-WAL event log with cursor-based polling.
Agents publish and subscribe to events instead of sharing in-process state.
"""

