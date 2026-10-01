# Canva Connect — house setup (Jon)

Eve creates designs via API. **Instagram publish** stays in Canva Content Planner (Pro) or manual paste — Connect API cannot schedule to Meta.

## 1. Canva account

- Prefer **Canva Pro/Teams** if you want Share → Schedule → Instagram (same path as History’s Ledger).
- Free: Eve can still create/export; you download/post manually.

## 2. Create an integration

1. Open [Canva Developers](https://www.canva.com/developers/) → Your integrations → **Create an integration**.
2. Name it e.g. `SOVERYN Eve`.
3. Copy **Client ID**; generate and save **Client secret**.
4. **Authentication → Redirect URL** add exactly:
   ```
   http://127.0.0.1:8765/oauth/canva/callback
   ```
5. **Scopes** enable (read + write as listed):
   - `design:content`, `design:meta`
   - `asset`
   - `brandtemplate:content`, `brandtemplate:meta`

## 3. Env on the tower

```bash
export SOVERYN_CANVA_CLIENT_ID='…'
export SOVERYN_CANVA_CLIENT_SECRET='…'
# optional brand → template map after you publish Brand Templates:
# export SOVERYN_CANVA_TEMPLATES='hl:TEMPLATE_ID,soveryn:TEMPLATE_ID,cwg:TEMPLATE_ID,acttruth:TEMPLATE_ID'
```

Put these in the same place other SOVERYN secrets live (systemd env / `.env` loaded by `soveryn-vnext`).

## 4. Authorize once

```bash
cd ~/soveryn_vnext
python -m soveryn.platform.canva status
python -m soveryn.platform.canva authorize
```

Browser opens → approve → tokens land in `$SOVERYN_DATA_ROOT/canva/tokens.json` (mode 600).

## 5. Brand templates (recommended)

In Canva, create **Brand Templates** (Enterprise/Teams feature in many plans) for IG 1080×1080 with text fields named:

- `HOOK`
- `BODY`
- `HASHTAGS`

Map them via `SOVERYN_CANVA_TEMPLATES`. Without Brand Templates, Eve can `canva_create_design` (blank) and you design in the editor, then she exports.

## 6. Social publish

1. In Canva, connect **Instagram Business** + Facebook Page (Content Planner).
2. Eve Signal-drops caption + PNG + Canva `edit_url`.
3. You open the link → **Schedule** (or paste to IG yourself).

## 7. Eve tools

- `canva_status`
- `canva_list_templates`
- `canva_autofill_post`
- `canva_create_design`
- `canva_export_design` → `data/media/canva/*.png` → `compose_post`

Restart `soveryn-vnext` after setting env so tools register.

## Troubleshooting: “The client ID is invalid”

That message is from **Canva’s consent page** — it never got a recognized integration ID.

Checklist:

1. **Copy Client ID, not Client secret.** ID usually looks like `OC-…` or `OCxxxx-…`. Secret is longer and random.
2. **No quotes in the env value.** Prefer:
   ```bash
   export SOVERYN_CANVA_CLIENT_ID=OC-yourRealIdHere
   export SOVERYN_CANVA_CLIENT_SECRET=yourSecretHere
   ```
   not `'OC-…'` with smart quotes from a chat paste.
3. **Redirect URL must match exactly** in Developer Portal → Authentication:
   ```
   http://127.0.0.1:8765/oauth/canva/callback
   ```
   (`localhost` is rejected by Canva; use `127.0.0.1`.)
4. Integration must be the **Connect API** integration you just created under [Your integrations](https://www.canva.com/developers/integrations/) — not an Apps SDK app ID.
5. After creating/editing the integration, wait a minute, then:
   ```bash
   python -m soveryn.platform.canva status   # should show starts_with_OC: true
   python -m soveryn.platform.canva authorize
   ```
6. If you regenerated the secret or deleted the integration, the old Client ID is dead — create a new integration and use the new ID.

`status` prints a fingerprint (prefix/suffix/length) only — never the full secret.
