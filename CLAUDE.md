# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Print-ready bakery labels (A4, 8 per sheet, 79.95 × 56.24 mm each, with crop marks) generated from a Google Sheet. Built originally for **Lully 1661 Boulangerie** (Lisbon), shipped as a working reference for any pastry shop to fork. There is no long-running server — execution is split across three runtimes that communicate via `repository_dispatch` and Drive uploads.

## Common commands

Local CSV → HTML/PDF render (no Google deps):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements-labels.txt
python3 scripts/build-labels.py --pdf       # uses data/labels-sample.csv → dist/labels.{html,pdf}
python3 scripts/build-labels.py --source <path-or-published-csv-url>
```

The `--pdf` flag invokes headless Chrome via `scripts/build-labels.py:_find_chrome()` — it probes `/Applications/Google Chrome.app/...` and PATH for `google-chrome`/`chromium`/`chrome`. Without Chrome you only get `dist/labels.html`.

OAuth setup (one-time, run on a laptop, not in CI):
```bash
python3 scripts/oauth-setup.py --client-id <ID> --client-secret <SECRET>
# Prints GOOGLE_OAUTH_REFRESH_TOKEN — paste into GitHub repo secrets.
```

There are no tests, no linter config, and no build step beyond `pip install`. The CI workflow (`.github/workflows/build-labels.yml`) only runs `release-labels.py`.

## Architecture — the three runtimes

```
Google Sheet (real_data tab)                       <-- bakery staff edit here
        |
        | "🥖 Lully → Generate" menu click
        v
apps-script/lully-labels.gs (Apps Script)          <-- runs in the Sheet
        |
        | POST repository_dispatch (event_type=generate-labels)
        | client_payload: { request_id, sheet_id, tab, requested_by, ... }
        v
.github/workflows/build-labels.yml                 <-- runs in GitHub Actions
        |
        | sets all client_payload values into env: (NEVER into shell `run:`)
        v
scripts/release-labels.py                          <-- the orchestrator
   1. refresh OAuth access token
   2. read tab via Sheets API → CSV → data/_release-input.csv
   3. subprocess: scripts/build-labels.py --source ... --pdf
   4. upload dist/labels.pdf + CSV snapshot to Drive folder
   5. append row to release_history tab (status=success|failed)
```

Single source of truth is the Sheet's `real_data` tab. The `release_history` tab is the audit log — every dispatch first appends `status=submitted`, then the Action overwrites with `success`/`failed`. Both ends MUST keep `release_history` writable.

### Layout pipeline (build-labels.py)

`scripts/build-labels.py` is the only renderer. It is dependency-light by design (`jinja2` + `requests`) so it works locally without Google APIs:

1. `_load_rows()` — accepts a local CSV path OR a published Sheet CSV URL (auto-detected by `http(s)://` prefix).
2. `_normalize()` — filters rows where `active` is truthy (`x`, `true`, `1`, `y`, `yes`, `sim`), formats price as `4,20€` (Portuguese decimal comma), collects allergen flags into a list ordered by `ALLERGEN_COLS`.
3. `_paginate()` — chunks into `LABELS_PER_SHEET = 8` (2×4 grid), pads the last sheet with `None` placeholders that render empty cells with crop marks but no content.
4. Jinja renders `templates/labels/labels.html.j2` with `StrictUndefined` (any missing template var crashes — use this when adding fields).
5. `_copy_static()` copies `labels.css` + `icons/*.svg` next to the HTML so `dist/labels.html` is self-contained.
6. `_render_pdf()` calls headless Chrome with `--no-pdf-header-footer`.

### Pixel-fidelity contract

The CSS in `templates/labels/labels.css` is **not arbitrary** — every dimension was reverse-engineered from `reference-pdf/Plano etiquetas (easy).pdf`. Coordinates are in `mm`, positioning is absolute. Specific constants you must not change without re-validating against `docs/design-reference/single-label.html` (the pixel-perfect ground truth):

- Cell: 79.95 × 56.24 mm. Sheet padding: t/b 27.04 mm, l 20.08 / r 20.67 mm (asymmetric). Column gap 9.34 mm, row gap 5.99 mm.
- Title (`.name`): top 15.90 mm, font-size 14pt, line-height 1.302, letter-spacing 0.26em, uppercase, `white-space: pre-line` (preserves Alt+Enter from Sheet cells).
- Description (`.description`): top 29.39 mm, italic 13pt, line-height 1.030.
- Allergens (`.allergens`): origin (4.69 mm, 41.61 mm), each icon 5.97 × 5.97 mm, edge-to-edge.
- Price (`.price`): top 42.51 mm, right inset 5.12 mm, italic 15pt.
- Color: `--label-grey: #7B7676` (sampled from the source PDF), `--crop-grey: #B8B0A4`.

Font fallback chain is `"Adobe Garamond Pro", "EB Garamond", "Garamond", Georgia, serif`. EB Garamond is loaded via Google Fonts CDN and is the open-source fallback — drop a licensed `AGaramondPro.otf` into `templates/labels/fonts/` + add an `@font-face` block to upgrade to 100% match.

### Schema — keep three places in sync

When adding/renaming a column or allergen, three files must change together:

1. `apps-script/lully-labels.gs` — `COLUMNS` array (controls sheet column order, widths, validations). On-sheet column order must equal label icon order.
2. `scripts/build-labels.py` — `ALLERGEN_COLS` list (controls icon render order on the label).
3. `templates/labels/icons/<slug>.svg` — must exist for every allergen slug in `ALLERGEN_COLS`. Match the existing grey-circle stroke style.

`name_fr` supports forced line breaks (Alt+Enter in the Sheet → `\n` in CSV → `pre-line` in CSS). Don't strip them.

## Security: workflow injection

`.github/workflows/build-labels.yml` deliberately passes every `client_payload.*` value through the `env:` block, never interpolated into `run:` shell commands. When editing the workflow, preserve this — the `client_payload` is attacker-influenceable (anyone with the PAT can dispatch).

## Branding / fork etiquette

The bundled brand assets — `templates/labels/icons/figurine.svg`, `data/labels-sample.csv`, `reference-pdf/Plano etiquetas (easy).pdf`, `docs/design-reference/single-label.*` — are property of Lully 1661 Boulangerie, shipped with permission as the working reference. Code is MIT. A fork rebranding for another bakery should replace those specific files.

## Operator setup

End-to-end Sheet → Drive setup is documented in `docs/sheet-setup.md` (OAuth client creation, refresh-token mint, GitHub secrets, Apps Script paste). When asked about deployment, point users there rather than re-deriving steps.
