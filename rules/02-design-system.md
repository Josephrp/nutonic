# Design system rules

Source of truth: **`refs/DESIGN.md`**, with stitch HTML as **layout and density** reference.

## Colors

- Use **semantic tokens** (e.g. `primary`, `surface`, `surface_container_low`) in code; **do not** sprinkle raw hex across composables except inside the single theme definition.
- **Void vs signal:** Dark navy surfaces vs cyan accent. Prefer **tonal stacking** for separation; avoid heavy 1px borders for structure (DESIGN “No-Line” rule).
- **Ghost borders** only where accessibility requires: low-opacity outline variant, not harsh boxes.

## Typography

- **Display / headlines:** Space Grotesk — uppercase + modest positive letter-spacing where DESIGN specifies.
- **Body / UI chrome:** Inter (or platform equivalent with same role).
- **Tactical / numeric HUD:** Monospace or Orbitron **only** where stitch/spec demands strong sci-fi labeling; do not set entire screens in display fonts (readability footgun in spec).

Load fonts in a **platform-appropriate** way; theme exposes `NutonicTypography`, not raw `Font` in feature screens.

## Surfaces and depth

- **Glass panels:** Translucent fills + blur in supported targets; provide **degraded fallback** (solid surface + subtle gradient) where blur is costly or unsupported.
- **Glow:** Use **sparingly** on primary actions (DESIGN). Primary button cyan fill + controlled outer bloom; avoid glowing every card.

## Components (must match behavior)

| Pattern | Rule |
|--------|------|
| Primary button | Filled `primary_container`, large radius (~12–16dp), pressed/hover scale per DESIGN |
| Inputs | Recessed surface, **focus = primary stroke + small outer glow**, label 4dp above field |
| Cards | Rounded; separation by **spacing and surface level**, not divider lines |
| Bottom bar | Blurred/low surface; **Play node elevated**; active indicator **above** icon |

## Motion and accessibility

- **Settings toggles** (high contrast, reduced motion, large data) must **actually change** rendering: reduce or disable parallax, particles, and non-essential animation when reduced motion is on.
- Respect **large text / scaling** where platform allows; “Large data rendering” should tie into font scale or density multiplier in shared theme.

## Background effects

- Scanlines / grid / HUD textures: **optional overlay** composable, behind content, `pointerEvents` disabled; must respect reduced motion (static or off).

## Iconography

- Prefer **one** icon set across platforms (e.g. Material icons extended with custom vectors for brand marks). Do not mix unrelated icon families per screen.
