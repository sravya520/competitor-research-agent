# DESIGN.md — rules for any UI change

Binding for humans and AI agents. **Read §0 for small tweaks; read only the section you touch for anything bigger.** Cite rules by ID (e.g. "per S3"). If a rule blocks the task, say so and propose an exception; don't silently break it.

**Light mode only for now.** Don't add dark styles or `prefers-color-scheme` overrides; dark tokens stay in `design-system/` for later (C5).

Source of values: `design-system/` (Ant Design v6 tokens + `spacing.css`). Never copy values from it into code. Reference variables (`var(--space-4)`, `var(--ant-color-primary)`). Don't open `design-system/tokens/*.json`; use `tokens.css` or grep one name.

---

## §0 Quick card

| Topic | Rule |
|---|---|
| Spacing | 8px grid. Use `--space-{2,4,6,8,12,16}`; 4px and 12px only as half-steps. Apply semantic aliases (`--stack-*`, `--inset-*`, `--cluster-*`), not raw steps. |
| Layout | Mobile-first (`min-width` queries). One column <768px. Reading width ≤ `--content-max`. |
| Color | Ant tokens only. No hex in components. Never color alone for meaning. Action color is `--ant-color-primary-active` (#0958d9), the AA-safe step (C2). |
| Type | Root 16px; UI text (labels, captions) 14px; prose 16px; inputs 16px on touch. Ant heading scale. One `h1`. |
| Targets | ≥ `--tap-min` (44px) on touch. Visible focus on everything interactive. |
| Contrast | WCAG AA: 4.5:1 text, 3:1 UI/large text. |
| Styling | No inline styles, no `style=` attributes. Classes in one stylesheet. |
| Widgets | Native Streamlit first. Custom HTML only if no native widget can do it. |
| Honesty | UI never shows more certainty than the evidence supports (P1). |
| Ethics | No dark patterns (X1). |
| Grouping | Space before lines. No borders or dividers to separate content; use whitespace and, rarely, a surface tint (R2). Borders only where they carry meaning (form controls, focus). |
| Marketing | Landing follows §15: one grotesk (Instrument Sans), near-black CTA, real photos + real product fragments, no borders, big jumps in type scale. |

Before finishing any UI change run the **checklist (§11)**.

---

## §1 Principles (tie-breakers, in order)

1. **Traceability over polish.** The product sells verifiable output. If a style choice hides a source, rejection or caveat, drop the style.
2. **Clarity over density.** One primary action per view. Reduce, don't decorate.
3. **Consistency over creativity.** Reuse a token/pattern before inventing one.
4. **Accessible by default.** AA is the floor, not a later pass.
5. **Calm.** Founders use this to decide things. No urgency, no celebration, no noise.

---

## §2 Spacing system

Defined in `design-system/spacing.css`. One knob: `--space-unit` (4px). Step N = N × 4px.

| Step | px | Role |
|---|---|---|
| `--space-1` | 4 | half-step: icon↔glyph, badge padding |
| `--space-2` | 8 | **grid**: tight gap, label→field |
| `--space-3` | 12 | half-step: compact list rows |
| `--space-4` | 16 | **grid**: default gap/padding |
| `--space-6` | 24 | **grid**: group gap, card padding |
| `--space-8` | 32 | **grid**: section gap |
| `--space-10` `-12` `-16` `-20` `-24` | 40 48 64 80 96 | **grid**: page regions, hero, empty states |

No step 5 (20px) or 7 (28px). Ant's 20px "MD" is intentionally not exposed.

Semantic aliases (use these):

| Alias | = | Use |
|---|---|---|
| `--inset-xs/sm/md/lg` | 8/16/24/32 | padding inside a container |
| `--stack-label` | 8 | label→field, heading→body |
| `--stack-field` | 16 | field→field |
| `--stack-group` | 24 | group→group within a card/form |
| `--stack-section` | 32 | section→section |
| `--stack-page` | 48 | major page regions |
| `--cluster-tight/base/loose` | 8/16/24 | horizontal gap (icon+text / buttons / chips) |
| `--gutter` | 16→24→32 | page side padding at <768 / ≥768 / ≥1200 |

**Rules**

- **S1** Every margin, padding and gap is a token. No literal px except `0`, `1px` borders, and `--tap-min`.
- **S2** Even steps by default. Odd steps (1, 3) only inside a single component, never between components.
- **S3** Space between siblings uses `gap` on the parent (`.stack`, `.cluster`). Don't put margins on children.
- **S4** Proximity encodes relation: gap *within* a group < gap *between* groups < gap between sections (`label` 8 < `field` 16 < `group` 24 < `section` 32). Never equal gaps at two levels.
- **S5** Nesting: inner inset ≤ outer inset. A card at `--inset-md` must not contain a box at `--inset-lg`.
- **S6** Vertical rhythm: gaps between text blocks follow `--stack-*`, not line-height hacks.
- **S7** Gutters come from `--gutter`; never hardcode page padding.
- **S8** Don't use spacing to fix alignment bugs. Fix the structure.
- **S9** Dense views (tables, logs) may drop one step (e.g. `--stack-field`→`--space-2`); say so in a comment. Never go below `--space-1`.
- **S10** Same component, same spacing everywhere. A spacing change is a token or alias change, not a per-use override.

Ant mapping (reference): 1=sizeXXS, 2=sizeXS, 3=sizeSM, 4=size, 6=sizeLG, 8=sizeXL, 12=sizeXXL.

---

## §3 Layout and responsiveness

- **L1** Mobile-first: base styles are the phone layout; add `@media (min-width: …)` only. Breakpoints are Ant screens: sm 576, md 768, lg 992, xl 1200, xxl 1600. No `max-width` queries, no new breakpoints.
- **L2** Test at 375, 768 and 1280 wide. No horizontal page scroll at any width.
- **L3** Single column by default. Multi-column only ≥768 and only for peer content (e.g. competitor cards), never for sequential steps.
- **L4** Max reading width `--content-max` (~65–75ch) for report text. Wide data may overflow-scroll inside its own container, not the page.
- **L5** Primary action placement: bottom of its form/section, left-aligned, full width on <576. Secondary actions sit after it, never before.
- **L6** Order = priority. Most important content first in DOM and visually; don't reorder with CSS in ways that desync tab/reading order.
- **L7** The flow is linear: input → progress → review → report. Show only the current stage's primary UI; earlier results collapse, they don't vanish (traceability).
- **L8** No sticky/fixed elements except the Streamlit header. They eat mobile viewport.
- **L9** Marketing pages (landing) use `--content-wide`; app pages use `--content-max`. A landing page has exactly one primary CTA (the hero); repeats are secondary. Every landing claim must be something the pipeline really does (P7); no stats, logos or testimonials without real data. Landing sections are `<section aria-labelledby>` with one `h1`.
- **L10** Gated pages show the sign-in/consent step *instead of* the page, never the page behind a lock. Header links are touch-sized (A5).

---

## §4 Color

- **C1** Only `--ant-color-*` tokens (or aliases of them). No hex/rgb in components.
- **C2** Semantic roles: `colorPrimary` = the single main action + links; `colorSuccess` / `colorWarning` / `colorError` / `colorInfo` for status; neutrals (`colorText`, `colorTextSecondary`, `colorBgContainer`, `colorBorder`) for everything else. One primary-colored button per view. **Action color deviates from Ant's default on purpose:** white on `#1677ff` is 4.1:1 (fails AA), so primary, links and focus use `--ant-color-primary-active` (#0958d9, 6.2:1). Status hues use the AA-passing palette step (see the `build-ui.js` report).
- **C3** Never convey meaning by color alone: pair with icon or text ("Corroborated across 3 sources", not just green).
- **C3a** Streamlit fades captions to 60% opacity (~4.3:1, fails AA). Captions are forced to `--ant-color-text-secondary` at full opacity in `ui/components.css`. Check any new faded/disabled text the same way.
- **C4** AA contrast: normal text ≥ 4.5:1, large text (≥24px or ≥19px bold) and UI boundaries/focus ≥ 3:1. Check dark theme too. `colorTextSecondary` is the lightest allowed body-text tone; `colorTextTertiary`/`Disabled` are not for essential text.
- **C5** **Light only for now.** `.streamlit/config.toml` pins `base = "light"` so the app ignores the OS theme. Still reference tokens (never assume white) so dark can return without a rewrite. Don't ship dark overrides until dark is re-enabled.
- **C6** Status colors are for status. Don't use `colorError` for emphasis or `colorSuccess` for decoration.
- **C8** Marketing palette is near-monochrome, all from Ant tokens: canvas `colorBgContainer`, one quiet surface `colorBgLayout`, text `colorText` / `colorTextSecondary`, one near-black (`colorText`) for the primary CTA and the single dark band. The only hues on the page are the product's own status colors inside real product fragments (green corroborated, gold single-source, red removed) and the AA-safe blue for links and focus. No glows, no gradients, no gradient text, no tinted "paper" backgrounds. Text on the dark band is a tint of white.
- **C7** Background layers: `colorBgLayout` (page) < `colorBgContainer` (cards) < `colorBgElevated` (popovers). Don't skip a layer to fake depth.

---

## §5 Typography

- **T1** Ant type scale only: `--ant-font-size-{sm,'',lg,xl}` and `--ant-font-size-heading-{1..5}`. No other sizes. This app's `h1` is heading-2 (30px) at all widths; sizes are set in the theme, not CSS.
- **T2** Root is 16px (`baseFontSize`). Labels/captions/UI text are 14px (Ant `fontSize`); prose 16px; **inputs 16px on touch** (`pointer: coarse`) to prevent iOS zoom. Don't set root to 14px: every `rem` shrinks (labels drop to 12px).
- **T3** Exactly one `h1` (the app title). Headings descend without skipping levels. Visual size ≠ semantic level; style with classes.
- **T4** Line-height: use `--ant-line-height` for body, `--ant-line-height-heading-*` for headings. Don't override per element.
- **T5** Weight: app UI uses regular + `--ant-font-weight-strong` only. Marketing (§15) also uses 500 for display headings. No italics for emphasis (use strong).
- **T6** App UI uses Ant's system stack. Marketing pages use **Instrument Sans** (variable, 400 to 700, one 30 KB woff2, SIL OFL), self-hosted in `static/fonts/` with `font-display: swap` and the system stack as fallback. Never load fonts from Google Fonts or any CDN (privacy, P-policy). Code/URLs use `--ant-font-family-code`.
- **T7** Line length ≤ ~75ch for prose. Long URLs wrap (`overflow-wrap: anywhere`), never overflow.
- **T8** Sentence case everywhere ("Generate report"). No ALL CAPS, no trailing "!".
- **T9** Marketing pages only: fluid display sizes `--l-d-xl` (hero, about 80px), `--l-d-l` (section, about 48px) at weight 500, line-height 1.0 to 1.08, tracking -0.035em to -0.04em; then a deliberate jump down to 18px/600 item titles and 17px/1.6 body. Nothing in between: no 24 to 30px "medium" headings. Eyebrows are 14px/500, sentence case (T8 applies; no uppercase labels). No serif, no italics, no decorative wordmark.

---

## §6 Shape, elevation, motion

- **R1** Radius: `--ant-border-radius` (6) default, `-sm` (4) for tags/inputs inside dense UI, `-lg` (8) for cards/containers. Marketing: buttons `lg * 1.5` (12), photo and visual panels `lg * 2` (16). No pills except tags/chips.
- **R2** Space before lines. Group with whitespace first (S4), a surface tint second (`--surface-card`, 98% lightness, defined in `design-system/spacing.css`; do not use `colorBgLayout` for cards), a border last and only when it carries meaning (input boundaries need 3:1, focus rings, the review checkbox). No divider lines between list items, FAQ rows or sections. Elevation (`--ant-box-shadow-*`) only for things that float above content: popovers, dialogs, and product fragments laid over a photo (§15 V4).
- **M1** Motion is functional: show state change or progress. ≤ `--ant-motion-duration-mid` (0.2s) for UI feedback. No decorative or looping animation (except the native progress indicator).
- **M2** Respect `prefers-reduced-motion: reduce`: remove transitions/animations.
- **M3** Never animate layout in a way that shifts content under the cursor/finger.
- **M4** Marketing motion may be expressive but must: use only `transform` and `opacity`; leave all content visible without JS; keep the hero entrance in CSS (no flash) and scroll effects in `static/landing.js` (GSAP) behind `gsap.matchMedia('(prefers-reduced-motion: no-preference)')`; stay under ~0.9s with the strong ease-out `cubic-bezier(0.23, 1, 0.32, 1)`; reveal once, never on every scroll; gate hover motion to `(hover: hover) and (pointer: fine)`; keep elements focusable (animate opacity, not `visibility`). Every animation states its purpose in a comment (pace, state, explanation, delight). No count-up on tiny numbers, no animation on the FAQ. Landing motion today: one CSS hero entrance, scroll reveals, and the flow connector drawing in (§15 V5).

---

## §7 Components

Prefer the native Streamlit widget. Wrap, don't fork. Each component below lists *must-haves*.

- **Form/inputs (`st.text_input`, `st.form`)** — visible label always (never placeholder-as-label). Optional fields say "(optional)"; required are default. Help text under the field, not in a tooltip alone (tooltips are not keyboard/touch friendly; tooltip may supplement). Field gap `--stack-field`; label→field `--stack-label`.
- **Primary button (`type="primary"`)** — one per view, verb-first label ("Research", "Generate report"). Disabled only with a visible reason; prefer enabled + validation message. Min height `--control-h`, ≥ `--tap-min` on touch.
- **Secondary/tertiary** — default button for secondary; plain link/text for tertiary. Destructive actions are never primary-styled and need an undo or confirm.
- **Status/progress (`st.status`)** — plain-language, present tense ("Researching competitors…"); update the label on completion; final state is `complete` or `error`, never left spinning. Details stream inside, collapsed by default once done.
- **Messages (`st.error/warning/info/success`)** — one message, what happened + what to do next. No jargon, no stack traces, no blame. Error = something failed; warning = proceed with care; info = neutral guidance. Not for decoration.
- **Cards / competitor items** — one level of nesting max. Title (strong) → one-line positioning → details in an expander. Sources are visible without extra clicks (P2).
- **Checkboxes (review list)** — label is the full row text; the checkbox hit area ≥ `--tap-min` tall; state not color-only.
- **Expanders** — title says what's inside ("Automatically excluded (2)"), includes count. Never hide the only path to a required action inside one.
- **Download button** — states format ("Download as Markdown"). Appears next to the thing it downloads.
- **Empty/error/loading** — every view has all three defined (§9). No blank screens.
- **Tables/long lists** — scroll inside their container (L4), header row sticky only inside that container.

New component? Check §7 and Ant's inventory (`design-system/tokens/component-inventory.json`) for an existing pattern before inventing. If new, add a bullet here in the same change.

---

## §8 Accessibility (WCAG 2.2 AA minimum)

- **A1** Every interactive element: keyboard reachable, logical tab order, visible focus ring ≥ 3:1 against its surroundings. Never `outline: none` without a replacement.
- **A2** Every input has a programmatic label (`label=` on Streamlit widgets; never empty or `label_visibility="collapsed"` without an `aria-label` equivalent). Icons-only buttons need an accessible name.
- **A3** Status that changes without focus (progress, errors) must be announced: use native `st.status/st.error` (live regions) or `role="status"` / `role="alert"`.
- **A4** Errors: say which field, what's wrong, how to fix. Keep input values on error.
- **A5** Target size ≥ 24×24 CSS px (AA); we ship ≥ 44 on touch (`--tap-min`).
- **A6** Don't rely on hover; everything hover reveals is reachable by focus/tap.
- **A7** Text resizes to 200% and reflows at 320px wide without loss (no fixed heights on text containers).
- **A8** Language: `lang` set; link text is meaningful ("Source: Crunchbase", never "click here"). Links that leave the app say so or open in the same tab by default.
- **A9** Respect `prefers-reduced-motion` and `prefers-color-scheme` (M2, C5).
- **A10** Images/graphics: informative ones have alt text; decorative ones are hidden from AT. Don't put essential text in images.

---

## §9 States and content

- **Loading** — within 100ms show something (button state or status). Name the step; never an unlabeled spinner. Long ops (30–90s here) show progressive steps.
- **Empty** — say why it's empty and the one next action ("No competitors passed verification. Try a more specific name or URL.").
- **Error** — plain language, next step, no internal terms (`429`, tracebacks). Distinguish "you can fix this" from "try later".
- **Success** — quiet. State the result ("4 competitors included, 1 excluded"); no confetti, no exclamation marks.
- **Copy** — verb-first buttons, sentence case, second person, ≤ ~20 words per message, no jargon (say "check", not "verify against corroboration thresholds"). Numbers as numerals. Same word for the same thing everywhere (competitor, source, excluded).
- **Destructive/irreversible** — state the consequence before the action and offer undo.

---

## §10 Product-specific rules (this app)

- **P1 Calibrated confidence.** UI must not look more certain than the evidence. Corroborated (2+ distinct domains), single-source, and no-source competitors must be visually and textually distinct (label text, not just color). Never hide "single-source" or flagged-problem labels.
- **P2 Sources are first-class.** A claim and its sources appear together. Don't collapse sources behind extra clicks in review or report.
- **P3 Rejections are shown.** Excluded competitors + reasons stay visible (collapsed with a count is fine). Never delete from view.
- **P4 Stopping is a feature.** "Identity ambiguous" is a designed state, not an error: explain why, give the single best next step (paste a URL). Calm tone, `warning` not `error`.
- **P5 Human stays in control.** The review step is mandatory; default actions are reversible; nothing is sent/published without an explicit click.
- **P6 Shared-quota reality.** The demo uses one shared API key; rate-limit messaging (429) is a normal state, written as such ("daily limit reached, try later"), never as a failure of the user.
- **P7 No fabricated polish.** Don't add metrics, scores, badges, testimonials or "AI-powered" flourishes that the pipeline doesn't produce.
- **P9 Consent is a choice.** Terms/Privacy and age confirmation are separate, unchecked, required checkboxes shown after sign-in, with both documents linked. Never pre-checked, never bundled into the sign-in click. Say what we store before asking (Account page shows it). Deleting an account is one screen and needs no email.
- **P8 Report is the product.** The output Markdown is the deliverable. UI chrome around it stays minimal; the download action is always adjacent.

---

## §11 Pre-merge checklist (copy into PR/commit notes if any item is N/A, say why)

1. All spacing from tokens/aliases (S1–S3); gaps ordered by relation (S4).
2. Works at 375 / 768 / 1280; no horizontal scroll (L2).
3. Light **and** dark OK; contrast checked (C4, C5).
4. Keyboard-only pass: tab order, focus ring, no traps (A1).
5. Labels, error text, live-region announcements present (A2–A4).
6. Touch targets ≥ 44px on touch (A5).
7. Loading / empty / error states exist and use §9 copy.
8. No inline styles, no hex, no new font sizes/weights/breakpoints (C1, T1, T5, L1). No borders used for grouping (R2); marketing pages pass §15 V10.
9. Honesty rules intact: confidence labels, sources, rejections visible (P1–P3).
10. `reduced-motion` honored; no decorative animation (M1, M2).

---

## §12 Anti-patterns (reject on sight)

- **X1 Dark patterns:** pre-checked consent/upsell, confirmshaming ("No, I don't want better results"), hidden or misdirecting cancel/close, fake urgency or scarcity, countdowns, nagging modals, forced sign-up for core function, disguised ads, buried opt-outs. *Allowed:* review checkboxes default-on **because removal is explicit, visible and reversible** (P5), not because it nudges.
- Placeholder as label · color-only status · icon-only buttons without a name · tooltips as the only help.
- Magic numbers (`margin-top: 13px`) · `!important` to win specificity · per-use spacing overrides (S10).
- Inline `style=`, hex colors, ad-hoc font sizes, new shadows.
- Custom HTML for something a native widget does.
- Vague errors ("Something went wrong"), jargon, blame.
- Decorative animation, auto-playing anything, content that moves under the cursor.
- Adding visual confidence the data doesn't have (P1, P7).

---

## §13 How the design system is applied (Streamlit, implemented)

```
design-system/tokens/*      -+
design-system/spacing.css    +- node design-system/build-ui.js -+- .streamlit/config.toml  theme: colors, font, radius, headings  (GENERATED)
ui/components.css (ours)    -+                                  +- ui/app.css              used tokens + spacing + components      (GENERATED)
moat_app.py loads ui/app.css via st.html("<style>...</style>") near the top
```

- **Never edit the generated files** (`.streamlit/config.toml`, `ui/app.css`). Change `design-system/build-ui.js` (theme), `design-system/spacing.css` (spacing) or `ui/components.css` (component rules), then run `node design-system/build-ui.js`. Restart Streamlit after theme changes; it reads `config.toml` only at startup. CSS changes hot-reload.
- **Theme first, CSS second.** Colors, font, radius, heading sizes and status hues live in the theme. CSS handles only what the theme can't: spacing, touch targets, focus, caption contrast, responsive widths.
- **Only `moat_app.py` imports Streamlit**; CSS loading stays there. UI changes never touch `pipeline.py`, `evaluate.py`, `prompts.py`, `tools.py`, `schemas.py`.
- **Selectors: `data-testid` only** (`stForm`, `stAlertContainer`, `stBaseButton-*`), never hashed `st-emotion-cache-*`. Re-check after a Streamlit upgrade. Style the element that *paints* the box (`stAlertContainer`), not its wrapper (`stAlert`), or padding doubles.
- **Streamlit shrink-wraps button containers.** Widen the `stElementContainer` with `:has(...)`, not just the button.
- **Spacing:** native gaps are already 16px (`--stack-field`). Use `.stack`/`.cluster` only inside custom HTML.
- **No inline styles.** Don't use `st.markdown("<div style=...>")`. Add a class in `ui/components.css`.
- **Verify:** run the app on port 4000 and check §11 at 375/768/1280, light only. Review/ambiguous/error states need seeded session state: use a throwaway harness outside the repo; don't add test hooks to `moat_app.py`.
- **`st.html` sanitizer:** it strips inline `<svg>` (use CSS-mask icons, see `.i-check` in `ui/landing.css`) and drops the **entire** `<style>` block if the CSS contains a `<` character, even inside a comment. Keep angle brackets out of every CSS file; `app.css` is checked with `grep -c '<' ui/app.css` (must print 0).
- **JS:** `st.html(..., unsafe_allow_javascript=True)` with a `<script src>` pointing at `/app/static/...` (static serving is enabled by `build-ui.js`). Third-party libraries are vendored under `static/vendor/` (GSAP, see its NOTICE.md); never load from a CDN, which would leak visitor IPs and make the Privacy Policy untrue. Streamlit scrolls `[data-testid="stMain"]`, not the window: ScrollTrigger needs `scroller: main`.
- **Landing files:** markup `ui/landing.html` (placeholders `{{RUNS}}`, `{{YEAR}}`, `{{OPERATOR}}`, `{{CONTACT}}` filled by `views/landing.py`), styles `ui/landing.css` (bundled by `build-ui.js`), motion `static/landing.js`. Sample data on the page must come from `example-report.md` (P7).
- **Generator checks:** `build-ui.js` prints a WCAG AA report (primary, borders, status hues). If a new Ant default fails 4.5:1 / 3:1, add the pick in the generator and note it in C2.

---

## §15 Marketing visual language (landing, decided 2026-10-28)

Direction: **plain proof**. A calm, near-monochrome page where the only "decoration" is the product's real output and real photographs. Measured from five references:

| Reference | Measured | Rule it became |
|---|---|---|
| near.com | One grotesk at 500, 60px/1.0, -1.5px; gray 18/28 body; one near-black 48px CTA, radius 12; real UI as hero | V1, V2, V6 |
| pallyy.com | Real photographs (people at work), 3:2, unrounded | V3 |
| rulebase.co | Regular weight, tight tracking (-0.033em), 100 to 120px section padding; UI cards laid over a tactile material photo | V2, V4, V7 |
| workos.com/atlas | 1 bordered element out of 988; grouping by space and one faint band; 84px display jumping straight to 16px labels | V7, T9 |
| orshot.com | Numbered flow (1, 2, 3) of real UI fragments joined by connector lines; 16px icons at 1.25 to 1.5 stroke, sometimes in small tiles | V5, V8 |

- **V1 One voice.** Instrument Sans only (T6). Display at 500, never bold 700 for headlines. Left-aligned hero and section heads; center only the final CTA.
- **V2 Restraint in color.** C8. The primary CTA is near-black with white text (48px tall, radius 12); secondary actions are text links with an arrow. One primary per view (L9) still holds.
- **V3 Real images, honestly used.** Only licensed photos (Unsplash License or owned) or public-domain artwork (the hero is Friedrich's *The Monk by the Sea*, a minimal landscape painting), self-hosted in `static/img/` with `width`/`height` set, `loading="lazy"` below the fold, and real alt text. Photos set context (records, checking, deciding); they never show people presented as customers, and never sit next to a quote (P7). No photo credits on the page (the Unsplash License does not require them); sources are recorded in `static/img/CREDITS.md`. Never use Unsplash+ or other paid images.
- **V4 Product on a photo.** The hero is a photograph with real product fragments floating on it (white cards, `--ant-box-shadow-secondary`). Fragments use real sample data from `example-report.md` (P7), so the visual *is* the proof.
- **V5 Show the pipeline as a flow.** "How it works" is a numbered sequence of real UI fragments joined by a connector, not a card grid. The connector may draw in on scroll (M4).
- **V6 Copy is short.** Headline at most 8 words, subhead at most 25, item text at most 15. Say what happens, never "AI-powered", "seamless", "unlock".
- **V7 Space is the structure.** Section padding `--space-16` on phones, `--space-32` from 992px. Within a section: heading to body `--space-4`, body to content `--space-12`. No borders (R2); a section may sit on the `--surface-card` surface instead.
- **V8 Icons are quiet.** One family, 20px, 1.5 stroke, drawn as CSS masks (sanitizer, §13), in `currentColor`. Use them to label list items or sit in a 40px `colorBgLayout` tile; never as large decorations above every heading.
- **V9 One dark moment.** At most one near-black band per page (the closing CTA), radius 16, white-tinted text.
- **V10 Not a template.** Before shipping, check the frontend-design "AI slop" list: no serif-on-cream editorial pastiche, no glow blobs, no identical icon-card grids, no big-number stat strips, no footnote gimmicks.
- **V11 Sign-in is one quiet column.** Brand mark top left, a short heading, one white outlined Google button (G at left, outline passes 3:1), fine print, legal links at the foot. No email field (not supported), no side panel. Styles in `ui/signin.css`; tokens only.
- **V12 Pills are fully round** (`--radius-pill`, 9999px) for tags and status chips. **Landing body width** is `--content-wide` 1196px. **Logo** is the two-circle mark `static/brand/mark.svg` (no tile); the favicon is the same shape.
- **V13 Workspace, not chat.** Signed-in pages have a left rail (brand, New research, Recent, then Account and Sign out at the bottom) and no top bar. The home screen is one plain question, a floating composer (company name and website side by side, the chosen method attached underneath like a file) and a 3-column grid of method cards. Selected card = 2px ink ring + check (the only border), unbuilt methods = muted with a Soon pill. Styles in `ui/workspace.css`.

---

## §14 Changing this file

Add/alter a rule in the same change that needs it; give it an ID; keep §0 and §11 in sync. Keep rules testable ("≥ 44px", "one h1") not aspirational. This file should stay under ~300 lines. If it grows, split by section into `design/*.md` and keep §0 + an index here.

## 16. Sharp system (supersedes the soft rules in sections 7 and 15 where they conflict)

Source of direction: Neon's site and the Spectr DesignMD (https://designmd.me/discover/spectr/raw), applied to OUR palette (near-black ink on white, Ant status hues, no purple). Light mode only. Layer: `ui/neon.css`, bundled last.

**Shape.** Radius is 0 everywhere: buttons, cards, inputs, tags, images, the Streamlit theme (`baseRadius = "none"`). `--l-r-btn`, `--l-r-panel`, `--radius-pill` and `--ant-border-radius*` are all 0. Round shapes are not used. To bring round tags back, change `--radius-pill` only.

**Structure.** Hairlines define structure (Spectr cards, Neon dividers): `--l-hair` (14% ink) for cards and rows, `--l-hair-strong` (28%) for the composer, a 2px ink ring only for a chosen method. Surfaces are flat colour blocks; the single shadow tier is for things that float over a photo.

**Type.** Inter (variable, self-hosted) for text, JetBrains Mono for labels. Text never lighter than 500. Display and headings 600 with tight tracking (-0.04em display, -0.02em headings), line-height 1.05 to 1.2. Labels (eyebrows, tags, chips, rail headings, table heads, the loader log): mono, 12px, uppercase, 0.08em tracking. Fields and placeholders: 14px placeholder, 500 weight. The Streamlit theme loads the same fonts (`[[theme.fontFaces]]` in the generated config).

**Colour.** Unchanged. Streamlit's primary colour is now the ink (`primaryColor`), so checkboxes and focus follow the brand.

**Spacing.** 4px grid, even steps (section 2). Cards pad 16 to 32, the loader panel 32.

**Loading screen (`.ld-*`, `views/tool.py::_progress`).** One panel: a pulsing ink square and mono "RESEARCHING", the current activity as a large shimmering sentence, three steps (identify, find competitors, verify and check sources) as hollow, pulsing or checked squares, a mono activity log (newest line fades in), and elapsed time. The animated header is a separate element so polling does not restart its pulse. Reduced motion: no pulse, no shimmer.

**Report tabs (`views/tool.py::_report`, `.st-key-report` in `ui/neon.css`).** The report Markdown is split at its `## ` headings, one tab each, in report order: Overview (the researched company's basics; never "My company", the company may be someone else's), Competitors (N), Market trends, Opportunities, Threats, Excluded, Sources, Limitations. The Download button stays above the tabs because it saves the whole report. Mono uppercase labels, hairline under the list, 2px ink bar under the open tab, panel fades in (opacity only). On phones the tab list scrolls sideways with no visible scrollbar. The page is 69rem wide (60rem + 15%).

**Disabled buttons.** A disabled filled button (primary or secondary) is a hatched surface with a hairline, faded ink and a not-allowed cursor; a disabled tertiary is struck through. Never "pale block" alone: that reads as tertiary.

**Secondary button.** Onboarding's Skip is `type="secondary"`: white, 1px `--l-hair-strong` outline, ink text, so it reads as a real choice beside the primary.

**Left rail never scrolls.** One screen tall (`100dvh - space-32`), the Recent list takes the leftover space and fades out where it is clipped, the footer stays pinned; below 620px height the email and legal links are hidden. Scrollbars are hidden.

**Landing when signed in.** The nav shows the account (Google photo, square, with the first-name initial underneath as fallback, plus first name) instead of "Try it free"; the other CTAs read "Open Moat".

Do: keep colours from the Ant tokens. Don't: add radius, add a second accent colour, use weights under 500 for text, or animate layout properties.

## 17. Motion (ui/motion.css, static/landing.js)

Rule: an animation ships only if it has a named purpose (feedback, state change, spatial continuity, preventing a jarring change) and is not on a path used hundreds of times a day. Only `transform` and `opacity` move (an accordion also animates height, which has no transform equivalent). Curve `cubic-bezier(0.23, 1, 0.32, 1)` (strong ease-out), never ease-in. Press 120ms, state change 180ms, entrance 180 to 240ms. Hover motion is gated by `(hover: hover) and (pointer: fine)`. Reduced motion collapses durations globally (components.css) and leaves end states.

| Surface | Decision | Why |
|---|---|---|
| Buttons (all) | Press scale 0.97 (0.985 for quiet text buttons), colour and enabled-state ease 180ms | Feedback; "Start research" turning on must be seen |
| Method cards | Press scale 0.985, chosen ring grows 1px to 2px, check pops in | Feedback and state; tens of times a day, so tiny |
| Method chip | Pops in from the left at the composer | Spatial continuity: the card sent it there |
| Sign-in, consent, onboarding | Column rises 6px and fades, 40ms stagger | A screen change; rare, so it can be noticed |
| Workspace home | Question, composer, then methods arrive 40ms apart | First impression of the product |
| Research page | Header, loader panel and review blocks rise in a short stagger | Result replaces the loader; stops it teleporting |
| Loader | Pulse, shimmer (exists); new "now" line fades; step check pops | State change |
| Alerts and warnings | Rise 6px, 180ms | Preventing a jarring change |
| Landing lanes | A name moving to "Removed by you" pops in | Spatial: shows where it went |
| Landing FAQ and sample rows | Open and close with the height | Preventing a jarring change |
| Landing hero and scroll reveals | Shortened to 450ms (were 700ms) | Quick and subtle |
| Download button | Label crossfades to "Saved" for 1.6s | Feedback |
| Streamlit stale dim | Turned OFF | Its 1s fade made fast reruns feel slow |

Rejected, on purpose: the left rail (navigated tens of times a day, no entrance), hover lifts on cards, parallax and scroll-linked effects, counters, background motion, anything keyboard-driven, page transitions between rail items, exit animations for removed rows (the browser cannot animate display none without extra machinery; entrances carry the meaning).
