# NU:TONIC — Complete artifact reference and formatting guide

This document is the **implementation-facing** companion to the visual and HTML references. Game apps must be **highly themed** and depend on **static, custom-designed artifacts** held in the repository—not on runtime CDN styling. Use this guide when mapping Stitch/HTML reference layouts into **Compose Multiplatform** (or any other UI stack): **tokens, hierarchy, spacing, and copy** must align here and in **`rules/DESIGN.md`**.

**Precedence when sources differ**

1. **`rules/DESIGN.md`** — color semantics, glass/glow rules, typography roles, component behavior.  
2. **`rules/01-navigation-architecture.md`** — canonical tab routes and depth.  
3. **Stitch `code.html`** — layout density, Tailwind token names, Orbitron usage on specific screens, Material Symbols choices.  
4. **`refs/stitch/nu_tonic_interface_design_specification.html`** (when present) — product copy, footguns, screen list.  

If Stitch’s Tailwind `borderRadius.lg` (0.5rem) conflicts with DESIGN’s primary button radius (1rem), **implement DESIGN** (≈12–16dp CTA corners) unless product signs a waiver.

---

## 1. Repository artifact map (what lives where)

| Kind | Canonical path | Role |
|------|----------------|------|
| Design system prose | `rules/DESIGN.md` | North star, palette, glass, type, components, do/don’t. |
| Navigation truth | `rules/01-navigation-architecture.md` | Home · Map · Play · Leaderboard · Settings; stitch label mapping. |
| Design rules (code) | `rules/02-design-system.md` | How to apply tokens in Kotlin theme. |
| Screen inventory | `rules/07-screens-checklist.md` | Which `refs/stitch/<id>/` pairs exist. |
| HTML reference | `refs/stitch/<screen_id>/code.html` | Structure, class names, inline CSS hooks (**reference only**). |
| Visual reference | `refs/stitch/<screen_id>/screen.png` | Pixel composition, glow weight, balance. |
| Global UX spec | `refs/stitch/nu_tonic_interface_design_specification.html` | Flows, footguns, nav intent. |
| Interface stack | `rules/09-html-vendoring-and-interface-stack.md` | No production CDN; Compose is primary UI. |
| Server-mediated cache | `rules/13-client-cache-and-data-plane.md` | Clients pull **bundles / manifests** from the NU:TONIC API only; **no** Hugging Face CLI or Hub tokens on device. |

**Static assets the themed app must vendor in-repo** (no Google Fonts / Material Symbols CDN in production):

- **Fonts:** Space Grotesk (display), Inter (body/UI), Orbitron (tactical headlines / HUD where mocks use `font-tactical` or spec calls for sci-fi display).  
- **Icons:** Equivalent vectors or a **single** bundled icon font set; map Stitch `material-symbols-outlined` names to your set consistently.  
- **Textures:** Optional scanline/grid overlays as drawable/asset files (PNG/SVG) or Compose-drawn equivalents.  
- **Brand:** Logo mark, globe/splash art if used—stored under e.g. `shared/src/commonMain/composeResources/` (or project convention).  

---

## 2. Semantic color tokens (canonical hex)

Use **only these names** in theme code; hex values below match **`rules/DESIGN.md`** and Stitch Tailwind extension (aligned set).

### 2.1 Core surfaces (Void)

| Token | Hex | Usage |
|-------|-----|--------|
| `background` / `surface` | `#0F131E` | App canvas, main backdrop. |
| `surface_dim` | `#0F131E` | Same plane as surface; dim regions. |
| `surface_container_lowest` | `#0A0E19` | Deepest void; **never pure `#000000`** unless high-contrast mode requires it. |
| `surface_container_low` | `#171B27` | Grouping panels, bottom bar base. |
| `surface_container` | `#1B1F2B` | Mid containers. |
| `surface_container_high` | `#262A36` | Active / elevated cards. |
| `surface_container_highest` | `#313441` | Input fills, recessed fields. |
| `surface_variant` | `#313441` | Glass fill base (with alpha). |
| `surface_bright` | `#353945` | List row flash / hover tone. |

### 2.2 Content on surfaces

