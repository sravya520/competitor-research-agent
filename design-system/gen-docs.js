// Generates README.md from the extracted token data so the docs can't drift from antd.
// Run after extract.js: node gen-docs.js
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, 'tokens');
const read = (f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
const light = read('global.light.json');
const dark = read('global.dark.json');
const seed = read('seed.json');
const palettes = read('palettes.json');
const comps = read('components.light.json');
const inv = read('component-inventory.json');

const kebab = (s) => s.replace(/([a-z0-9])([A-Z])/g, '$1-$2').replace(/([a-zA-Z])(\d)/g, '$1-$2').toLowerCase();
const v = (k) => `\`--ant-${kebab(k)}\``;
const table = (head, rows) =>
  [`| ${head.join(' | ')} |`, `|${head.map(() => '---').join('|')}|`, ...rows.map((r) => `| ${r.join(' | ')} |`)].join('\n');
const show = (k, x) => {
  if (typeof x !== 'number') return String(x).replace(/\s+/g, ' ');
  if (/^motionDuration/.test(k)) return `${x}s`;
  if (/^(lineHeight|fontWeight|opacity|zIndex)/.test(k)) return String(x);
  return `${x}px`;
};
const pick = (keys, src = light) => keys.filter((k) => k in src).map((k) => [`\`${k}\``, v(k), `\`${show(k, src[k])}\``]);

const prim = (o) => Object.entries(o).filter(([, x]) => ['string', 'number', 'boolean'].includes(typeof x)).length;
const compRows = Object.entries(comps)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([name, t]) => [name, String(Object.keys(t).length)]);

const md = `# Ant Design — design system import

Official [Ant Design](https://ant.design) **v${inv.version}** tokens, extracted programmatically from the installed \`antd\` package (not copied by hand). Reference only: nothing in the app imports this folder, so the current UI is unchanged.

## What's here

| Path | Contents |
|---|---|
| \`tokens/tokens.css\` | ${Object.keys(light).length} global tokens as \`--ant-*\` CSS variables. Light by default; dark via \`[data-theme="dark"]\` or \`prefers-color-scheme\`. |
| \`tokens/seed.json\` | ${Object.keys(seed).length} **seed tokens** — the inputs everything else derives from. |
| \`tokens/global.{light,dark,compact,dark-compact}.json\` | Full derived token sets (seed → map → alias) for each algorithm. |
| \`tokens/components.{light,dark,compact}.json\` | **Component tokens** for ${Object.keys(comps).length} components, evaluated against the global tokens. |
| \`tokens/palettes.json\` | ${Object.keys(palettes).length} preset colors, each a 10-step scale (light and dark). |
| \`tokens/component-inventory.json\` | All ${inv.components.length} public components in the package. |
| \`spacing.css\` | **Our** spacing system on top of Ant's 4px unit: primitives, semantic aliases, responsive gutters, layout helpers. Rules in \`../DESIGN.md\` §2. |
| \`build-ui.js\` | Applies the tokens to the app (light only): generates \`../.streamlit/config.toml\` and \`../ui/app.css\`, with a WCAG AA report. |\n| \`extract.js\`, \`gen-css.js\`, \`gen-docs.js\` | Regenerate everything: \`npm i && node extract.js && node gen-css.js && node gen-docs.js\` |

## Token layers

1. **Seed** — raw choices: \`colorPrimary\`, \`borderRadius\`, \`fontSize\`, \`sizeUnit\`, \`controlHeight\`, motion base.
2. **Map** — algorithm output: the 10-step color scales, size/spacing steps, radius and font-size scales. Algorithms: default, dark, compact (combinable).
3. **Alias** — semantic names components use: \`colorText\`, \`colorBgContainer\`, \`colorBorder\`, \`colorError\`…
4. **Component** — per-component overrides (\`Button.primaryShadow\`, \`Table.headerBg\`…), derived from the alias layer.

Change a seed and every layer below recomputes. That is the point of the system.

## Spacing

Base unit is **${light.sizeUnit}px** (\`sizeUnit\`), not 8px. Steps are multiples of it, so it nests inside an 8px grid but also allows 4/12/20px.

${table(['Step', 'Size / margin / padding', 'Value'], [
  ['XXS', 'sizeXXS · marginXXS · paddingXXS', `${light.sizeXXS}px`],
  ['XS', 'sizeXS · marginXS · paddingXS', `${light.sizeXS}px`],
  ['SM', 'sizeSM · marginSM · paddingSM', `${light.sizeSM}px`],
  ['base', 'size · margin · padding', `${light.size}px`],
  ['MD', 'sizeMD · marginMD · paddingMD', `${light.sizeMD}px`],
  ['LG', 'sizeLG · marginLG · paddingLG', `${light.sizeLG}px`],
  ['XL', 'sizeXL · marginXL · paddingXL', `${light.sizeXL}px`],
  ['XXL', 'sizeXXL · marginXXL', `${light.sizeXXL}px`],
])}

Variables: \`--ant-size-*\`, \`--ant-margin-*\`, \`--ant-padding-*\`.

## Typography

${table(['Token', 'Variable', 'Value'], pick(['fontSizeSM', 'fontSize', 'fontSizeLG', 'fontSizeXL', 'fontSizeHeading5', 'fontSizeHeading4', 'fontSizeHeading3', 'fontSizeHeading2', 'fontSizeHeading1', 'lineHeight', 'lineHeightHeading1', 'fontWeightStrong']))}

Font stack: \`${show('fontFamily', light.fontFamily)}\`. Code: \`${show('fontFamilyCode', light.fontFamilyCode)}\`.

## Shape, controls, breakpoints, motion, layering

${table(['Token', 'Variable', 'Value'], pick([
  'borderRadiusXS', 'borderRadiusSM', 'borderRadius', 'borderRadiusLG', 'lineWidth',
  'controlHeightXS', 'controlHeightSM', 'controlHeight', 'controlHeightLG',
  'screenXS', 'screenSM', 'screenMD', 'screenLG', 'screenXL', 'screenXXL',
  'motionDurationFast', 'motionDurationMid', 'motionDurationSlow', 'motionEaseInOut', 'motionEaseOut',
  'zIndexBase', 'zIndexPopupBase', 'opacityLoading',
]))}

Elevation: \`boxShadow\`, \`boxShadowSecondary\`, \`boxShadowTertiary\` → \`--ant-box-shadow*\`.

## Color

Seed colors: ${['colorPrimary', 'colorSuccess', 'colorWarning', 'colorError', 'colorInfo'].map((k) => `\`${k}\` ${seed[k] || light[k]}`).join(' · ')}.

