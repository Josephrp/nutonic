# Design System Specification

## 1. Overview & Creative North Star
**The Creative North Star: "The Neon Relic"**

This design system is a study in high-contrast survivalism. We are not designing a sterile laboratory interface; we are designing a salvaged, high-tech HUD functioning within a cold, post-apocalyptic void. The aesthetic balances the brutalist weight of deep space with the ethereal, fragile glow of advanced "Cyan-Tech."

To move beyond generic sci-fi templates, we embrace **Intentional Asymmetry** and **Optical Depth**. We do not use grids to cage elements, but to anchor them. By utilizing heavy "ink traps" in typography and layering frosted surfaces, we create a UI that feels like it’s floating three inches in front of the user's eyes.

---

## 2. Colors & Surface Logic

### Palette Definition
Our color strategy relies on the tension between the "Void" (deep navies) and the "Signal" (neon accents).

*   **Primary (Signal):** `primary` (#C3F5FF) / `primary_container` (#00E5FF) — The pulse of the UI.
*   **Secondary (Warning):** `secondary` (#FFB68B) / `secondary_container` (#FF7F1C) — Industrial caution.
*   **Tertiary (Success):** `tertiary` (#AAFFC7) / `tertiary_container` (#00EE91) — Bio-organic stability.
*   **Background (The Void):** `surface` (#0F131E) / `surface_container_lowest` (#0A0E19).

### The "No-Line" Rule
Standard 1px solid borders are strictly prohibited for structural sectioning. To define a layout, use **Background Shift**. A card should be recognized because it is `surface_container_low` sitting atop a `surface_dim` background, not because it has an outline.

### The Glass & Gradient Rule
All interactive panels must utilize **Glassmorphism**.
*   **Backdrop Blur:** 12px to 20px.
*   **Fill:** `surface_variant` at 40% - 60% opacity.
*   **Signature Texture:** Use a subtle linear gradient (Top-Left to Bottom-Right) from `primary` at 5% opacity to `transparent` to simulate light catching the edge of a glass pane.

---

## 3. Typography
We use a **three-family** stack so HUD and long-form copy stay distinct: engineered display, readable UI, and tactical numerics.

*   **Display & Headlines (`Space Grotesk`):** Chosen for its geometric, engineered feel. Use `display-lg` (3.5rem) for major terminal headers. Always set to uppercase with +5% letter spacing to evoke a digital broadcast.
*   **Titles & Body (`Inter`):** This is our "Operating System" font. It provides the high-legibility needed for complex game stats.
*   **Tactical / numeric HUD (`Orbitron`):** Sequence IDs, coordinate readouts, latency or accuracy micro-labels, and other “sci-fi instrument” lines where stitch uses tactical display—**not** for whole paragraphs. Prefer **Inter** for any block of body copy.
*   **Visual Hierarchy:** Headlines should feel "heavy" and authoritative, while body text should feel light and recessed (`on_surface_variant`).

### Ship contract (repository build / publish / CI)
**Themed typography is vendored in this repo**—production and release pipelines must **not** depend on runtime font CDNs (e.g. `fonts.googleapis.com`). Implementations should load **Space Grotesk**, **Inter**, and **Orbitron** from packaged assets (Compose Multiplatform convention: e.g. `nutonic/shared/src/commonMain/composeResources/font/` with `FontFamily` / `NutonicTypography` in theme code). **`docs/DESIGN.md`** (this file) plus **`rules/02-design-system.md`** are the canonical spec for what ships; CI should fail or warn once a font-check task exists and expected files are missing.

---

## 4. Elevation & Depth

### The Layering Principle
Depth is achieved through **Tonal Stacking**. 
1.  **Level 0 (The Void):** `surface_container_lowest` (#0A0E19) - The base canvas.
2.  **Level 1 (Sub-Panels):** `surface_container_low` (#171B27) - For grouping related data.
3.  **Level 2 (Active Cards):** `surface_container_high` (#262A36) - For actionable content.

### Ambient Shadows & Glows
Forget black shadows. In this system, "elevation" is light. 
*   **Floating Elements:** Apply a diffused outer glow using the `primary_container` color at 10% opacity, with a 32px blur. This creates a "bloom" effect rather than a traditional drop shadow.
*   **The Ghost Border:** If a boundary is required for accessibility, use `outline_variant` (#3B494C) at 15% opacity. It must be felt, not seen.

---

## 5. Components

### Buttons (Tactile Cyan-Tech)
*   **Primary:** Fill with `primary_container` (#00E5FF). Corner radius `lg` (1rem). 
    *   *Hover:* Scale 1.02, add 15px `primary` bloom glow.
    *   *Pressed:* Scale 0.98, background shifts to `on_primary_fixed_variant`.
*   **Tertiary (Ghost):** No fill. `primary` text. Use a 1px "Ghost Border" that only reaches 100% opacity on hover.

### Input Fields
*   **Styling:** `surface_container_highest` fill. No bottom line.
*   **Focus State:** The container gains a 1px internal stroke of `primary` and a subtle 4px outer glow. Labels should use `label-sm` and sit exactly 4px above the input.

### Navigation (The Horizon Bar)
*   **Structure:** A persistent bottom bar using `surface_container_low` with a 24px backdrop blur.
*   **The "Play" Node:** The center action must be elevated. Use a circular `primary_container` background with a heavy 20px neon bloom.
*   **Indicators:** Active states are marked by a 2px tall `primary` line floating *above* the icon, not below.

### Cards & Lists
*   **Rule:** Zero dividers. 
*   **Separation:** Use `md` (0.75rem) vertical spacing. Group items by nesting them inside a `surface_container_low` wrapper. 
*   **Interactions:** List items should highlight with a subtle `surface_bright` flash on tap.

### Screen music control (header chrome)
*   **Presence:** Every shipped screen exposes a **music on/off** control in the **top bar** (trailing cluster, e.g. beside profile), per [`SCREEN-MUSIC-SPEC.md`](SCREEN-MUSIC-SPEC.md). Same touch target and glow discipline as other header actions; **active state** (muted) must be visually obvious (icon + optional subtle dim of the “signal” accent).
*   **Semantics:** The control reflects **global** persisted `audio.music_master_enabled` from [`CLIENT-SETTINGS-SPEC.md`](CLIENT-SETTINGS-SPEC.md) §6.7 — header and **SETUP → Audio** stay in sync.
*   **Theming:** Use `primary` / `on_surface` for the icon; do not rely on color alone — pair with filled vs outline icon variant where the icon set allows.

---

## 6. Do’s and Don'ts

### Do:
*   **Use Intentional Breath:** Leave significant "Void" (negative space) between major UI modules to prevent the screen from feeling cluttered.
*   **Embrace the Glow:** Use `primary` bloom for critical path actions, but keep it rare so it retains its "High-Tech" value.
*   **Layer Surfaces:** Always put a darker surface behind a lighter, more interactive one.

### Don't:
*   **Don't use pure black:** Use `surface_container_lowest` (#0A0E19) to maintain depth and color-grading.
*   **Don't use 100% opaque borders:** They break the "Glass" immersion. Always use reduced opacity for lines.
*   **Don't crowd typography:** If a screen feels busy, increase the line-height of `body-md` rather than shrinking the font size.