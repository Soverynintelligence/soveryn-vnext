# Google Calendar — CWG (Eve)

Eve can **list** upcoming events (OAuth or private iCal) and **create** one
after Messages **Allow**. She does not delete calendars.

## OAuth tester block (Error 403 access_denied)

Google’s “Soveryn Intelligence LLC has not completed verification” screen
means the consent app is in **Testing** and the account you clicked is **not**
a tester — or the screen is **Internal** (Workspace-only) and you used Gmail.

1. Cloud Console → **the same project as the OAuth client**
2. **APIs & Services → Google Auth Platform → Audience** (old name: OAuth consent screen)
3. User type must be **External** if you sign in with `gmail.com`.
   Internal = only `@your-workspace` users. Gmail will always fail.
4. Publishing status: **Testing**
5. **Test users → Add** the **exact** address on the blocked page
   (`Jon.Deoliveira@gmail.com` and/or the CWG account)
6. Save. Wait a minute.
7. Chrome **Incognito**, only that Google account, then:

```bash
python -m soveryn.platform.gcal authorize
```

Do not use the LLC Workspace login unless that address is also a tester.

## Read-only without OAuth (works today)

Google Calendar → Settings (the calendar, not the account) →
**Integrate calendar** → **Secret address in iCal format**.

Put it in `~/soveryn_vnext/.env` (do not commit, do not paste in chat):

```
SOVERYN_GCAL_ICAL_URL=https://calendar.google.com/calendar/ical/…/private-…/basic.ics
```

Then `eve_calendar_list` works. `eve_calendar_create` still needs OAuth.

## OAuth client (for create)

Desktop app. Redirect URI:

```
http://127.0.0.1:8767/oauth/gcal/callback
```

Enable **Google Calendar API**. Client ID/secret:

```
SOVERYN_GBP_CLIENT_ID=…
SOVERYN_GBP_CLIENT_SECRET=…
```
