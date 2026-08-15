# PondWright Cloudflare failover (tower)

When Spark loses WiFi/internet, public hosts (chat/crm/estimator/ask/atticus)
run through the tower:

1. `pondwright-ssh-forwards.service` — SSH -L tower → Spark loopback agents
2. `pondwright-smtp-relay.service` — SSH -R Spark:2465 → Gmail via tower
3. `pondwright-tunnel.service` — cloudflared with credentials under
   `~/.cloudflared-pondwright/` (not in git)

CRM `notify.py` uses `smtp.host=127.0.0.1` / `port=2465` /
`tls_hostname=smtp.gmail.com` during this mode.

Restore units:
  cp docs/ops/pondwright-failover/*.service ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --now pondwright-ssh-forwards pondwright-smtp-relay pondwright-tunnel
