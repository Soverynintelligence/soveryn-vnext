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

## Spark internet via tower (CX-7)

Spark may be **wired to the tower** (CX-7 `10.10.10.2` ↔ `10.10.10.1`) while
**WiFi is still down**. That keeps SSH + agent loopbacks working for the
public tunnel failover, but Spark has **no default route**, so it cannot
reach the internet for tools / updates / outbound SMTP from Spark itself.

One-shot (tower, needs sudo):

```bash
bash docs/ops/pondwright-failover/spark-internet-via-tower.sh
```

That enables NAT on the tower and `default via 10.10.10.1` on Spark.

## Persist internet-via-tower (survives reboot)

Interactive, once (tower terminal — sudo on tower + Spark):

```bash
bash ~/soveryn_vnext/docs/ops/pondwright-failover/persist-spark-internet.sh
```

Installs:
- `spark-fabric-nat.service` — NAT/FORWARD on boot
- Spark NM `cx7-tower`: gateway `10.10.10.1`, DNS `1.1.1.1 8.8.8.8`, `never-default=no`
