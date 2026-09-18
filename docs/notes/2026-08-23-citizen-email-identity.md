Roster authority: README §What is SOVERYN — Vett/Scotty rows are design-only until re-promoted.

# Citizen email identity (ours — not AgentMail)

**Date:** 2026-08-23  
**Status:** **Pending — not armed.** Code + identity map exist. DNS/SMTP/`SOVERYN_EMAIL_PRODUCTION=1` have not been flipped. The canonical step list and its count live in `docs/CURRENT_TRUTH.md` §2 (Citizen email row); this note holds the full checklist body and does not restate the number. The latch stays off.  
**Trigger:** Musk / Grok Bot “why its own email?” + AgentMail pitch. Same problem we’ve held: agents must not write as Jon from his personal inbox.

## Claim (design intent — not live)

**Every founding hand is designed to send as a house-owned address.** Not Jon’s Gmail. Not a cloud inbox SaaS control plane. SMTP/IMAP we configure; **Approval Gate** on `email_send`. Live egress stays off until ops below are done and the production latch is set.

| Their frame | Ours |
|-------------|------|
| Grok Bot + AgentMail plugin | Citizen channel under CoS + Gate |
| AgentMail API in the cloud | `SOVERYN_SMTP_*` + house domains |
| One bot Gmail plugin → your inbox | Per-citizen From allowlist; personal inbox never mounted |

## v0 identity map

| Who | Default From | Also allowed |
|-----|--------------|--------------|
| Aetheria | `aetheria@soverynintelligence.com` | `aetheria@carolinawatergardens.com` |
| Vett (folded — see README roster) | `vett@soverynintelligence.com` **(design-only — do-not-arm; folded into Eve)** | `vett@carolinawatergardens.com` **(design-only — do-not-arm)** |
| Eve / Kernel (Scotty folded — see README roster) | `{name}@soverynintelligence.com` | `pondwright@carolinawatergardens.com` (design-only — do-not-arm; desk alias) |
| PondWright (desk) | `pondwright@carolinawatergardens.com` **(design-only — do-not-arm; desk alias)** | Aetheria/Vett may send-as **(design-only / do-not-arm)** |

Override: `SOVERYN_EMAIL_IDENTITIES` JSON (see `soveryn/platform/email/identities.py`).

## Code

- `soveryn/platform/email/identities.py` — map + resolve/allowlist  
- `email_send` — From = citizen identity (optional `from` if allowlisted)  
- Connectors board — `email_identities` + per-citizen `email_from` / `email_aliases`  
- Gate unchanged — write egress still requires Allow  
- **Production latch:** `SOVERYN_EMAIL_PRODUCTION=1` required in addition to SMTP (SMTP alone does not register tools)

## Ops checklist (Jon) — required before production

1. Create aliases on **soverynintelligence.com** and **carolinawatergardens.com**  
2. SPF/DKIM (and DMARC when ready) for both domains  
3. Arm house SMTP: `SOVERYN_SMTP_HOST`, `SOVERYN_SMTP_FROM` (envelope mailbox), user/pass  
4. Optional IMAP for house inbox list (not personal Gmail)  
5. Set `SOVERYN_EMAIL_PRODUCTION=1` only after a controlled smoke  
6. Smoke: Messages → Aetheria → Gate Allow → send test as `aetheria@soverynintelligence.com`  
7. Flip `docs/CURRENT_TRUTH.md` to Live only after smoke  
8. Bounce / complaint policy (write **before** the latch flips): bounces land at the `SOVERYN_SMTP_FROM` postmaster, never a personal inbox; citizen egress auto-stops on the first spam complaint or DMARC `arc=fail`; re-arm only by Jon or Aetheria-via-Gate; Jon reviews DMARC aggregates weekly  
9. Roster tiers: live citizens = Aetheria/Kernel/Eve; folded = Vett⇑Eve, Scotty⇑Kernel; teammates = Critic/Scout. Do not add Vett or Scotty back to `ACTIVE_AGENTS` or the email allowlist as live identities. (added 2026-09-09 per Critic 9d3933be)  
## Non-goals (v0)

- AgentMail / any mail SaaS agent plugin  
- Mounting Jon’s personal Gmail  
- Full per-citizen IMAP silos  
- Auto signup on GitHub/Reddit  

## Related

- `2026-08-21-phone-chat-house.md` — Messages as OS  
- Connectors grants — `soveryn/citizens/connectors.py`  

_Updated 2026-08-23: AgentMail wave → house citizen From identities._  
_Updated 2026-08-24: kill-list #4 — marked not production everywhere; production latch._  
_Updated 2026-09-07: step 8 bounce/complaint policy (Critic overnight 52aba9ac)._  
_Updated 2026-09-09: step 9 roster tiers (live/folded/teammates) (Critic overnight 9d3933be)._  
superseded-by: for live status, trust `docs/CURRENT_TRUTH.md` §2 (Citizen email row) — this note is the canonical checklist text, §2 is the canonical live-state pointer.
