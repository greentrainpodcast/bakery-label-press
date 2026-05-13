"""Build Lully product-label sheets (A4, 2×4 grid) from a CSV or Google Sheet.

Input columns (case-sensitive):
  name_fr        -- French product name (rendered uppercase)
  description_pt -- Portuguese description (italic)
  gluten / milk / egg / nuts / peanut / soy
                 -- one column per allergen; cell value is "x"/"X"/"true"/"1"
                    if the product contains that allergen, blank otherwise
  price          -- decimal number (e.g. 4.20). Rendered as "4,20€"
  active         -- "x" to include this row in the output, blank to skip

Source can be either:
  - local CSV path (e.g. data/labels-sample.csv)
  - a published Google Sheet CSV URL (File → Share → Publish to web → CSV)

Output:
  dist/labels.html        -- always written, can be opened in any browser
  dist/labels.pdf         -- optional, requires --pdf and a Chrome/Chromium binary

Usage:
  python3 scripts/build-labels.py
  python3 scripts/build-labels.py --source data/labels-sample.csv
  python3 scripts/build-labels.py --source 'https://docs.google.com/spreadsheets/d/.../pub?output=csv' --pdf
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates" / "labels"
DEFAULT_SOURCE = ROOT / "data" / "labels-sample.csv"
DEFAULT_OUT_DIR = ROOT / "dist"

# Order matters — this is the order allergen icons render in the foot row,
# and must match the column order on the Sheet's real_data tab.
# 5 allergens: gluten, milk, egg, peanut, soy. (The codebase originally
# mislabelled the 5th source-PDF icon as "nuts" — it actually depicts
# soybeans; we corrected the slug to "soy". A separate nuts column was
# briefly added then dropped per bakery feedback as redundant overlap
# with peanut/soy.)
ALLERGEN_COLS = ["gluten", "milk", "egg", "peanut", "soy"]

LABELS_PER_SHEET = 8  # 2 columns × 4 rows


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"x", "true", "1", "y", "yes", "sim"}


def _format_price(raw: str) -> str:
    """4.20  ->  4,20€   |   3 -> 3,00€   |   '' -> ''"""
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return ""
    try:
        v = float(s)
    except ValueError:
        return raw  # let the user see their typo
    return f"{v:.2f}".replace(".", ",") + "€"


def _load_rows(source: str) -> list[dict]:
    """Load CSV from a local path OR a published Google Sheets URL."""
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source) as resp:  # noqa: S310 (URL is user-supplied)
            text = resp.read().decode("utf-8-sig")
    else:
        text = Path(source).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [r for r in reader]


def _normalize(rows: list[dict]) -> list[dict]:
    """Filter active rows and shape them for the template."""
    out = []
    for i, r in enumerate(rows, start=2):  # start=2 because row 1 is the header
        if not _truthy(r.get("active")):
            continue
        name = (r.get("name_fr") or "").strip()
        if not name:
            print(f"  ⚠ row {i}: missing name_fr — skipped", file=sys.stderr)
            continue
        desc = (r.get("description_pt") or "").strip()
        # 3+ line descriptions overflow the 29.4mm text-block budget at the
        # default 13pt size; flag them so the template can apply `.long` for
        # a tighter render. See `.description.long` in labels.css.
        desc_long = desc.count("\n") >= 2
        out.append({
            "name_fr": name,
            "description_pt": desc,
            "desc_long": desc_long,
            "allergens": [c for c in ALLERGEN_COLS if _truthy(r.get(c))],
            "price_str": _format_price(r.get("price", "")),
        })
    return out


def _paginate(items: list[dict], per_sheet: int) -> list[list[dict | None]]:
    """Group items into sheets of `per_sheet`, padding the last sheet with None."""
    sheets = []
    for start in range(0, len(items), per_sheet):
        chunk = items[start:start + per_sheet]
        chunk += [None] * (per_sheet - len(chunk))
        sheets.append(chunk)
    return sheets or [[None] * per_sheet]  # always emit at least one sheet


def _copy_static(out_dir: Path) -> None:
    """Copy CSS + icons next to the generated HTML so the file is self-contained."""
    (out_dir / "icons").mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE_DIR / "labels.css", out_dir / "labels.css")
    for svg in (TEMPLATE_DIR / "icons").glob("*.svg"):
        shutil.copy(svg, out_dir / "icons" / svg.name)


def _find_chrome() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def _render_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = _find_chrome()
    if not chrome:
        print(
            "  ⚠ Chrome/Chromium not found — open dist/labels.html manually and "
            "use File → Print → Save as PDF.",
            file=sys.stderr,
        )
        return
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    subprocess.run(cmd, check=True)
    print(f"  ✓ PDF: {pdf_path.relative_to(ROOT)}")


def build(source: str, out_dir: Path, *, pdf: bool) -> None:
    rows = _load_rows(source)
    items = _normalize(rows)
    if not items:
        print("✗ No active rows found.", file=sys.stderr)
        sys.exit(1)
    sheets = _paginate(items, LABELS_PER_SHEET)

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("labels.html.j2").render(sheets=sheets)

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "labels.html"
    html_path.write_text(html, encoding="utf-8")
    _copy_static(out_dir)
    print(f"  ✓ HTML: {html_path.relative_to(ROOT)}  ({len(items)} labels, {len(sheets)} sheet(s))")

    if pdf:
        _render_pdf(html_path, out_dir / "labels.pdf")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default=str(DEFAULT_SOURCE),
                   help=f"CSV path or published Google Sheet URL (default: {DEFAULT_SOURCE.relative_to(ROOT)})")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                   help=f"Output directory (default: {DEFAULT_OUT_DIR.relative_to(ROOT)})")
    p.add_argument("--pdf", action="store_true",
                   help="Also render PDF via headless Chrome (if installed)")
    args = p.parse_args()
    build(args.source, Path(args.out_dir), pdf=args.pdf)


if __name__ == "__main__":
    main()
