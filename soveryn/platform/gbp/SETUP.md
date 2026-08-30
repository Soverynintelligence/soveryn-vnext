# Google Business Profile — CWG (Eve)

Eve posts **updates** to the Carolina Water Gardens listing after Messages **Allow**.
She does **not** run ads or touch billing. Cadence never calls `eve_gbp_post`.

## 1. Google Cloud project

1. [Google Cloud Console](https://console.cloud.google.com/) → new or existing project.
2. Enable:
   - **My Business Account Management API**
   - **My Business Business Information API**
   - **Google My Business API** (v4 — local posts)
3. APIs → **Credentials** → **OAuth client ID** → Desktop app (or Web with loopback).
4. Redirect URI exactly:
   ```
   http://127.0.0.1:8766/oauth/gbp/callback
   ```
5. Copy **Client ID** and **Client secret**.

## 2. Request API access (quota starts at zero)

Google leaves Business Profile quota at **0** until they approve you.

Form is linked from [Basic setup / request access](https://developers.google.com/my-business/content/basic-setup).
Use the CWG verified listing + carolinawatergardens.com. This can take days.

Until then, `eve_gbp_post` returns `needs_api_access`. Honest. Not a bug.

## 3. Env on the tower

Same place as Canva / other secrets (`soveryn-vnext` `.env` or systemd):

```bash
export SOVERYN_GBP_CLIENT_ID='…'
export SOVERYN_GBP_CLIENT_SECRET='…'
# optional if several listings on the Google account:
# export SOVERYN_GBP_LOCATION='accounts/ACCOUNT_ID/locations/LOCATION_ID'
# export SOVERYN_GBP_CTA_URL='https://carolinawatergardens.com'
```

## 4. Authorize once (Jon)

```bash
cd ~/soveryn_vnext
python -m soveryn.platform.gbp status
python -m soveryn.platform.gbp authorize
```

Browser: sign in as the **CWG Google account** (the one that owns the listing / ran the ads). Tokens: `data/gbp/tokens.json` (mode 600, gitignored).

## 5. Eve tools

- `eve_gbp_status` — read, ungated
- `eve_gbp_post` — live CWG update, **Gate Allow only**, never cadence, never ads

Photos: `Desktop/CWG-Instagram`. Text still posts if GBP will not take a local file (Google wants a public URL or media upload).

## 6. Ads

Leave ads in Google Ads. Eve must not spend.
