# DEPLOY — SOVERYN vNext (Flask, :5001)

**Repo:** `~/soveryn_vnext` (branch: `main`) · **Host:** tower · **Unit:** `soveryn-vnext.service` (user systemd)

## Deploy steps

1. `bash scripts/verify.sh` — must be GREEN (tests + compile + secrets)
2. `git add … && git commit` — hooks block secrets
3. `git push origin main` (offsite record)
4. `systemctl --user restart soveryn-vnext.service`
5. `curl -fsS http://127.0.0.1:5001/health` and watch `logs/vnext.log` (rotates at 50 MB × 5)

## Notes

- `.env` holds flags incl. `SOVERYN_KERNEL_LATTICE`, SMTP, `SOVERYN_EMAIL_PRODUCTION=1` (email grants: eve + kernel only)
- App logs go to stdout (journald) + RotatingFileHandler `logs/vnext.log`
- After changing `.env`, restart the service to apply

## Gotchas

- vNext serves citizens' tool registry at boot — connector/tool changes need a restart
- The scotty worker polls the drain endpoint every 60 s; a restart is seamless to it
