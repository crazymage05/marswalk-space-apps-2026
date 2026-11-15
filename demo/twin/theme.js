/* MARSWALK shared theme switch (index.html, twin.html, mission.html). Load it in <head> before the page's styles render.
   Theme = the viewer's saved choice, else "day"; "day" (light) or "dusk" (dark). Any button with
   [data-theme-toggle] switches it; the choice is remembered per browser (localStorage, wrapped: it may be blocked).
   Pages that redraw canvases can listen for the "mw-theme" event on window. */
(function () {
  "use strict";
  var KEY = "mw_theme", root = document.documentElement, t = null;
  try { t = localStorage.getItem(KEY); } catch (e) {}
  if (t !== "day" && t !== "dusk") t = "day";   // default: Mars day (light) for everyone; the Dusk button switches and is remembered
  root.dataset.theme = t;
  function sync() {
    var dusk = root.dataset.theme === "dusk";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.textContent = dusk ? "Day" : "Dusk"; b.setAttribute("aria-pressed", String(dusk));
      b.title = dusk ? "Switch to Mars day (light)" : "Switch to Mars dusk (dark)";
    });
  }
  function set(next) {
    root.dataset.theme = next; try { localStorage.setItem(KEY, next); } catch (e) {}
    sync(); window.dispatchEvent(new CustomEvent("mw-theme", { detail: next }));
  }
  document.addEventListener("click", function (e) {
    var b = e.target && e.target.closest && e.target.closest("[data-theme-toggle]");
    if (b) set(root.dataset.theme === "dusk" ? "day" : "dusk");
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", sync); else sync();
  window.MWTheme = { get: function () { return root.dataset.theme; }, set: set };
})();