| Token | Hex | Usage |
|-------|-----|--------|
| `on_surface` | `#DFE2F2` | Primary text on dark surfaces. |
| `on_surface_variant` | `#BAC9CC` | Secondary / recessed copy. |
| `on_background` | `#DFE2F2` | Text on background. |
| `outline` | `#849396` | Rare dividers (prefer spacing). |
| `outline_variant` | `#3B494C` | Ghost border at **~15% opacity** when required for a11y. |

### 2.3 Signal (Primary cyan)

| Token | Hex | Usage |
|-------|-----|--------|
| `primary` | `#C3F5FF` | Headline tint, glow highlights, label emphasis. |
| `primary_container` | `#00E5FF` | **Primary filled buttons**, active tab, key CTAs. |
| `on_primary_container` | `#00626E` | Text/icons on cyan fill (or dark text per mock: use `#00363D` / `on_primary` where contrast demands). |
| `on_primary` | `#00363D` | Text on light primary tint areas. |
| `primary_fixed` / `primary_fixed_dim` | `#9CF0FF` / `#00DAF3` | Fixed palette slots if using M3-style roles. |
| `inverse_primary` | `#006875` | Inverse surfaces. |
| `surface_tint` | `#00DAF3` | Subtle surface tinting. |

### 2.4 Secondary (warning / industrial)

| Token | Hex | Usage |
|-------|-----|--------|
| `secondary` | `#FFB68B` | Warning text accents. |
| `secondary_container` | `#FF7F1C` | Caution, rank-2 / “YOU” accent borders in leaderboard mocks. |
| `on_secondary_container` | `#602A00` | Text on orange fills. |

### 2.5 Tertiary (success / growth)

| Token | Hex | Usage |
|-------|-----|--------|
| `tertiary` | `#AAFFC7` | Success labels. |
| `tertiary_container` | `#00EE91` | Positive XP, upload/success buttons, rank-3 accents. |
| `on_tertiary` / `on_tertiary_container` | `#00391F` / `#00673C` | On success fills. |

### 2.6 Error

| Token | Hex | Usage |
|-------|-----|--------|
| `error` | `#FFB4AB` | Error text. |
| `error_container` | `#93000A` | Error surfaces. |
| `on_error` | `#690005` | On error. |

### 2.7 Spec alias (nu_tonic HTML markdown, when cited)

The interface spec sometimes lists **#0B0F1A** (background) and **#121829** (panels). Map them to **`surface` / `surface_container_lowest`** and **`surface_container_low`** respectively—do not introduce a third parallel palette.

---

## 3. Typography

### 3.1 Typefaces and roles

| Role | Family | When to use |
|------|--------|-------------|
| Display / headlines | **Space Grotesk** | App bar wordmark, section titles, uppercase “terminal” headers. **Uppercase + ~5% letter-spacing** for major headers per DESIGN. |
| Body / UI | **Inter** | Labels, body, buttons (except tactical), settings descriptions. |
| Tactical / HUD | **Orbitron** | Sequence IDs, monospace-style banners, “sci-fi” titles where Stitch sets `font-tactical`. **Do not** set entire screens in Orbitron. |

### 3.2 Size scale (align Compose `TextStyle` to spec + mocks)

| Step | Approx size | Weight | Typical use |
|------|-------------|--------|-------------|
| Display XL | 28–32sp | Bold / Black | Screen titles (“MISSION COMPLETE”, “PROTOCOL CONFIGURATION”). |
| Display LG | `3.5rem` equivalent (~56sp) | Black | Rare full-bleed terminal headers (DESIGN); use sparingly on mobile. |
| Title | 20–24sp | SemiBold | Card titles, section headers. |
| Body | 14–16sp | Regular / Medium | Descriptions, form text. |
| Label / caption | 11–12sp | Medium | Metadata, footer build string, coordinate row. |
| Micro / HUD | 10–11sp | Regular, **monospace or Orbitron** | `LAT:` / `LNG:` / `ELV:`, sequence codes, accuracy/latency in leaderboard rows. |

**Hierarchy rule:** Headlines feel **heavy**; body feels **recessed** (`on_surface_variant`).

