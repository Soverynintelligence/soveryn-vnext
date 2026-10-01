# Automation routine docs

Plain-Markdown how/when/verify for each catalog automation (Rakazo-inspired).

- **Package defaults:** this directory (shipped with the house).
- **Jon overlay:** `$SOVERYN_DATA_ROOT/automations/routines/<id>.md` wins when present.
- **API:** `GET /api/automations/<id>/routine` returns the resolved markdown.
- Edit freely and commit package changes; use the data overlay for machine-local tweaks.