Neutrals and semantics (light → dark):

${table(['Token', 'Light', 'Dark'], ['colorText', 'colorTextSecondary', 'colorTextTertiary', 'colorTextDisabled', 'colorBgLayout', 'colorBgContainer', 'colorBgElevated', 'colorBorder', 'colorBorderSecondary', 'colorFill', 'colorPrimary', 'colorPrimaryBg', 'colorPrimaryHover', 'colorPrimaryActive', 'colorLink', 'colorSuccess', 'colorWarning', 'colorError'].map((k) => [`\`${k}\``, `\`${light[k]}\``, `\`${dark[k]}\``]))}

Preset palettes (10-step scales in \`palettes.json\`): ${Object.keys(palettes).join(', ')}.

## Components (${inv.components.length} in package)

${inv.components.map((c) => `\`${c}\``).join(' · ')}

Component tokens extracted (${compRows.length}); count is number of tokens per component:

${table(['Component', 'Tokens'], compRows)}

## Using it later

- **Plain CSS / Streamlit:** link \`tokens/tokens.css\` and use \`var(--ant-color-primary)\` etc.
- **React:** \`npm i antd\`, wrap in \`<ConfigProvider theme={{ token: { colorPrimary: '…' }, algorithm: theme.darkAlgorithm }}>\` — same system, live.
- **Tailwind:** map \`theme.extend\` colors/spacing/radius to the \`--ant-*\` variables.
- Note: this repo is a Streamlit (Python) app; Ant Design components are React, so only tokens apply directly. Wiring them into the UI is a separate step.
`;

fs.writeFileSync(path.join(__dirname, 'README.md'), md);
console.log('README.md written,', md.length, 'chars');