---

## 4. Layout, elevation, and effects

### 4.1 Spacing and radius

- **Card / panel separation:** Prefer **0.75rem (12dp)** vertical gap between siblings inside a group; larger **void** between major modules (DESIGN).  
- **Primary CTA corner radius:** **1rem (16dp)** per DESIGN; large cyan buttons in mocks match this visually.  
- **Secondary controls:** `8–12dp` radius for chips, small cards.  
- **Pills / badges:** Full pill (`9999dp` logical).  

### 4.2 Glassmorphism (interactive panels)

- **Blur:** 12–20px backdrop blur where the platform supports it; else **solid** `surface_variant` at **40–60% opacity** + subtle gradient.  
- **Edge light:** Linear gradient **top-left → bottom-right**, `primary` at **~5% opacity** → transparent.  
- **No-line rule:** No 1px solid boxes for structure; use **background shift** between `surface_container_low` and `surface_dim`.

### 4.3 Glow and bloom

- **Primary bloom:** `primary_container` at **~10% opacity**, **~32dp blur** on elevated actions (Play node, primary CTA).  
- **Text drop-shadow (header wordmark):** e.g. `0 0 8dp` with `primary_container` ~40% opacity (matches Stitch `drop-shadow-[0_0_8px_rgba(0,229,255,0.4)]`).  
- **Discipline:** Glow only on **critical path** controls (see `rules/08-ux-and-performance-footguns.md`).

### 4.4 Ghost border

