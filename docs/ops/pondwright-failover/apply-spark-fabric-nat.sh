#!/usr/bin/env bash
# Apply tower NAT so Spark (10.10.10.2) can use house internet via CX-7.
# Safe to re-run (idempotent). Intended as root (systemd or sudo).
set -euo pipefail

UPLINK="${UPLINK:-enp66s0f0np0}"
FABRIC="${FABRIC:-enp130s0f1np1}"

sysctl -w net.ipv4.ip_forward=1 >/dev/null

iptables -t nat -C POSTROUTING -s 10.10.10.0/30 -o "$UPLINK" -j MASQUERADE 2>/dev/null \
  || iptables -t nat -A POSTROUTING -s 10.10.10.0/30 -o "$UPLINK" -j MASQUERADE

iptables -C FORWARD -i "$FABRIC" -o "$UPLINK" -j ACCEPT 2>/dev/null \
  || iptables -A FORWARD -i "$FABRIC" -o "$UPLINK" -j ACCEPT

iptables -C FORWARD -i "$UPLINK" -o "$FABRIC" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
  || iptables -A FORWARD -i "$UPLINK" -o "$FABRIC" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# Also accept established via state (older kernels)
iptables -C FORWARD -i "$UPLINK" -o "$FABRIC" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
  || iptables -A FORWARD -i "$UPLINK" -o "$FABRIC" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
  || true

echo "spark-fabric-nat: forward=1, NAT 10.10.10.0/30 → $UPLINK, FORWARD $FABRIC↔$UPLINK"
