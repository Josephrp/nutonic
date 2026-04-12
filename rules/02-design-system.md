# Design system rules

**Typography and visual tokens for shipped builds:** canonical product spec is **`docs/DESIGN.md`** (Neon Relic palette, glass rules, **Space Grotesk + Inter + Orbitron** roles, component behaviors). **This file** adds **implementation** constraints: semantic tokens in Kotlin, bundled font files (no runtime font CDN), `NutonicTypography` indirection, and degraded blur where needed. **Stitch** (`refs/stitch/...`) is **layout and density** reference only—if a mock predates `docs/DESIGN.md`, implement **`docs/DESIGN.md`** and record deltas in theme code. **`refs/DESIGN.md`** is optional legacy token prose when present in a checkout; it does **not** override `docs/DESIGN.md` for new work.

## Colors

- Use **semantic tokens** (e.g. `primary`, `surface`, `surface_container_low`) in code; **do not** sprinkle raw hex across composables except inside the single theme definition.
- **Void vs signal:** Dark navy surfaces vs cyan accent. Prefer **tonal stacking** for separation; avoid heavy 1px borders for structure (DESIGN “No-Line” rule).
- **Ghost borders** only where accessibility requires: low-opacity outline variant, not harsh boxes.

## Typography

- **Display / headlines:** Space Grotesk — uppercase + modest positive letter-spacing where DESIGN specifies.
- **Body / UI chrome:** Inter (or platform equivalent with same role).
- **Tactical / numeric HUD:** **Orbitron** (bundled with the app alongside Space Grotesk and Inter) or monospace **only** where stitch/spec demands strong sci-fi labeling; do not set entire screens in display fonts (readability footgun in spec).

Load fonts in a **platform-appropriate** way; theme exposes `NutonicTypography`, not raw `Font` in feature screens. **Orbitron** files live in repo resources (not runtime CDN) for production builds.

## Surfaces and depth

- **Glass panels:** Translucent fills + blur in supported targets; provide **degraded fallback** (solid surface + subtle gradient) where blur is costly or unsupported.
- **Glow:** Use **sparingly** on primary actions (DESIGN). Primary button cyan fill + controlled outer bloom; avoid glowing every card.

## Components (must match behavior)

| Pattern | Rule |
|--------|------|
| Primary button | Filled `primary_container`, large radius (~12–16dp), pressed/hover scale per DESIGN |
| Inputs | Recessed surface, **focus = primary stroke + small outer glow**, label 4dp above field |
| Cards | Rounded; separation by **spacing and surface level**, not divider lines |
| Bottom bar | Blurred/low surface; **elevate the dominant game tab** — **default:** **SCAN** hub tab (see `rules/01-navigation-architecture.md`); active indicator **above** icon |
| Header music toggle | **Every** checklist screen (`rules/07-screens-checklist.md`): trailing **music on/off** bound to `audio.music_master_enabled`; matches SETUP Audio section. **One BGM loop per primary route** — mapping and assets in [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md). |

## Motion and accessibility

- **Settings toggles** (high contrast, reduced motion, large data) must **actually change** rendering: reduce or disable parallax, particles, and non-essential animation when reduced motion is on.
- Respect **large text / scaling** where platform allows; “Large data rendering” should tie into font scale or density multiplier in shared theme.

## Background effects

- Scanlines / grid / HUD textures: **optional overlay** composable, behind content, `pointerEvents` disabled; must respect reduced motion (static or off).

## Iconography

- Prefer **one** icon set across platforms (e.g. Material icons extended with custom vectors for brand marks). Do not mix unrelated icon families per screen.
