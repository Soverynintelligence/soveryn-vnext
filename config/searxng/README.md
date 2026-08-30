# SearXNG (house)

Canonical **non-secret** settings for `soveryn-searxng.service` (`127.0.0.1:8095`).

- **Brave** default (2026-08-30). Bing kept enabled as fallback; Wikipedia off — it was dictionary-first.
- Mounted into the container at `/etc/searxng` from this directory
- Client default engines also set in `soveryn/platform/web/search.py` (`DEFAULT_ENGINES`)

## Secret key (do not commit)

```bash
mkdir -p ~/.config/soveryn
python3 -c 'import secrets; print("SEARXNG_SECRET_KEY="+secrets.token_hex(32))' \
  > ~/.config/soveryn/searxng.env
chmod 600 ~/.config/soveryn/searxng.env
systemctl --user daemon-reload
systemctl --user restart soveryn-searxng.service
```

The unit passes `SEARXNG_SECRET_KEY` into the container. Never put the real key in
`settings.yml` — `soveryn-vnext` is a **public** GitHub repo.

## Restart after engine edits

```bash
systemctl --user restart soveryn-searxng.service
```

Note: the container may chown this folder to uid 977 while running; reclaim with
`chown -R $(id -u):$(id -g) config/searxng` before editing.
