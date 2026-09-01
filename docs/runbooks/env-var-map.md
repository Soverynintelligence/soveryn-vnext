# SOVERYN env-var map (high-stakes)

One page. Full dump of every `SOVERYN_*` is not the point — these are the vars that arm egress, money, or restore. Live values live in `~/soveryn_vnext/.env` (gitignored). Authority for *whether* something is armed: `docs/CURRENT_TRUTH.md`.

| Var | Who reads it | What it does | Armed? |
|-----|--------------|--------------|--------|
| `SOVERYN_EMAIL_PRODUCTION` | `soveryn/citizens/connectors.py`, `platform/email/` | Production latch. SMTP alone does **not** register send tools. | **NOT ARMED** |
| `SOVERYN_SMTP_HOST` / `PORT` / `USER` / `PASS` / `FROM` | email connectors + identities | House SMTP. `FROM` is the envelope mailbox. | unset / not production |
| `SOVERYN_IMAP_HOST` / `PORT` / `USER` / `PASS` | email connectors | Optional house inbox list (not personal Gmail). | optional, unset |
| `SOVERYN_EMAIL_IDENTITIES` | `platform/email/identities.py` | Per-citizen From allowlist override. | default in code |
| `SOVERYN_CANVA_CLIENT_ID` / `CLIENT_SECRET` / `REDIRECT_URI` | `platform/canva/config.py` (Eve) | Canva Connect OAuth. Tokens: `data/canva/tokens.json`. | **Live** |
| `SOVERYN_GBP_CLIENT_ID` / `CLIENT_SECRET` / `REDIRECT_URI` / `LOCATION` | `platform/gbp/` (Eve) | CWG Google Business OAuth. Tokens: `data/gbp/tokens.json`. | **NOT ARMED** |
| `SOVERYN_CANVA_TEMPLATES` | Canva config | Optional template ids. | optional |
| `SOVERYN_SIGNAL_BOT_NUMBER` | signal-bridge daemon | Bot identity. Refuses to start if missing. | **Live** |
| `SOVERYN_SIGNAL_ALLOWED_NUMBERS` | signal-bridge + Eve marketing tools | Allowlist. Empty = drop all inbound. | **Live** |
| `SOVERYN_SIGNAL_DISABLED` | connectors | Kill switch for Signal tools. | off |
| `SOVERYN_SIGNAL_CLI_BIN` / `VNEXT_BASE` / `BRIDGE_ENABLED` / poll + retry | signal-bridge | Daemon plumbing. | defaults |
| `SOVERYN_X_DISABLED` | connectors | Kill switch for X tools. | off |
| `SOVERYN_GATE_USER` / `PASS` / `PORT` / `UPSTREAM` | `runtime/public_gate.py` | Funnel Basic auth. | **Live** |
| `SOVERYN_BACKUP_DEST` | `soveryn/backup/daemon.py` | Override off-box dest (default easystore path). | easystore mounted |
| `SOVERYN_DATA_ROOT` | personas, automations, Canva, botdirectory, voice | Data overlay root. | default `data/` |
| `SOVERYN_GROK_BIN` / `CWD` / `TIMEOUT` | `platform/inference/grok_build_client.py` | Headless Grok CLI for Messages Grok. | **Live** |
| `SOVERYN_SEARXNG_URL` | connectors (Scout/search) | Local search. | default `:8095` |
| `SOVERYN_CITIZENS_DB` | commissions / house posts | Citizens sqlite. | default under data |
| `SOVERYN_COS_RELAY_SIGNAL` | rooms store | CoS Signal relay. Default on. | on |

Eve CWG Instagram desk session lives in `data/eve_ig_profile/` (gitignored cookies, not an env var). Login: `python -m soveryn.platform.social.instagram_desk login`.
Agent browser desks (Eve Google Ads/Business, Aetheria/Kernel browser): `data/desks/<agent>/<seat>/chrome`. Login: `python -m soveryn.platform.social.agent_desk login eve google`.

Teammates secrets are in `~/teammates/.env`, not this tree.

Restore: `docs/runbooks/secrets-state-backup.md`.
