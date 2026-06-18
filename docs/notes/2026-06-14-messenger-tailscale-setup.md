# Messenger v1 — Tailscale Funnel Setup (TLS Termination)

**Task 15** of the SOVERYN Messenger v1 plan. The messenger PWA runs on port `5001` on SOVERYN; this note documents how to expose it to the public internet with managed TLS via Tailscale Funnel so Jon's phone can reach `https://soveryn.<tailnet>.ts.net/m/` from anywhere without port-forwarding or self-signed certs.

These commands require sudo on SOVERYN and must be run by Jon — they are not executed by an agent.

---

## 1. Enable Funnel for the messenger port

Run the following on SOVERYN:

```bash
sudo tailscale funnel --bg 5001
sudo tailscale funnel status
```

- `--bg` keeps the Funnel attached after the shell exits (persists across reboots).
- `funnel status` should show port `5001` mapped to a public HTTPS endpoint.

## 2. Get the cert-bearing hostname

The public URL uses SOVERYN's Tailscale DNS name (which automatically has a valid Let's Encrypt cert from Tailscale's infra):

```bash
tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//'
# Returns: soveryn.<tailnet>.ts.net
```

The messenger PWA is then reachable at:

```
https://soveryn.<tailnet>.ts.net/m/
```

The pairing admin route (localhost-only, see Caveats below) stays at:

```
http://127.0.0.1:5001/m/pair
```

## 3. Verification

After Funnel is on, smoke test end-to-end:

1. Open `https://soveryn.<tailnet>.ts.net/m/` on a phone (the phone does *not* need Tailscale installed — Funnel exposes to the public internet).
2. Confirm the pairing screen renders (Terminal-meets-Luxury aesthetic; see Task 13).
3. From a SOVERYN-local browser, hit `http://127.0.0.1:5001/m/pair` to mint a pairing code.
4. Paste the code on the phone, complete claim flow, confirm device token issued.
5. Send a message round-trip; verify SSE stream renders the reply incrementally (Task 14).
6. Confirm the PWA install prompt appears (browser offers **Add to Home Screen**); install and re-test from the standalone PWA shell.
7. Verify IDB outbox + service-worker retry survives a brief network drop (toggle airplane mode mid-send; message should flush on reconnect — Task 14).

## 4. Rollback

If Funnel needs to come off (e.g., during maintenance, or to flip back to Tailscale-only access):

```bash
sudo tailscale funnel reset
```

This tears down the public mapping immediately. The messenger continues serving on `127.0.0.1:5001` and over the tailnet at SOVERYN's MagicDNS name, but is no longer reachable from the public internet.

## 5. Caveats

- **Public internet exposure.** Funnel routes through Tailscale's edge nodes and exposes the messenger to the entire public internet. TLS is terminated at Tailscale's edge with a valid Let's Encrypt cert tied to the `*.ts.net` hostname.
- **Authentication is still the messenger's job.** Funnel is *only* TLS termination and reverse proxying. Anyone who reaches the URL still needs a valid device secret (issued during pairing) to send or receive messages. Auth lives in the messenger's device-token middleware, not at the network edge.
- **Pairing is localhost-only.** The `/m/pair` admin route is gated by Task 7's `_require_localhost` decorator. Even with Funnel exposing `/m/` publicly, pairing codes can only be minted from `127.0.0.1` (i.e., a browser session on SOVERYN itself or via an SSH tunnel). Funnel traffic arrives with non-loopback source addresses and is rejected from the admin route by design.
- **Rate limiting / abuse.** Funnel doesn't add rate limiting. If the device-token layer is brute-forceable, the public exposure widens the attack surface. Token entropy and any login-attempt throttling are the messenger's responsibility.

## 6. Alternative — Cloudflare Tunnel

If Funnel isn't viable (tailnet policy restrictions, ACL conflicts, or Funnel being disabled for the tailnet), **Cloudflare Tunnel** is the documented fallback. Same operational properties:

- Managed TLS (Cloudflare's edge cert).
- No port-forwarding required.
- Outbound-only connection from SOVERYN to Cloudflare's edge.

The trade-off is routing through Cloudflare's edge instead of Tailscale's, which is a different trust footprint. The localhost-only admin route still holds — `_require_localhost` rejects any non-loopback source regardless of which tunnel terminates TLS.

Setup sketch (not run here):

```bash
# One-time: install cloudflared, authenticate, create a tunnel
cloudflared tunnel login
cloudflared tunnel create soveryn-messenger
cloudflared tunnel route dns soveryn-messenger messenger.<jon's domain>

# Run the tunnel pointing at localhost:5001
cloudflared tunnel --url http://127.0.0.1:5001 run soveryn-messenger
```

The PWA URL then becomes `https://messenger.<jon's domain>/m/`.
