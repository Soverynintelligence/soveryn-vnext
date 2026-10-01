#!/usr/bin/env bash
# Give Spark (10.10.10.2) internet via tower (10.10.10.1) over CX-7.
#
# Run ON THE TOWER (needs sudo on tower + on Spark):
#   bash docs/ops/pondwright-failover/spark-internet-via-tower.sh
#
set -euo pipefail

UPLINK="${UPLINK:-enp66s0f0np0}"     # tower → house router
FABRIC="${FABRIC:-enp130s0f1np1}"    # tower → Spark CX-7
SPARK_HOST="${SPARK_HOST:-soverynspark@10.10.10.2}"
SPARK_FABRIC_IF="${SPARK_FABRIC_IF:-enp1s0f1np1}"

echo "== tower: IP forward =="
sudo sysctl -w net.ipv4.ip_forward=1

echo "== tower: NAT fabric → uplink =="
sudo iptables -t nat -C POSTROUTING -s 10.10.10.0/30 -o "$UPLINK" -j MASQUERADE 2>/dev/null \
  || sudo iptables -t nat -A POSTROUTING -s 10.10.10.0/30 -o "$UPLINK" -j MASQUERADE

echo "== tower: FORWARD =="
sudo iptables -C FORWARD -i "$FABRIC" -o "$UPLINK" -j ACCEPT 2>/dev/null \
  || sudo iptables -A FORWARD -i "$FABRIC" -o "$UPLINK" -j ACCEPT
sudo iptables -C FORWARD -i "$UPLINK" -o "$FABRIC" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
  || sudo iptables -A FORWARD -i "$UPLINK" -o "$FABRIC" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

echo "== spark: default route via tower =="
# Do NOT use a heredoc into ssh (that steals stdin → no TTY → sudo fails).
# -tt forces a TTY so Spark sudo can prompt. Commands are remote args only.
ssh -tt -o ConnectTimeout=8 "$SPARK_HOST" \
  "set -e;
   if ip route | grep -q '^default '; then sudo ip route del default || true; fi;
   sudo ip route add default via 10.10.10.1 dev ${SPARK_FABRIC_IF};
   if ! grep -qE 'nameserver [0-9]' /etc/resolv.conf 2>/dev/null; then
     echo 'nameserver 1.1.1.1' | sudo tee /etc/resolv.conf >/dev/null;
   fi;
   echo 'routes:';
   ip -4 route;
   echo 'ping 1.1.1.1:';
   ping -c 2 -W 2 1.1.1.1 || true;
   curl -sS -m 5 -o /dev/null -w 'https://example.com %{http_code}\n' https://example.com/ || true;
  "

echo "== done =="
echo "Persist later: netfilter-persistent on tower; on Spark set gateway 10.10.10.1 on cx7-tower."
