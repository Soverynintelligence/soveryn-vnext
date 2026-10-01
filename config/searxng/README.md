# SearXNG (house)

Canonical **non-secret** settings for `soveryn-searxng.service` (`127.0.0.1:8095`).

- **Brave** default (2026-08-30). Bing kept enabled as fallback; Wikipedia off — it was dictionary-first.
- **LIVE mount (2026-09-24):** `~/.config/soveryn/searxng/` — the container chowns its config dir to uid 977, so the live dir was moved OUT of the repo tree (git operations here collided with it and blocked a delegation merge twice). This directory holds tracked templates; copy edits to the live dir, then `systemctl --user restart soveryn-searxng.service`.
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

Note: the container may chown this folder to uid 977 while running. Reclaim without
host sudo: `docker exec soveryn-searxng chown -R 1000:1000 /etc/searxng` (or
`chown -R $(id -u):$(id -g) config/searxng` if you have sudo). Then edit.