- Color: `outline_variant` (**#3B494C**) at **~15% opacity** on strokes only when needed for focus or WCAG boundary clarity.

### 4.5 Atmospheric overlays (from Stitch `code.html` patterns)

Implement as a **non-interactive** top layer; **disable or simplify** when reduced motion is on.

**Scanlines**

```text
Overlay: repeating vertical gradient
  stripes: transparent 50% / rgba(0, 229, 255, 0.03) 50%
  period: 4px (background-size height 4px, full width)
pointerEvents: none
```

**Glitch text (decorative only)**

```text
text-shadow:
  2px 0 #FF7F1C,
  -2px 0 #00E5FF
```

**Marker ripple (map pin)**

```text
Pseudo-ring: 2dp stroke primary_container, circular, scaled from pin anchor; opacity ~0.8; respect reduced motion (static ring or none).
```

---

## 5. Components — formatting checklist

### 5.1 Primary button (Tactile Cyan-Tech)

- Fill: **`primary_container`**; label: **dark on cyan** (`on_primary` / `#00363D` or mock-equivalent bold black).  
- **All caps** or small caps for major CTAs where mocks show it (`INITIALIZE PROTOCOL`, `LOCK IN GUESS`, `ENTER THE NETWORK`).  
- **Pressed:** scale **0.98**; **hover/desktop:** scale **1.02** + **~15dp** primary bloom.  
- Min height: **48dp** touch target; prefer **56dp** for hero CTAs.

### 5.2 Secondary / outline button

- Dark fill `surface_container_high` or transparent; stroke: ghost border; label `on_surface` or `primary`.

### 5.3 Tertiary success button (e.g. “UPLOAD CONFIG”)

- Fill **`tertiary_container`**; label dark/green-safe contrast per token table.

### 5.4 Text fields

- Fill: **`surface_container_highest`**. No underline-only Material default.  
- **Focus:** 1dp **inner** stroke `primary` + **~4dp** outer glow.  
- Label: **small caps** style (“IDENTITY TAG”, “ACCESS PROTOCOL”), **4dp** above field.  
- Leading icon: user / lock silhouettes as in authentication mock.

### 5.5 Cards

- Rounded rect; **no list dividers**—separation by spacing and surface level.  
- Optional frosted treatment per §4.2.

### 5.6 Sliders (settings)

- Track: dark recessed bar; thumb: **circular**, **primary_container** “glow” thumb; value label **percentage** in monospace or tabular figures.

### 5.7 Toggles

- ON: **primary_container** track/thumb; OFF: neutral gray.  
- **High contrast / reduced motion / large data** must change real rendering (not just a flag).

### 5.8 Bottom navigation (“Horizon bar”)

- Container: **`surface_container_low`** + **~24dp** blur equivalent.  
- **Play** (canonical route): **elevated** circular **`primary_container`** with **strong bloom**.  
- **Active tab:** **2dp tall** `primary` bar **above** the icon (not below).  
- Inactive icons: **`primary` at ~60% opacity** or `on_surface_variant`.  

**Stitch label mapping** (when reading mocks): `SCAN` → gameplay/map context; `INTEL` → intel feed if product adds; `RANK` → Leaderboard; `SQUAD` → Settings or social—see `rules/01-navigation-architecture.md`.

### 5.9 Top app bar

- **Fixed** feel; background **`surface` ~80% opacity** + blur; horizontal padding **~24dp**; wordmark **Space Grotesk**, **tracking wide**, **uppercase**, color **`primary`** tint on **`#C3F5FF`**.  
- Trailing: profile **`account_circle`**; optional XP pill **`primary_container` text** on dark chip.

---

## 6. Screen-by-screen artifact and formatting binding

Pair each row with **`refs/stitch/<folder>/code.html` + `screen.png`** when those files exist in the repo.

| # | Screen | Stitch folder | Mandatory visual elements | Formatting notes |
|---|--------|---------------|---------------------------|------------------|
| 1 | Splash | `splash_screen` | Globe / glitch art, **NU:TONIC** logotype, tagline *“MEMORY IS ALL THAT REMAINS”*, **INITIALIZE PROTOCOL** CTA, footer status row | Tagline flanked by thin horizontal rules; footer: green **SYSTEM STABLE**, signal + **XP ACTIVE**, sector label; **BUILD** micro string corner. Dark void + cyan glow on title. |
| 2 | Authentication | `authentication` | Rocket/brand icon, **NU:TONIC**, system version string, card “Reconnect to Earth”, identity + password fields, **ENTER THE NETWORK**, Create Identity, biometric/QR hints | Card is elevated glass panel; **EMERGENCY RESET?** link right-aligned above primary; footer **SERVER:** + copyright. |
| 3 | Role selection | `role_selection` | **SELECT YOUR IDENTITY**, subtitle italic gray, three horizontal **role cards** (Human / Astronaut / Alien) with icon, tag (STABLE / VOYAGER / XENO), chevron, **INITIALIZE** + bolt | Cards: role-specific accent (orange rocket, green alien); protocol version under CTA. |
| 4 | Dashboard | `dashboard` | XP chip, **RANK PROGRESS** + bar, circular **PLAY NOW**, **MEMORY STABILITY** gradient bar, **CURRENT SESSION** media card, **DAILY PROTOCOLS** checklist | Progress bars thin cyan; memory bar green→purple gradient; quest rows with check circles and XP rewards. |
| 5 | World map gameplay | `world_map_gameplay` | Header wordmark, **SCORE PREVIEW** card, **SIGNAL EXPIRATION** timer + cyan dot, hint bulb, **map** with grid + **pin** + `SCAN_POINT_*` label, **LOCK IN GUESS**, **LAT/LNG/ELV** row, bottom bar | Timer **tabular / digital** feel; primary CTA full width; coords **monospace**; scanline overlay optional. |
| 6 | Success overlay | `success_overlay` | Modal card, cyan check in glowing circle, particles (respect reduced motion), **SIGNAL LOCK ACHIEVED**, precision + XP stat boxes, **VIEW FULL RESULTS →**, **RETURN TO SECTOR MAP** | **PRECISION** neutral; **GROWTH** XP in **tertiary / green**; primary cyan button. |
| 7 | Final results | `final_results` | **MISSION COMPLETE**, sequence id, large score card, **LIVE INTEL MAP** card, **TACTICAL BREAKDOWN** rows, **LEVEL UP PROGRESSION** bar, **GLOBAL RANKS** + role filters, leaderboard rows, **PLAY AGAIN**, **SHARE DATA** | Sequence **monospace**; score **large cyan**; filters **HUMAN | ASTRONAUT | ALIEN**; ranks **1 cyan border**, **2 orange + YOU**, **3 green**; each row **ACCURACY %** + **LATENCY ms**. |
| 8 | Settings / protocol | `settings_protocol` | **PROTOCOL CONFIGURATION** title with underline accent, avatar block, **CHANGE ROLE**, **SECURITY STATUS** green stripe, **AUDIO FREQUENCY** sliders, **NEURAL ADAPTATION** toggles, **FACTORY RESET** / **UPLOAD CONFIG** | Section titles with icons; security inner panel green left bar; destructive vs success button pairing. |

### 6.1 Leaderboard row schema (presentation)

For **GLOBAL RANKS** (results screen and Leaderboard tab), each row must support:

- **Rank** (1-based), **display name**, **role tag** (e.g. CARTOGRAPHER), **title** (e.g. GLOBAL MASTER), **score** (tabular), **accuracy** (%), **latency** (ms).  
- **You** row: distinct **secondary_container** border; score aligns with mission score.  
- **Typography:** stats in **monospace** or small caps; names in **Inter** semibold.

### 6.2 Game launch overlay (spec text, no separate stitch id in checklist)

- Sheet/dialog: mode **Solo / Multiplayer / AI**, difficulty; must not exceed **two levels** of depth from tab root (`rules/01-navigation-architecture.md`).

---

## 7. Iconography (Material Symbols → app)

Stitch uses **`material-symbols-outlined`** with `data-icon` for tooling. Standardize names across clients:

| Context | Symbol name (reference) |
|---------|-------------------------|
| Brand / signal | `sensors` |
| Profile | `account_circle` |
| Leaderboard / rank | `leaderboard` |
| Home / play | `home`, `rocket_launch` (per mock) |
| Settings | `settings` or gear in mock |
| Hint | `lightbulb` |
| Lock guess | `lock` |
| Security | `shield` |
| Audio | `volume_up` or `graphic_eq` |
| Accessibility | `accessibility_new` or `person` |

---

## 8. Strings and microcopy (frozen examples)

Use a **single string table**; evolve copy without forking per platform.

- Splash tagline: **MEMORY IS ALL THAT REMAINS**  
- Splash CTA: **INITIALIZE PROTOCOL**  
- Auth headline: **Reconnect to Earth**  
- Auth sub: **Initialize Memory Profile to begin**  
- Role screen title: **SELECT YOUR IDENTITY**  
- Gameplay CTA: **LOCK IN GUESS**  
- Success title: **SIGNAL LOCK ACHIEVED**  
- Success sub: **MEMORY FRAGMENT SUCCESSFULLY RECOVERED.**  
- Results title: **MISSION COMPLETE**  
- Settings title: **PROTOCOL CONFIGURATION**  

---

## 9. Motion, accessibility, and performance

Mandatory alignment with **`rules/08-ux-and-performance-footguns.md`**:

- Map: **large invisible hit slop** around guess actions.  
- Feedback: **~100ms** perceived response for taps.  
- **Reduced motion:** disable/simplify particles, parallax, ripple animation.  
- **High contrast:** may strengthen outlines; still avoid pure black void if possible.  
- **Glow:** rare, high-value only.

---

## 10. What not to ship

- **No** `cdn.tailwindcss.com` or **fonts.googleapis.com** in production builds (`rules/09-html-vendoring-and-interface-stack.md`).  
- **No** duplicate business logic inside vendored HTML `<script>` without tests and an approved bridge ADR.  
- **No** raw hex in feature composables—only **`NutonicTheme` tokens**.

---

## 11. Related documents

| Document | Purpose |
|----------|---------|
| `rules/DESIGN.md` | Authoritative design system prose |
| `rules/02-design-system.md` | Theme application in code |
| `rules/04-maps-and-gameplay.md` | Map abstraction and gameplay |
| `rules/05-networking-leaderboard.md` | API hydration |
| `rules/06-server-embedding-and-ai.md` | Server-side embeddings |
| `plans/2026-04-07-gradio-terramind-backend.md` | Reference server architecture |

---

*Last aligned with repo rules and Stitch-derived tokens as of 2026-04-07. Update this file when `screen.png` or `code.html` artifacts change.*
