# Screen checklist (implementation vs refs)

Each row: implement in **`commonMain`** unless a **platform actual** is noted. Pair **`code.html`** with **`screen.png`** for layout.

| # | Screen | Stitch folder | Must include |
|---|--------|---------------|--------------|
| 1 | Splash | `splash_screen` | Globe/brand, tagline, Initialize CTA, footer status line, build label from config |
| 2 | Authentication | `authentication` | Identity + credential fields, primary CTA, create account path, server/status line |
| 3 | Role selection | `role_selection` | Three role cards (Human / Astronaut / Alien), perks copy, Initialize, protocol version |
| 4 | Dashboard / Home | `dashboard` | XP, rank progress, Play CTA, memory stability, current session, daily protocols list |
| 5 | World map gameplay | `world_map_gameplay` | HUD: timer, score preview, hint, map + pin, lock-in CTA, lat/lng/elv, bottom shell |
| 6 | Success overlay | `success_overlay` | Post-guess summary, precision, XP, navigation to full results / map |
| 7 | Final results | `final_results` | Mission score, tactical breakdown, level progression, **GLOBAL RANKS** hydrated from API, play again / share |
| 8 | Settings / protocol | `settings_protocol` | Profile block, security status, sliders, accessibility toggles, destructive actions styled per DESIGN |

## Overlays and modals (from spec text)

- **Game launch overlay**: mode/difficulty (Solo / Multi / AI)—implement as sheet/dialog **without** exceeding max navigation depth rule.

## Leaderboard-only entry

- **Leaderboard** tab can reuse rows/components from **final_results** “Global ranks” for consistency (single composable, two contexts).

## String and content

- **Microcopy** may evolve; keep strings in a **single resource layer** (Compose Multiplatform resources or typed `String` table) for future localization.
