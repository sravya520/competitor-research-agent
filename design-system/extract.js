// Extracts Ant Design's design tokens straight from the installed `antd` package.
// Run: node extract.js   (writes ./tokens/*)
const fs = require('fs');
const path = require('path');
// Must run before antd loads: wrap the style-hook factories so token functions are captured.
const utils = require('antd/lib/theme/util/genStyleUtils');
const captured = {};
const origHooks = utils.genStyleHooks;
utils.genStyleHooks = (comp, styleFn, getDefaultToken, ...rest) => {
  const key = Array.isArray(comp) ? comp[0] : comp;
  if (!(key in captured)) captured[key] = getDefaultToken;
  return origHooks(comp, styleFn, getDefaultToken, ...rest);
};
const origHook = utils.genComponentStyleHook;
utils.genComponentStyleHook = (comp, styleFn, getDefaultToken, ...rest) => {
  const key = Array.isArray(comp) ? comp[0] : comp;
  if (!(key in captured)) captured[key] = getDefaultToken;
  return origHook(comp, styleFn, getDefaultToken, ...rest);
};

const { theme } = require('antd');
const colors = require('@ant-design/colors');

const out = path.join(__dirname, 'tokens');
fs.mkdirSync(out, { recursive: true });
const write = (name, data) =>
  fs.writeFileSync(path.join(out, name), typeof data === 'string' ? data : JSON.stringify(data, null, 2));

const { defaultAlgorithm, darkAlgorithm, compactAlgorithm, defaultSeed, getDesignToken } = theme;

// --- Seed tokens (the few inputs everything else derives from)
write('seed.json', defaultSeed);

// --- Full derived token sets: seed -> map -> alias
const variants = {
  light: getDesignToken({ algorithm: defaultAlgorithm }),
  dark: getDesignToken({ algorithm: darkAlgorithm }),
  compact: getDesignToken({ algorithm: [defaultAlgorithm, compactAlgorithm] }),
  'dark-compact': getDesignToken({ algorithm: [darkAlgorithm, compactAlgorithm] }),
};
for (const [k, v] of Object.entries(variants)) write(`global.${k}.json`, v);

// --- Preset palettes: 10-step scale per color, light + dark
const presets = {};
for (const name of colors.presetPalettes ? Object.keys(colors.presetPalettes) : []) {
  presets[name] = {
    light: colors.presetPalettes[name],
    dark: colors.generate(colors.presetPrimaryColors[name], { theme: 'dark', backgroundColor: '#141414' }),
    primary: colors.presetPrimaryColors[name],
  };
}
write('palettes.json', presets);

// --- Component tokens. antd defines them inside genStyleHooks(name, styleFn, getDefaultToken).
// Wrap that factory before loading any component style so each token function is captured,
// then evaluate it against the global token set.
const libDir = path.dirname(require.resolve('antd/lib/index.js'));
const noToken = [];
const evalTokens = (globalToken) => {
  const res = {};
  for (const [name, fn] of Object.entries(captured)) {
    if (typeof fn !== 'function') { if (fn && typeof fn === 'object') res[name] = fn; continue; }
    try { res[name] = fn({ ...globalToken }); } catch (e) { noToken.push(`${name} (${e.message.split(String.fromCharCode(10))[0]})`); }
  }
  return res;
};
const components = evalTokens(variants.light);
write('components.light.json', components);
write('components.dark.json', evalTokens(variants.dark));
write('components.compact.json', evalTokens(variants.compact));

// --- Component inventory (every public component dir in the package)
const inventory = fs.readdirSync(libDir).filter(
  (d) => fs.statSync(path.join(libDir, d)).isDirectory() && !d.startsWith('_') && d !== 'style' && d !== 'theme' && fs.existsSync(path.join(libDir, d, 'index.js')),
);
write('component-inventory.json', { version: require('antd/package.json').version, components: inventory, withoutExtractableTokens: noToken });

console.log({
  version: require('antd/package.json').version,
  globalTokens: Object.keys(variants.light).length,
  palettes: Object.keys(presets).length,
  componentsWithTokens: Object.keys(components).length, captured: Object.keys(captured).length,
  inventory: inventory.length,
  noToken,
});
