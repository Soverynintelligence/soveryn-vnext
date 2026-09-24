# Incident / rollback — YYYY-MM-DD — short title

Copy this file to `docs/notes/YYYY-MM-DD-<slug>.md`. Notes are **not** authority; after recovery, update `docs/CURRENT_TRUTH.md` if live state changed.

## What broke
- Surface (Messages / Eve Canva / Signal / Seneca / PondWright / Kernel router / email):
- Symptom:
- First seen (UTC):
- Who noticed:

## Blast radius
- Customer-visible? Y/N
- Secrets involved? Y/N
- Egress (email / Signal / X / Canva publish)? Y/N

## Immediate
- [ ] Stop the bad path (disable tool, comment router preset, unset latch — do not delete secrets)
- [ ] Tell Jon in Messages if it is still live
- [ ] Do **not** arm `SOVERYN_EMAIL_PRODUCTION` as a “fix”

## Rollback (pick the one that matches)

### Bad persona override
```bash
# live overlay (gitignored)
ls -l ~/soveryn_vnext/data/memory/personas/
# restore from last good backup
SNAP=~/soveryn_vnext/backups/YYYY-MM-DD   # or /mnt/easystore/soveryn_backups/YYYY-MM-DD
cp "$SNAP/secrets/eve_persona.md" ~/soveryn_vnext/data/memory/personas/eve.md
```

### Canva token expiry / bad OAuth
```bash
python -m soveryn.platform.canva status
# if unauthorized: re-OAuth; do not commit tokens.json
# restore last tokens only if the Canva app still accepts them
SNAP=/mnt/easystore/soveryn_backups/YYYY-MM-DD
cp "$SNAP/secrets/canva_tokens.json" ~/soveryn_vnext/data/canva/tokens.json && chmod 600 $_
```

### Email almost-send / latch panic
- Confirm `SOVERYN_EMAIL_PRODUCTION` is **unset** in `.env`
- SMTP present without the latch must still refuse tools (`connectors.py` + `platform/email/`)
- Do not flip CURRENT_TRUTH §2 to Live

### Router / model load crash (e.g. Flash-Next CUDA softmax)
- Leave the preset **commented**
- `systemctl --user restart soveryn-router-quadro.service` only after the ini is safe
- Do not reload a known-crash GGUF “to check”

### Secrets / disk
See `docs/runbooks/secrets-state-backup.md` — real restore, not the scratch drill.

## After
- Root cause in one paragraph:
- What we changed in CURRENT_TRUTH:
- Follow-up (parked / owned by):
