#!/usr/bin/env bash
# Persist Spark internet-via-tower:
#   1) Tower: systemd oneshot for NAT/forward (survives reboot)
#   2) Spark: NetworkManager cx7-tower gateway + DNS (survives reboot)
#
# Run on the TOWER in an interactive terminal (sudo prompts on tower + Spark):
#   bash ~/soveryn_vnext/docs/ops/pondwright-failover/persist-spark-internet.sh
#
set -euo pipefail

OPS="$(cd "$(dirname "$0")" && pwd)"
SPARK_HOST="${SPARK_HOST:-soverynspark@10.10.10.2}"

echo "== 1/2 tower: install spark-fabric-nat.service =="
sudo install -m 755 "$OPS/apply-spark-fabric-nat.sh" /usr/local/sbin/apply-spark-fabric-nat.sh
sudo tee /etc/systemd/system/spark-fabric-nat.service >/dev/null <<'UNIT'
[Unit]
Description=NAT Spark CX-7 fabric (10.10.10.0/30) out house uplink
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=UPLINK=enp66s0f0np0
Environment=FABRIC=enp130s0f1np1
ExecStart=/usr/local/sbin/apply-spark-fabric-nat.sh

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now spark-fabric-nat.service
sudo systemctl --no-pager --full status spark-fabric-nat.service || true

echo "== 2/2 spark: persist cx7-tower gateway + DNS =="
# -tt + remote string (no heredoc on stdin) so Spark sudo can prompt.
ssh -tt -o ConnectTimeout=15 "$SPARK_HOST" \
  "set -e;
   sudo nmcli connection modify cx7-tower \
     ipv4.method manual \
     ipv4.addresses 10.10.10.2/30 \
     ipv4.gateway 10.10.10.1 \
     ipv4.dns '1.1.1.1 8.8.8.8' \
     ipv4.never-default no \
     ipv4.route-metric 100;
   sudo nmcli connection up cx7-tower;
   if ! ip route | grep -q '^default via 10.10.10.1'; then
     sudo ip route replace default via 10.10.10.1 dev enp1s0f1np1;
   fi;
   sudo resolvectl dns enp1s0f1np1 1.1.1.1 8.8.8.8 || true;
   echo '--- spark routes ---';
   ip -4 route;
   echo '--- nm connection ---';
   nmcli -f ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,ipv4.never-default connection show cx7-tower;
   echo '--- checks ---';
   ping -c 2 -W 2 1.1.1.1;
   getent hosts example.com | head -2;
   curl -sS -m 5 -o /dev/null -w 'https://example.com %{http_code}\n' https://example.com/;
  "

echo ""
echo "== persist complete =="
echo "Tower: systemctl status spark-fabric-nat"
echo "Spark: nmcli -f ipv4.gateway,ipv4.dns,ipv4.never-default connection show cx7-tower"
