# Citizen email identity (ours — not AgentMail)

**Date:** 2026-08-23  
**Status:** **Pending — not armed.** Code + identity map exist. DNS/SMTP/`SOVERYN_EMAIL_PRODUCTION=1` have not been flipped. Checklist below is complete through step 7; nothing after 08-24 contradicts that.  
**Roster note:** Vett/Scotty still have From *design* rows. They are **not** live Messages citizens (Vett folded into Eve, Scotty into Kernel).  
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
| Vett | `vett@soverynintelligence.com` | `vett@carolinawatergardens.com` |
| Eve / Scotty / Kernel | `{name}@soverynintelligence.com` | — |
| PondWright (desk) | `pondwright@carolinawatergardens.com` | Aetheria/Vett may send-as |

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
