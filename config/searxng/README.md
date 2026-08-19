# SearXNG (house)

Canonical settings for `soveryn-searxng.service` (`127.0.0.1:8095`).

- **Bing + Wikipedia** enabled by default (2026-08-19) after DDG/Brave CAPTCHA storms
- Mounted into the container at `/etc/searxng` from this directory
- Client default engines also set in `soveryn/platform/web/search.py` (`DEFAULT_ENGINES`)

Restart after edits:

```bash
systemctl --user restart soveryn-searxng.service
```

Note: the container may chown this folder to uid 977 while running; reclaim with
`chown -R $(id -u):$(id -g) config/searxng` (or alpine docker) before editing.
