# vNext systemd templates

Daily code backup at 04:30 (offset from production backup.sh at 04:00).

## Install (user-scoped)

```bash
mkdir -p ~/.config/systemd/user
cp soveryn-vnext-backup.service ~/.config/systemd/user/
cp soveryn-vnext-backup.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now soveryn-vnext-backup.timer
systemctl --user list-timers | grep vnext-backup
```

## Verify

```bash
# Manual one-shot:
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.backup.daemon --once

# Inspect backups:
ls /media/jon-deoliveira/easystore/soveryn_vnext_code_backups/
cat /media/jon-deoliveira/easystore/soveryn_vnext_code_backups/<latest>/SNAPSHOT.json
```

## Uninstall

```bash
systemctl --user disable --now soveryn-vnext-backup.timer
rm ~/.config/systemd/user/soveryn-vnext-backup.{service,timer}
systemctl --user daemon-reload
```

Templates are committed but NOT auto-installed. Install manually when ready.
