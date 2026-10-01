"""The Cathedral's public face — for sharing, not for living in.

Same galaxy, same live lattice, one difference: the words stay home. Star
positions, colors, connections, and counts go out; memory text is stripped
at this server, and the page shows a notice instead of the moment when a
star is clicked. Jon's private view stays on the house app (:5001).

Runs on 127.0.0.1:18810. The pondwright Cloudflare tunnel fronts it.
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import Flask, Response, abort, jsonify, send_file

from soveryn.app.routes.api_cathedral import build_cathedral_data

_REPO = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO / "soveryn" / "app" / "templates" / "cathedral.html"
_OG_IMAGE = _REPO / "soveryn" / "app" / "public_assets" / "cathedral-og.png"

_PUBLIC_URL = "https://cathedral.soverynintelligence.com"

app = Flask("cathedral_public")


@app.get("/og.png")
def og_image() -> Response:
    if not _OG_IMAGE.is_file():
        abort(404)
    return send_file(_OG_IMAGE, mimetype="image/png", max_age=3600)


@app.get("/api/cathedral/data")
def public_data() -> Response:
    data = build_cathedral_data()
    if data.get("ok"):
        for node in data.get("nodes", []):
            node["text"] = ""
        for lm in data.get("landmarks", []):
            lm["text"] = ""
    return jsonify(data)


@app.get("/cathedral")
@app.get("/")
def page() -> Response:
    if not _TEMPLATE.is_file():
        abort(404)
    html = _TEMPLATE.read_text(encoding="utf-8")
    og = (
        '<meta property="og:title" content="Everything We Remember — a self-portrait of SOVERYN">\n'
        '<meta property="og:description" content="Every star is a real memory. '
        f'{_count_line()} The four suns are the ones who said it.">\n'
        f'<meta property="og:image" content="{_PUBLIC_URL}/og.png">\n'
        '<meta property="og:type" content="website">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<script>window.CATHEDRAL_PUBLIC = true;</script>\n'
    )
    # Inject OG tags + public flag; the private page keeps a clean head.
    html = html.replace("</head>", og + "</head>", 1)
    return Response(html, mimetype="text/html")


def _count_line() -> str:
    try:
        data = build_cathedral_data()
        meta = data.get("meta", {})
        return f"{meta.get('node_count', '?')} of them and counting."
    except Exception:
        return ""


# Everything else is the house's business, not the internet's.
@app.before_request
def _only_known_paths():
    from flask import request

    if request.path not in ("/", "/cathedral", "/api/cathedral/data", "/og.png"):
        abort(404)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=18810, debug=False)
