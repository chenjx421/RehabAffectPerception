# RehabAffect Classroom Studio Design System

**Direction:** Quiet Swiss evidence workspace
**Audience:** Special-education teachers, teaching researchers, school managers
**Product character:** Calm, precise, respectful, evidence-first

## Product Principles

1. Make evidence readable before making data decorative.
2. Use calm hierarchy for a sensitive classroom context; do not gamify student status.
3. Reserve coral for teacher-review-required states. Do not color-code every metric.
4. Use professional line icons only. Never use emoji as controls or status symbols.
5. Keep teacher judgment visible: provisional findings must never look final.
6. Prefer full-width work bands and unframed reading layouts. Cards are for repeated evidence items only.

## Color Tokens

| Role | Token | Value | Use |
| --- | --- | --- | --- |
| Canvas | `--canvas` | `#F3F6F4` | Page background |
| Paper | `--paper` | `#FFFFFF` | Work surfaces |
| Warm paper | `--paper-warm` | `#FAFAF7` | Long-form reports |
| Ink | `--ink` | `#1D2E2D` | Primary text |
| Muted ink | `--muted` | `#60706C` | Secondary text; WCAG AA on canvas |
| Mineral green | `--teal` | `#4B766F` | Active navigation and evidence accents |
| Deep mineral | `--navy-deep` | `#173633` | Primary commands and video stage |
| Review coral | `--coral` | `#CF715F` | Items requiring teacher review |
| Hairline | `--line` | `#DBE3DF` | Dividers and component borders |
| Strong hairline | `--line-strong` | `#C5D1CC` | Inputs and structural boundaries |

No purple UI, rainbow metric cards, bright educational blue, decorative gradients, or colored shadows.

## Typography

- UI and headings: `Helvetica Neue`, `Aptos`, `Segoe UI`, `PingFang SC`, system sans-serif.
- Chinese long-form report: `Noto Serif SC`, `Source Han Serif SC`, `Songti SC`, serif.
- Engineering identifiers: `Cascadia Code`, `SFMono-Regular`, `Consolas`, monospace.
- Do not scale type with viewport width. Letter spacing is `0`, except compact eyebrow labels at `0.08-0.12em`.
- Minimum body size is `12px` for dense evidence tables; normal reading copy is `13-14px`.

## Spacing

Use the sequence `4, 8, 12, 16, 20, 24, 30, 42, 64` pixels.

- Control height: `40-46px`.
- Compact evidence row: `12-16px` vertical padding.
- Analysis content: `28-30px` desktop, `14-18px` mobile.
- Major section gap: `26-42px`.
- Cards and panels: `3-5px` radius. Status pills may use a full radius.

## Elevation

- Default surfaces use borders, not shadows.
- Main work surfaces: `0 12px 34px rgba(31,56,51,.055)`.
- Entry dialog only: `0 34px 90px rgba(28,50,47,.16)`.
- No colored or floating card shadows.

## Components

### Buttons

- Primary commands use deep mineral fill and white text.
- Secondary commands use white fill and a mineral border.
- Option sets use segmented controls.
- Icon-only buttons require an accessible name and tooltip.
- Minimum target height is `40px`.

### Navigation

- Desktop analysis navigation is a quiet mineral-tinted rail with Lucide-style line icons.
- Tablet and mobile navigation becomes a horizontally scrollable tab strip with scroll snapping.
- Active state uses a two-pixel mineral rule and white surface, not a saturated block.
- Arrow keys, Home, and End navigate tabs.

### Evidence

- Evidence uses a thin review-coral left rule only when teacher attention is required.
- Student, teacher, and outcome form one linked reading sequence.
- Teacher-review clips are disclosure rows: first clip opens by default; remaining clips stay summarized.
- Internal robot motion codes appear beside a plain-Chinese action label.

### Reports And Data

- Course reports use a warm paper surface and Chinese serif body copy.
- Deep reports use a sticky section index and unframed reading column.
- JSON is constrained to a scrollable code viewer; it must never expand the full page.

## Responsive Rules

- `1440px`: complete workbench, 232px analysis rail.
- `1120px` and below: video and student evidence stack; classroom stage becomes a full-width 16:9 surface.
- `1024px`: stacked evidence workbench; analysis rail remains visible.
- `768px`: header wraps, process becomes 2x2, analysis navigation becomes horizontal.
- `390px`: student selectors and analysis tabs scroll horizontally; evidence and forms become one column.
- No horizontal document overflow at any supported width.

## Accessibility And Safety

- All normal text must reach WCAG AA contrast (`4.5:1`).
- Focus rings remain visible; reduced-motion preferences are respected.
- Tabs expose `tablist`, `tab`, `tabpanel`, `aria-selected`, and roving `tabindex` semantics.
- Modes expose `aria-pressed`; status changes use polite live regions.
- Timeline slices require accessible time, lesson phase, and state names.
- UI language must say “初评”“待复核”“证据不足”, never imply diagnosis or certainty.

## Delivery Checklist

- [x] No emoji or mixed icon families
- [x] No unexplained color outside the token palette
- [x] No control shorter than 40px unless it is a non-interactive visual tick
- [x] No unnamed interactive control
- [x] No broken or blank image
- [x] No console or page errors
- [x] No horizontal overflow at 360, 390, 768, 1024, 1366, and 1440px
- [x] Entry, three-student switch, group/portrait, report generation, and keyboard tabs tested
- [x] All provisional conclusions keep teacher-review language visible
