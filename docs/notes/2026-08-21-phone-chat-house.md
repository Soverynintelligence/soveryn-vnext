# Phone chat house — Grok Bots insight (park)

**Date:** 2026-08-21  
**Status:** orientation only — product north-star UX, not a build plan  
**Trigger:** After a day on Grok Bots: the phone app feels like a normal chat app with access to everything; agents can form group chats and talk to each other with one as chief of staff.

## The feeling (keep this)

Not Mission Control first. **Messages first.**

- Every citizen is a contact.
- The house has group rooms (CoS + peers + Jon).
- One mobile surface that can reach tools, memory, approvals, intake — without looking like an ops console.
- Chief of Staff is a *role in the room*, not a settings page.

## Map onto SOVERYN spine

| Grok Bots energy | Ours (keep) | Gap |
|------------------|-------------|-----|
| Bots as contacts | Citizens + Easy CC Talk | Not yet a contacts-list inbox |
| Chat app on phone | `/chat`, `/m/`, soveryn_mobile | Dual with CC; not the default front door |
| Group chats | CoS + house_post / commissions | No live group *thread* Jon watches |
| Peer agent talk | house_post, delegation | File/DB more than chat UI |
| CoS | Aetheria | Already locked — do not flatten to peer swarm |
| Approvals in thread | Gate cards (CC + chat) | Shipped; keep in group rooms later |
| Access to everything | Tools + Lattice + intake | Continue; don’t become cloud bot SaaS |

**Spine unchanged:** local, Approval Gate, CoS + citizens. Steal messaging UX; refuse N rented desktops / create-a-bot marketplace.

## Related borrow list

See `2026-08-20-hermes-rakazo-soveryn-three-way.md`:

- Borrow later: `@citizen` handoff, group room + `@jon` escalate, forever-chat `/new`
- Non-goal: replacing CoS with a flat peer swarm

## When we build (order of thin slices)

1. **Group room v0** — Aetheria + one citizen + Jon; one thread; CoS speaks first / routes.  
2. **Mobile front door** — open that room from `/m` or RN like Messages.  
3. **Visible peer turns** — when Aetheria commissions Vett, a line appears in the room (not only desk outbox).  
4. Only then: multi-citizen rooms, caps, `@mention` validation.

## Quotable brief

> The app on the phone is literally like a chat app that has access to everything — agents can make group chats and communicate with each other with one being the chief of staff.

---

_Parked 2026-08-21. Intake v0 already shipped; this is the next UX north star when Jon opens it._
