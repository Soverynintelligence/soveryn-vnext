#!/usr/bin/env python3
"""CX-7 only: 10.10.10.1:8091 → 127.0.0.1:8091 (Quadro llama-server).

Public Spark agents bind loopback on Spark; they call the tower Qwen 3.8
over the fabric. Do not bind 0.0.0.0 — that would publish :8091 on LAN/WAN.
"""
from __future__ import annotations

import select
import socket
import threading

LISTEN = ("10.10.10.1", 8091)
DEST = ("127.0.0.1", 8091)
BUF = 256 * 1024


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(BUF)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(client: socket.socket) -> None:
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        upstream.settimeout(10)
        upstream.connect(DEST)
        upstream.settimeout(None)
        client.settimeout(None)
        t1 = threading.Thread(target=_pipe, args=(client, upstream), daemon=True)
        t2 = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except OSError:
        pass
    finally:
        for s in (client, upstream):
            try:
                s.close()
            except OSError:
                pass


def main() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(128)
    while True:
        client, _ = srv.accept()
        threading.Thread(target=_handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
