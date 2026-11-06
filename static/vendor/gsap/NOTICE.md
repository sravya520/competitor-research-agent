# GSAP (vendored)

GSAP 3.15.0: `gsap.min.js`, `ScrollTrigger.min.js`, `CustomEase.min.js`, copied unmodified from the `gsap` npm package.
License: GSAP Standard "no charge" license, https://gsap.com/standard-license

Vendored on purpose instead of loaded from a CDN: visitors' IP addresses are not sent to a third party, which keeps the Privacy Policy accurate. To update: `cd design-system && npm i gsap@latest`, then copy the three files from `node_modules/gsap/dist/`.
