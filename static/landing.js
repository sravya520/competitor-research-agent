/* Landing page interactions (loaded by views/landing.py via st.html with unsafe_allow_javascript).
 *
 * DESIGN.md M4 and section 15: content is complete without this file; only transform and opacity
 * animate; motion runs only without a reduced-motion preference (gsap.matchMedia). In-page links
 * work either way. GSAP is vendored in /app/static/vendor/gsap (no third-party requests).
 *
 * What animates and why:
 *  - reveals ......... pace: each block settles in once as it is reached (12px, opacity)
 *  - flow connectors . explanation: the lines between steps draw in, in order, so the six
 *                      steps read as one sequence
 *  Not animated: the hero (pure CSS entrance), the FAQ, numbers, hover beyond CSS.
 */
(function () {
  "use strict";

  var BASE = "/app/static/vendor/gsap/";
  var root = document.querySelector(".lp");
  if (!root) return;
  if (window.__craLanding && window.__craLanding.root === root) return; // this DOM is already set up
  if (window.__craLanding) window.__craLanding.revert();               // a rerun replaced the old DOM

  var main = document.querySelector('[data-testid="stMain"]') || document.scrollingElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var cleanups = [];
  var mm = null;

  function on(target, type, fn) {
    target.addEventListener(type, fn);
    cleanups.push(function () { target.removeEventListener(type, fn); });
  }

  // In-page links scroll Streamlit's scroll container (the window itself does not scroll).
  root.querySelectorAll('a[href^="#"]').forEach(function (a) {
    on(a, "click", function (e) {
      var target = root.querySelector(a.getAttribute("href"));
      if (!target || !main) return;
      e.preventDefault();
      var top = main.scrollTop + target.getBoundingClientRect().top - main.getBoundingClientRect().top - 24;
      main.scrollTo({ top: top, behavior: reduce.matches ? "auto" : "smooth" });
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    });
  });

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = false;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("failed " + src)); };
      document.head.appendChild(s);
    });
  }

  function setup() {
    gsap.registerPlugin(ScrollTrigger, CustomEase);
    CustomEase.create("uiOut", "0.23, 1, 0.32, 1"); // strong ease-out, same curve as the CSS
    ScrollTrigger.defaults({ scroller: main });
    gsap.ticker.lagSmoothing(0); // entrances finish after a stalled frame instead of crawling

    mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", function () {
      // Reveals. Opacity, not visibility, so everything stays focusable while hidden.
      var reveal = Array.prototype.filter.call(
        root.querySelectorAll(".lp-section .lp-head, .lp-step, .lp-checks li, .lp-points, .lp-try, .lp-doc, .lp-faq, .lp-cta"),
        function (el) { return !el.closest(".lp-hero"); }
      );
      gsap.set(reveal, { opacity: 0, y: 12 });
      ScrollTrigger.batch(reveal, {
        start: "top 90%",
        once: true,
        interval: 0.1,
        batchMax: 6,
        onEnter: function (batch) {
          gsap.to(batch, { opacity: 1, y: 0, duration: 0.45, ease: "uiOut", stagger: 0.05, overwrite: true, clearProps: "transform" });
        }
      });

      // Flow connectors draw in left to right, in step order.
      var flow = root.querySelector("[data-flow]");
      var links = flow ? flow.querySelectorAll(".lp-step__link") : [];
      if (links.length) {
        gsap.set(links, { scaleX: 0 });
        ScrollTrigger.create({
          trigger: flow,
          start: "top 75%",
          once: true,
          onEnter: function () {
            gsap.to(links, { scaleX: 1, duration: 0.4, ease: "uiOut", stagger: 0.08, delay: 0.1 });
          }
        });
      }

      ScrollTrigger.refresh();
    });
  }

  loadScript(BASE + "gsap.min.js")
    .then(function () { return loadScript(BASE + "ScrollTrigger.min.js"); })
    .then(function () { return loadScript(BASE + "CustomEase.min.js"); })
    .then(setup)
    .catch(function () { /* GSAP unavailable: the page is already complete without it */ });

  window.__craLanding = {
    root: root,
    revert: function () {
      if (mm) mm.revert();
      if (window.ScrollTrigger) ScrollTrigger.getAll().forEach(function (t) { t.kill(); });
      cleanups.forEach(function (fn) { fn(); });
      window.__craLanding = null;
    }
  };
})();
