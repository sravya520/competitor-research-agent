// Turns tokens/global.{light,dark}.json into tokens/tokens.css (CSS custom properties).
// Run after extract.js: node gen-css.js
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, 'tokens');
const read = (f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
const kebab = (s) => s.replace(/([a-z0-9])([A-Z])/g, '$1-$2').replace(/([a-zA-Z])(\d)/g, '$1-$2').toLowerCase();

// Numeric tokens that are lengths (px) vs unitless/other
const UNITLESS = /^(lineHeight|lineHeightHeading|lineHeightSM|lineHeightLG|lineHeightHeading\d|fontWeight|fontWeightStrong|opacity|motion$|motionBase|motionUnit|zIndex|screen|wireframe|colorBgMask$)/;
const SECONDS = /^motionDuration/;

const fmt = (key, v) => {
  if (typeof v === 'number') {
    if (SECONDS.test(key)) return `${v}s`;
    if (/^(lineHeight|fontWeight|opacity|zIndex|motion(Base|Unit)|screen)/.test(key) && !/^screen.*$/.test(key)) return String(v);
    if (/^screen/.test(key)) return `${v}px`;
    if (/^fontHeight|^fontSizeIcon|^size|^margin|^padding|^control|^border|^line(Width|Type)|^font/.test(key) || /Radius|Height|Width|Offset|Size|Indent/.test(key)) return `${v}px`;
    return String(v);
  }
  if (typeof v === 'boolean') return v ? '1' : '0';
  return String(v);
};

const block = (selector, tokens) => {
  const lines = Object.entries(tokens)
    .filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v))
    .map(([k, v]) => `  --ant-${kebab(k)}: ${fmt(k, v)};`);
  return `${selector} {\n${lines.join('\n')}\n}\n`;
};

const light = read('global.light.json');
const dark = read('global.dark.json');
const css =
  `/* Ant Design design tokens as CSS variables — generated from antd by extract.js + gen-css.js.\n   Light is default; dark applies under [data-theme="dark"] or prefers-color-scheme. */\n` +
  block(':root', light) +
  `\n` + block(':root[data-theme="dark"]', dark) +
  `\n@media (prefers-color-scheme: dark) {\n` +
  block(':root:not([data-theme="light"])', dark).replace(/^/gm, '  ').replace(/^ {2}$/gm, '') +
  `}\n`;

fs.writeFileSync(path.join(dir, 'tokens.css'), css);
console.log('tokens.css', Object.keys(light).length, 'vars/theme');
