# Secrets & operator state — backup / restore

**Kill-list #2 (Critic 2026-08-24).**  
Not in git. Must survive tower death.

## What must be restorable

| Item | Live path | In nightly? |
|------|-----------|-------------|
| SOVERYN env (incl. Canva client id/secret) | `~/soveryn_vnext/.env` | **Yes** → `backups/DATE/secrets/soveryn_vnext.env` (added 2026-08-24) |
| Canva OAuth tokens | `data/canva/tokens.json` | Yes (`data/canva/` + secrets copy) |
| Eve live persona | `data/memory/personas/eve.md` | Yes |
| Teammates env | `~/teammates/.env` | **Yes** → `secrets/teammates.env` |
| Teammates roster | `~/teammates/roster.toml` | Yes (also in git; bundled for convenience) |
| SQLite DBs / souls | under `data/` | Yes (longstanding) |

Off-box: rsync to **`/mnt/easystore/soveryn_backups/`** when easystore is mounted (cron 04:00). Missing mirror **alerts Signal** — do not ignore.

## Nightly job

```bash
# crontab
0 4 * * * /home/jon-deoliveira/soveryn_vnext/scripts/backup_soveryn.sh \
  >> /home/jon-deoliveira/soveryn_vnext/logs/backup.log 2>&1 \
  || /home/jon-deoliveira/soveryn_vnext/scripts/alert_signal.sh "Backup failed…"
```

Manual:

```bash
~/soveryn_vnext/scripts/backup_soveryn.sh
```

## Restore drill (safe — scratch only)

```bash
~/soveryn_vnext/scripts/restore_secrets_drill.sh
# or pin a day:
~/soveryn_vnext/scripts/restore_secrets_drill.sh ~/soveryn_vnext/backups/2026-08-24
```

Must print `✓ PASS`. Run after any change to the secrets list.

## Real restore (new tower / wiped disk)

1. Mount easystore (or copy latest `backups/DATE` onto the box).
2. Restore code from git (`soveryn_vnext`, `teammates`).
3. Apply secrets:

```bash
SNAP=/mnt/easystore/soveryn_backups/YYYY-MM-DD   # or local backups/

cp "$SNAP/secrets/soveryn_vnext.env" ~/soveryn_vnext/.env && chmod 600 ~/soveryn_vnext/.env
mkdir -p ~/soveryn_vnext/data/canva ~/soveryn_vnext/data/memory/personas
cp "$SNAP/secrets/canva_tokens.json" ~/soveryn_vnext/data/canva/tokens.json && chmod 600 $_
cp "$SNAP/secrets/eve_persona.md" ~/soveryn_vnext/data/memory/personas/eve.md
cp "$SNAP/secrets/teammates.env" ~/teammates/.env && chmod 600 ~/teammates/.env
# optional: rsync DB tree from $SNAP/data/ if rebuilding memory
```

4. `systemctl --user restart soveryn-vnext teammates-console`
5. Smoke: `python -m soveryn.platform.canva status` → configured+authorized; open `:5075`.

## Rules

- Never commit `secrets/` or `.env` to git.
- Bundle files are mode **600**.
- Local keep ~7 days; easystore is the archive (no `--delete` on rsync).
- If Signal says “easystore not mounted” — plug it in; local-only is not enough.
