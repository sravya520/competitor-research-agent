# Ant Design — design system import

Official [Ant Design](https://ant.design) **v6.6.8** tokens, extracted programmatically from the installed `antd` package (not copied by hand). Reference only: nothing in the app imports this folder, so the current UI is unchanged.

## What's here

| Path | Contents |
|---|---|
| `tokens/tokens.css` | 536 global tokens as `--ant-*` CSS variables. Light by default; dark via `[data-theme="dark"]` or `prefers-color-scheme`. |
| `tokens/seed.json` | 47 **seed tokens** — the inputs everything else derives from. |
| `tokens/global.{light,dark,compact,dark-compact}.json` | Full derived token sets (seed → map → alias) for each algorithm. |
| `tokens/components.{light,dark,compact}.json` | **Component tokens** for 60 components, evaluated against the global tokens. |
| `tokens/palettes.json` | 14 preset colors, each a 10-step scale (light and dark). |
| `tokens/component-inventory.json` | All 77 public components in the package. |
| `spacing.css` | **Our** spacing system on top of Ant's 4px unit: primitives, semantic aliases, responsive gutters, layout helpers. Rules in `../DESIGN.md` §2. |
| `build-ui.js` | Applies the tokens to the app (light only): generates `../.streamlit/config.toml` and `../ui/app.css`, with a WCAG AA report. |
| `extract.js`, `gen-css.js`, `gen-docs.js` | Regenerate everything: `npm i && node extract.js && node gen-css.js && node gen-docs.js` |

## Token layers

1. **Seed** — raw choices: `colorPrimary`, `borderRadius`, `fontSize`, `sizeUnit`, `controlHeight`, motion base.
2. **Map** — algorithm output: the 10-step color scales, size/spacing steps, radius and font-size scales. Algorithms: default, dark, compact (combinable).
3. **Alias** — semantic names components use: `colorText`, `colorBgContainer`, `colorBorder`, `colorError`…
4. **Component** — per-component overrides (`Button.primaryShadow`, `Table.headerBg`…), derived from the alias layer.

Change a seed and every layer below recomputes. That is the point of the system.

## Spacing

Base unit is **4px** (`sizeUnit`), not 8px. Steps are multiples of it, so it nests inside an 8px grid but also allows 4/12/20px.

| Step | Size / margin / padding | Value |
|---|---|---|
| XXS | sizeXXS · marginXXS · paddingXXS | 4px |
| XS | sizeXS · marginXS · paddingXS | 8px |
| SM | sizeSM · marginSM · paddingSM | 12px |
| base | size · margin · padding | 16px |
| MD | sizeMD · marginMD · paddingMD | 20px |
| LG | sizeLG · marginLG · paddingLG | 24px |
| XL | sizeXL · marginXL · paddingXL | 32px |
| XXL | sizeXXL · marginXXL | 48px |

Variables: `--ant-size-*`, `--ant-margin-*`, `--ant-padding-*`.

## Typography

| Token | Variable | Value |
|---|---|---|
| `fontSizeSM` | `--ant-font-size-sm` | `12px` |
| `fontSize` | `--ant-font-size` | `14px` |
| `fontSizeLG` | `--ant-font-size-lg` | `16px` |
| `fontSizeXL` | `--ant-font-size-xl` | `20px` |
| `fontSizeHeading5` | `--ant-font-size-heading-5` | `16px` |
| `fontSizeHeading4` | `--ant-font-size-heading-4` | `20px` |
| `fontSizeHeading3` | `--ant-font-size-heading-3` | `24px` |
| `fontSizeHeading2` | `--ant-font-size-heading-2` | `30px` |
| `fontSizeHeading1` | `--ant-font-size-heading-1` | `38px` |
| `lineHeight` | `--ant-line-height` | `1.5714285714285714` |
| `lineHeightHeading1` | `--ant-line-height-heading-1` | `1.2105263157894737` |
| `fontWeightStrong` | `--ant-font-weight-strong` | `600` |

Font stack: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji'`. Code: `'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace`.

## Shape, controls, breakpoints, motion, layering

| Token | Variable | Value |
|---|---|---|
| `borderRadiusXS` | `--ant-border-radius-xs` | `2px` |
| `borderRadiusSM` | `--ant-border-radius-sm` | `4px` |
| `borderRadius` | `--ant-border-radius` | `6px` |
| `borderRadiusLG` | `--ant-border-radius-lg` | `8px` |
| `lineWidth` | `--ant-line-width` | `1px` |
| `controlHeightXS` | `--ant-control-height-xs` | `16px` |
| `controlHeightSM` | `--ant-control-height-sm` | `24px` |
| `controlHeight` | `--ant-control-height` | `32px` |
| `controlHeightLG` | `--ant-control-height-lg` | `40px` |
| `screenXS` | `--ant-screen-xs` | `480px` |
| `screenSM` | `--ant-screen-sm` | `576px` |
| `screenMD` | `--ant-screen-md` | `768px` |
| `screenLG` | `--ant-screen-lg` | `992px` |
| `screenXL` | `--ant-screen-xl` | `1200px` |
| `screenXXL` | `--ant-screen-xxl` | `1600px` |
| `motionDurationFast` | `--ant-motion-duration-fast` | `0.1s` |
| `motionDurationMid` | `--ant-motion-duration-mid` | `0.2s` |
| `motionDurationSlow` | `--ant-motion-duration-slow` | `0.3s` |
| `motionEaseInOut` | `--ant-motion-ease-in-out` | `cubic-bezier(0.645, 0.045, 0.355, 1)` |
| `motionEaseOut` | `--ant-motion-ease-out` | `cubic-bezier(0.215, 0.61, 0.355, 1)` |
| `zIndexBase` | `--ant-z-index-base` | `0` |
| `zIndexPopupBase` | `--ant-z-index-popup-base` | `1000` |
| `opacityLoading` | `--ant-opacity-loading` | `0.65` |

Elevation: `boxShadow`, `boxShadowSecondary`, `boxShadowTertiary` → `--ant-box-shadow*`.

## Color

Seed colors: `colorPrimary` #1677ff · `colorSuccess` #52c41a · `colorWarning` #faad14 · `colorError` #ff4d4f · `colorInfo` #1677ff.

Neutrals and semantics (light → dark):

| Token | Light | Dark |
|---|---|---|
| `colorText` | `rgba(0,0,0,0.88)` | `rgba(255,255,255,0.85)` |
| `colorTextSecondary` | `rgba(0,0,0,0.65)` | `rgba(255,255,255,0.65)` |
| `colorTextTertiary` | `rgba(0,0,0,0.45)` | `rgba(255,255,255,0.45)` |
| `colorTextDisabled` | `rgba(0,0,0,0.25)` | `rgba(255,255,255,0.25)` |
| `colorBgLayout` | `#f5f5f5` | `#000000` |
| `colorBgContainer` | `#ffffff` | `#141414` |
| `colorBgElevated` | `#ffffff` | `#1f1f1f` |
| `colorBorder` | `#d9d9d9` | `#424242` |
| `colorBorderSecondary` | `#f0f0f0` | `#303030` |
| `colorFill` | `rgba(0,0,0,0.15)` | `rgba(255,255,255,0.18)` |
| `colorPrimary` | `#1677ff` | `#1668dc` |
| `colorPrimaryBg` | `#e6f4ff` | `#15325b` |
| `colorPrimaryHover` | `#4096ff` | `#3c89e8` |
| `colorPrimaryActive` | `#0958d9` | `#1554ad` |
| `colorLink` | `#1677ff` | `#1668dc` |
| `colorSuccess` | `#52c41a` | `#49aa19` |
| `colorWarning` | `#faad14` | `#d89614` |
| `colorError` | `#ff4d4f` | `#dc4446` |

Preset palettes (10-step scales in `palettes.json`): red, volcano, orange, gold, yellow, lime, green, cyan, blue, geekblue, purple, magenta, grey, pink.

## Components (77 in package)

`affix` · `alert` · `anchor` · `app` · `auto-complete` · `avatar` · `back-top` · `badge` · `border-beam` · `breadcrumb` · `button` · `calendar` · `card` · `carousel` · `cascader` · `checkbox` · `col` · `collapse` · `color-picker` · `config-provider` · `date-picker` · `descriptions` · `divider` · `drawer` · `dropdown` · `empty` · `flex` · `float-button` · `form` · `grid` · `image` · `input` · `input-number` · `layout` · `list` · `listy` · `locale` · `masonry` · `mentions` · `menu` · `message` · `modal` · `notification` · `pagination` · `popconfirm` · `popover` · `progress` · `qr-code` · `qrcode` · `radio` · `rate` · `result` · `row` · `segmented` · `select` · `skeleton` · `slider` · `space` · `spin` · `splitter` · `statistic` · `steps` · `switch` · `table` · `tabs` · `tag` · `time-picker` · `timeline` · `tooltip` · `tour` · `transfer` · `tree` · `tree-select` · `typography` · `upload` · `version` · `watermark`

Component tokens extracted (60); count is number of tokens per component:

| Component | Tokens |
|---|---|
| Affix | 1 |
| Alert | 4 |
| Anchor | 2 |
| App | 0 |
| Avatar | 12 |
| BackTop | 1 |
| Badge | 9 |
| Breadcrumb | 7 |
| Button | 58 |
| Calendar | 27 |
| Card | 13 |
| Carousel | 8 |
| Cascader | 8 |
| Collapse | 10 |
| DatePicker | 45 |
| Descriptions | 10 |
| Divider | 3 |
| Drawer | 4 |
| Dropdown | 7 |
| Flex | 0 |
| FloatButton | 0 |
| Form | 11 |
| Grid | 0 |
| Image | 6 |
| Input | 18 |
| InputNumber | 29 |
| Layout | 19 |
| List | 11 |
| Listy | 2 |
| Mentions | 22 |
| Message | 3 |
| Modal | 19 |
| Notification | 3 |
| Pagination | 30 |
| Popconfirm | 1 |
| Popover | 12 |
| Progress | 6 |
| QRCode | 1 |
| Radio | 16 |
| Rate | 7 |
| Result | 4 |
| Segmented | 8 |
| Select | 27 |
| Skeleton | 8 |
| Slider | 18 |
| Space | 0 |
| Spin | 4 |
| Splitter | 4 |
| Statistic | 2 |
| Steps | 17 |
| Switch | 13 |
| Table | 37 |
| Tabs | 26 |
| Tag | 3 |
| Timeline | 4 |
| Tour | 9 |
| Transfer | 7 |
| Tree | 9 |
| Typography | 2 |
| Upload | 2 |

## Using it later

- **Plain CSS / Streamlit:** link `tokens/tokens.css` and use `var(--ant-color-primary)` etc.
- **React:** `npm i antd`, wrap in `<ConfigProvider theme={{ token: { colorPrimary: '…' }, algorithm: theme.darkAlgorithm }}>` — same system, live.
- **Tailwind:** map `theme.extend` colors/spacing/radius to the `--ant-*` variables.
- Note: this repo is a Streamlit (Python) app; Ant Design components are React, so only tokens apply directly. Wiring them into the UI is a separate step.
