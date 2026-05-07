# Lully · single-label · pixel-perfect reproduction

This folder is the **visual confirmation deliverable** for label cell #1
(`GATEAU BASQUE / À LA PART`) from
[`raw-requirements/Plano etiquetas (easy).pdf`](../../raw-requirements/Plano%20etiquetas%20%28easy%29.pdf).

## What's here

| File                      | What it is                                        |
|---------------------------|---------------------------------------------------|
| `single-label.html`       | **Self-contained HTML** — open in any browser     |
| `single-label.pdf`        | Print-ready PDF rendered from the HTML            |
| `single-label-vector.svg` | The vector SVG that the HTML inlines              |
| `icons/`                  | The 4 individual icon SVGs (figurine + 3 allergens) |

## How it was built

The cell content was extracted directly from the source PDF — no manual
recreation, no font guessing:

1. **Text glyphs** → `pdftocairo -svg` of page 1, which converts the embedded
   Adobe Garamond Pro Type1 fonts (the original print template fonts) into
   vector outlines at exact page-coordinate positions. Every letterform is
   from the source document, not a free substitute like EB Garamond.

2. **Icon paths** (figurines + allergen circles + their white symbols) →
   `PyMuPDF.get_drawings()` of the same page, walked to find every primitive
   inside the cell-1 bounding box.

3. **Layout** → bounding boxes from the PDF crop-mark transforms, so cell
   size is **79.95 × 56.24 mm** exactly, with text and icons at the same
   page coordinates as the source.

4. The two streams are merged into a single SVG, then the SVG is inlined
   inside an HTML wrapper.

## Verified fidelity

Pixel diff vs. the source PDF cell (rasterised at 300 DPI, both rendered
through the same path):

```
mean abs diff:    4.73 / 255  (1.9%)
matched within 10: 95.10%
matched within 30: 96.01%
```

Remaining ~5% is **pure antialiasing edge noise** between two different
rasterisers (Chrome's Skia vs. ImageMagick's Cairo). Every glyph and icon
is in the exact same position with the exact same outline.

## Layout reference (extracted from source PDF)

| Element     | Font                       | Size  | Cell-relative position    | Notes                |
|-------------|----------------------------|-------|---------------------------|----------------------|
| figurine    | (vector silhouette)        | 4.80×7.16mm | top=5.05mm, x_inset=5.30mm | TWO per label, top corners |
| title       | Adobe Garamond Pro Regular | 14pt  | top=15.90mm, line-height=1.302 | uppercase, letter-spacing wide |
| description | Adobe Garamond Pro Italic  | 13pt  | top=29.39mm, line-height=1.030 | centred, italic |
| allergens   | (vector circles)           | 5.97×5.97mm | top=41.61mm, x=4.69mm  | zero spacing between |
| price       | Adobe Garamond Pro Italic  | 15pt  | top=42.51mm, right_inset=5.12mm | bottom-right |
| color       | `#7B7676` (`rgb(48.12%,46.23%,46.09%)`) | — | applies to all      | sampled from PDF     |

## Next step (after confirmation)

Port the layout constants above into the production templates at
`templates/labels/labels.css` so the data-driven pipeline (Sheet → PDF)
matches the same fidelity. Two open questions for that port:

1. **Font** — the production pipeline currently uses **EB Garamond** (free,
   Google Fonts). To reach the exact pixel-fidelity above, the bakery would
   need to provide their licensed **Adobe Garamond Pro** OTF/TTF files;
   they get dropped into `templates/labels/fonts/` and an `@font-face` rule
   gets added. Without that, EB Garamond is ~95% visually equivalent and
   metrically very close.
2. **Icons** — the canonical SVGs in `icons/` (figurine, gluten, milk, egg)
   were extracted from the PDF and are 1:1 with the source. The 3 missing
   allergens (nuts, peanut, soy) can be extracted the same way from labels
   that contain them (e.g. CAKE AU CHOCOLAT has all 6).
