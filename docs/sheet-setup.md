# Lully product-label generator — full setup

End-to-end workflow:

```
[Google Sheet] ── 🥖 Lully menu → Generate ──┐
                                              ▼
                                  GitHub: repository_dispatch
                                              │
                                              ▼
                          GitHub Actions: scripts/release-labels.py
                                              │
                          ┌───────────────────┼─────────────────────┐
                          ▼                   ▼                     ▼
                   Sheets API        scripts/build-labels.py    Drive API
                  (read tab)         (HTML → PDF via Chrome)    (upload PDF + CSV)
                          │                                          │
                          └────────────────► release_history ◄───────┘
```

The bakery staff just open the Sheet, click **🥖 Lully → Generate labels (PDF)**.
Within ~2 min a new row appears in `release_history` with the Drive link.

## Resources already provisioned

| What                  | ID / URL                                                                                            |
|-----------------------|-----------------------------------------------------------------------------------------------------|
| Drive folder          | [`Lully · Labels`](https://drive.google.com/drive/folders/<YOUR_DRIVE_FOLDER_ID>)                |
| Source Sheet          | [`Lully · Plano de etiquetas`](https://docs.google.com/spreadsheets/d/<YOUR_SHEET_ID>/edit) |
| Folder ID (env var)   | `<YOUR_DRIVE_FOLDER_ID>`                                                                   |
| Sheet ID (env var)    | `<YOUR_SHEET_ID>`                                                        |

## One-time setup — Sheet side

1. Open the source Sheet (link above).
2. **Extensions → Apps Script** → paste the contents of
   [`apps-script/lully-labels.gs`](../apps-script/lully-labels.gs) → save.
3. Reload the Sheet so the **🥖 Lully** menu appears.
4. **🥖 Lully → Setup / repair tabs** → creates the 3 tabs:
   - `real_data` — staff edit here (one row per product)
   - `sample` — read-only reference (the 8 originals)
   - `release_history` — append-only audit log
5. **🥖 Lully → Configure GitHub trigger** → paste:
   - owner: `<YOUR_GH_OWNER>`
   - repo: `<YOUR_REPO>`
   - PAT: a fine-grained PAT scoped to **this repo only**, with
     `Contents: read and write` (that's the scope `repository_dispatch` lives under).
     [Generate one here](https://github.com/settings/personal-access-tokens/new).

> The PAT lives in the Sheet's Apps Script properties. Anyone who can edit
> the Sheet's Apps Script can read it. Use a fine-grained, repo-scoped PAT —
> never a classic PAT.

## One-time setup — GitHub side

The Action needs to upload to Drive and write to the Sheet, both as **a real
Google user** (you chose user OAuth over service account). So we mint a
refresh token once and store it as a GitHub secret.

### Step 1 · Create an OAuth client

1. https://console.cloud.google.com → create or pick a project.
2. **APIs & Services → Library** → enable both:
   - **Google Sheets API**
   - **Google Drive API**
3. **APIs & Services → OAuth consent screen** → *External*, add your
   Google account as a *test user*. (Don't bother with verification —
   in-test mode works indefinitely for self-use.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   → application type **Desktop app** → save the client ID + client secret.

### Step 2 · Mint a refresh token

```bash
python3 -m venv .venv-labels && source .venv-labels/bin/activate
pip install -r scripts/requirements-labels.txt
python3 scripts/oauth-setup.py \
  --client-id     '...apps.googleusercontent.com' \
  --client-secret '...'
```

A browser tab opens, you log in, the script prints three values.

### Step 3 · Add GitHub repository secrets

[`Settings → Secrets and variables → Actions → New repository secret`](https://github.com/<YOUR_GH_OWNER>/<YOUR_REPO>/settings/secrets/actions/new):

| Secret name                  | Value                                              |
|------------------------------|----------------------------------------------------|
| `GOOGLE_OAUTH_CLIENT_ID`     | from step 1                                        |
| `GOOGLE_OAUTH_CLIENT_SECRET` | from step 1                                        |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | from step 2                                        |
| `LULLY_DRIVE_FOLDER_ID`      | `<YOUR_DRIVE_FOLDER_ID>`                  |

> The refresh token will keep working as long as you don't revoke the OAuth
> grant in [your Google account permissions](https://myaccount.google.com/permissions)
> or change the OAuth client's scopes. If it ever stops working, re-run
> step 2.

## Daily use

Staff edit `real_data`, tick `active` for the products to print, click
**🥖 Lully → Generate labels (PDF)**.

What they see:

- A toast: *Submitted. PDF will appear in release_history within ~2 min.*
- A new row in `release_history` with `status=submitted` (immediate)
- Within ~2 min the same `request_id` shows a `success` row with the
  Drive link to the PDF + a CSV snapshot of the data that produced it

If something goes wrong, a `failed` row appears with the error message.

## Local development

You don't need any of the OAuth / Sheet plumbing to iterate on the layout.
The original local-only flow still works:

```bash
python3 scripts/build-labels.py --pdf            # uses data/labels-sample.csv
python3 scripts/build-labels.py --source 'https://...pub?output=csv' --pdf
open dist/labels.pdf
```

For testing the full release path locally, you can run
`scripts/release-labels.py` with the same env vars the workflow sets — but
the easier path is **Actions → Build Lully labels → Run workflow** in the
GitHub UI, which uses `workflow_dispatch` with the production Sheet ID
already filled in.

## Adding a new allergen

1. Add the slug to `COLUMNS` in `apps-script/lully-labels.gs` and re-run
   **Setup / repair tabs**.
2. Add the same slug to `ALLERGEN_COLS` in `scripts/build-labels.py`.
3. Drop a 24×24 SVG into `templates/labels/icons/<slug>.svg`. Match the
   existing style: grey circle with a white symbol.

## Forced line breaks in the title

The original Plano etiquetas wraps product names at specific points
(e.g. *GATEAU BASQUE* / *À LA PART*, *COOKIE* / *AU CHOCOLAT*). To keep
that control, **the bakery uses Alt+Enter inside the `name_fr` cell** to
insert a literal newline. The PDF respects it as a hard line break.

If no `\n` is in the cell, the title renders on one line (or auto-wraps if
truly too wide for the label).

## Typography

The original print template uses **Adobe Garamond Pro** (a licensed Adobe
font). The build pipeline ships **EB Garamond** (Google Fonts, free,
metrically/visually 1:1 with Adobe Garamond). If the bakery's Adobe CC
licence covers Adobe Garamond Pro, drop the `.otf` files into
`templates/labels/fonts/` and add an `@font-face` block at the top of
`templates/labels/labels.css`; the existing `font-family` stack will pick
it up first.

## What's still placeholder

- All 6 allergen icons in `templates/labels/icons/*.svg` are simple shapes,
  not the EU-standard set. Swap in the proper CC0 icons before printing for
  real (food-labelling regulation issue).
- `templates/labels/icons/figurine.svg` is a hand-drawn outline of *La
  Pâtissière* (the pastry sub-mark). It's recognisable but rough — ask the
  designer to export the canonical silhouette SVG from the original
  InDesign template. Drop it in place; no code changes needed.
