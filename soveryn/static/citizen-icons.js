/* Grok-style badges: a colored shape + two black eyes. User picks the shape.
   2026-11 cc-revamp: each citizen also gets an animated trait (halo, sparks, antenna, monocle,
   radar, ripples, spectacles) and a live state (live / busy / down / inbox) via data-state. */
(function (root) {
  "use strict";

  var SEQ = 0;
  var SHAPES = [
    "round", "squircle", "pill", "bean", "diamond",
    "egg", "triangle", "hex", "heart", "star", "drop",
    "moon", "cloud", "clover", "shield", "blob"
  ];
  var SHAPE_LABELS = {
    round: "Round",
    squircle: "Square",
    pill: "Pill",
    bean: "Bean",
    diamond: "Diamond",
    egg: "Egg",
    triangle: "Triangle",
    hex: "Hex",
    heart: "Heart",
    star: "Star",
    drop: "Drop",
    moon: "Moon",
    cloud: "Cloud",
    clover: "Clover",
    shield: "Shield",
    blob: "Blob"
  };
  var DEFAULTS = {
    aetheria: "round",
    forge: "squircle",
    kernel: "squircle",
    eve: "pill",
    t_critic: "diamond",
    t_scout: "bean",
    pondwright: "drop",
    atticus: "egg",
    vett: "round",
    scotty: "squircle"
  };
  var NAMES = {
    aetheria: "Aetheria", forge: "Forge", kernel: "Kernel", eve: "Eve",
    t_critic: "Critic", t_scout: "Scout", pondwright: "Pondwright", atticus: "Atticus", vett: "Vett", scotty: "Scotty"
  };
  /* v2 (2026-11-03): flat, friendly, one clear hue per citizen; readable on the dark UI.
     mid = body fill, lo = outline (same hue, darker), hi = light accent. */
  var PALETTE = {
    aetheria:   { hi: "#ffe39a", mid: "#ffbf3c", lo: "#a8700a" },  /* sunny gold */
    forge:      { hi: "#b9f5a8", mid: "#5fd35a", lo: "#2a7d28" },  /* leaf green */
    kernel:     { hi: "#b9f5a8", mid: "#5fd35a", lo: "#2a7d28" },
    eve:        { hi: "#dccbff", mid: "#a97cff", lo: "#5a33b5" },  /* violet */
    t_critic:   { hi: "#ffc2b0", mid: "#ff7b54", lo: "#a83a1e" },  /* coral */
    t_scout:    { hi: "#b5dcff", mid: "#4aa3ff", lo: "#1d5aa3" },  /* sky blue */
    pondwright: { hi: "#b2f4ee", mid: "#26cfc2", lo: "#0f746c" },  /* teal */
    atticus:    { hi: "#ffc4e1", mid: "#ff6fae", lo: "#a3265f" },  /* pink */
    vett:       { hi: "#c9ecf7", mid: "#7ec8e3", lo: "#2f6f8a" },
    scotty:     { hi: "#ffd2ad", mid: "#ff9a4d", lo: "#a3521a" }
  };
  var cache = {};
  var hydrated = false;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function norm(id) {
    return String(id || "").toLowerCase().replace(/[^a-z0-9_]/g, "");
  }
  function ids(prefix) {
    SEQ += 1;
    var n = SEQ;
    return function (name) { return "sci-" + prefix + "-" + name + "-" + n; };
  }
  function shapeFor(id) {
    var n = norm(id);
    return cache[n] || DEFAULTS[n] || "round";
  }

  function shapeEl(shape, attrs) {
    if (shape === "squircle") {
      return '<rect x="9" y="9" width="46" height="46" rx="14"' + attrs + "/>";
    }
    if (shape === "pill") {
      return '<rect x="6" y="18" width="52" height="28" rx="14"' + attrs + "/>";
    }
    if (shape === "bean") {
      return '<path d="M16 38 C 12 22, 28 10, 42 14 C 56 18, 58 36, 48 46 C 36 56, 20 54, 16 38 Z"' + attrs + "/>";
    }
    if (shape === "diamond") {
      return '<path d="M32 8 L54 32 L32 56 L10 32 Z" stroke-linejoin="round"' + attrs + "/>";
    }
    if (shape === "egg") {
      return '<ellipse cx="32" cy="33" rx="18" ry="23"' + attrs + "/>";
    }
    if (shape === "triangle") {
      return '<path d="M32 9 L55 51 L9 51 Z" stroke-linejoin="round"' + attrs + "/>";
    }
    if (shape === "hex") {
      return '<polygon points="32,8 51,19.5 51,44.5 32,56 13,44.5 13,19.5" stroke-linejoin="round"' + attrs + "/>";
    }
    if (shape === "heart") {
      return '<path d="M32 50 C 32 50, 10 34, 10 22 C 10 13, 18 10, 24 15 C 28 18, 32 24, 32 24 C 32 24, 36 18, 40 15 C 46 10, 54 13, 54 22 C 54 34, 32 50, 32 50 Z"' + attrs + "/>";
    }
    if (shape === "star") {
      return '<path d="M32 7 L36.8 23.2 L54 24.2 L40.4 34.4 L45.2 51 L32 41.6 L18.8 51 L23.6 34.4 L10 24.2 L27.2 23.2 Z" stroke-linejoin="round"' + attrs + "/>";
    }
    if (shape === "drop") {
      return '<path d="M32 7 C 48 24, 52 40, 32 54 C 12 40, 16 24, 32 7 Z"' + attrs + "/>";
    }
    if (shape === "moon") {
      return '<path d="M42 10 A22 22 0 1 0 42 54 A16 16 0 1 1 42 10 Z" stroke-linejoin="round"' + attrs + "/>";
    }
    if (shape === "cloud") {
      return '<path d="M18 42 C10 42, 8 32, 16 28 C16 18, 28 14, 34 20 C38 12, 52 14, 54 24 C60 26, 60 38, 52 40 C54 48, 42 50, 36 46 L22 46 C14 48, 12 44, 18 42 Z"' + attrs + "/>";
    }
    if (shape === "clover") {
      return '<path d="M32 14 C22 6, 10 16, 20 28 C10 40, 22 50, 32 42 C42 50, 54 40, 44 28 C54 16, 42 6, 32 14 Z"' + attrs + "/>";
    }
    if (shape === "shield") {
      return '<path d="M32 7 L52 14 L52 32 C52 46, 32 57, 32 57 C32 57, 12 46, 12 32 L12 14 Z" stroke-linejoin="round"' + attrs + "/>";
    }
    if (shape === "blob") {
      return '<path d="M18 28 C14 16, 28 8, 38 12 C50 8, 56 22, 50 32 C56 44, 42 54, 32 50 C18 56, 10 42, 18 28 Z"' + attrs + "/>";
    }
    return '<circle cx="32" cy="32" r="24"' + attrs + "/>";
  }

  function bodyPath(shape, p, u) {
    /* flat fill, no metallic gradient or sheen */
    return (
      shapeEl(shape, ' fill="' + p.mid + '"') +
      shapeEl(shape, ' fill="none" stroke="' + p.lo + '" stroke-width="2"')
    );
  }

  function eyes() {
    return (
      '<g class="sov-eyes">' +
        '<g class="sov-pupils">' +
          '<circle cx="24.6" cy="29.2" r="3.45" fill="#14110e"/>' +
          '<circle cx="39.4" cy="29.2" r="3.45" fill="#14110e"/>' +
          '<circle cx="23.5" cy="28.1" r="0.95" fill="#f7f4ec"/>' +
          '<circle cx="38.3" cy="28.1" r="0.95" fill="#f7f4ec"/>' +
        "</g>" +
      "</g>"
    );
  }

  var STATES = { live: 1, busy: 1, down: 1, inbox: 1, idle: 1 };
  var TRAIT_ALIAS = { kernel: "forge" };

  /* One small animated accessory per citizen. Drawn in the 64-box, above/around the body. */
  function trait(n, p) {
    var t = TRAIT_ALIAS[n] || n;
    if (t === "aetheria") {
      return '<g class="sov-tr sov-tr-halo"><ellipse cx="32" cy="3.5" rx="12.5" ry="3.4" fill="none" stroke="#f8e9b6" stroke-width="2.2"/>' +
        '<ellipse cx="32" cy="3.5" rx="12.5" ry="3.4" fill="none" stroke="#fff6d8" stroke-width="0.8" opacity="0.9"/></g>' +
        '<path class="sov-tr sov-tr-twinkle" d="M55 9 L56.4 12.6 L60 14 L56.4 15.4 L55 19 L53.6 15.4 L50 14 L53.6 12.6 Z" fill="#fff3c8"/>';
    }
    if (t === "forge") {
      return '<g class="sov-tr sov-tr-sparks" stroke="#ffd36b" stroke-width="2" stroke-linecap="round">' +
        '<line x1="52" y1="11" x2="57" y2="5"/><line x1="55" y1="15" x2="62" y2="13"/><line x1="48" y1="8" x2="49" y2="1"/></g>' +
        '<circle class="sov-tr sov-tr-ember" cx="58" cy="3" r="1.6" fill="#ffb347"/>';
    }
    if (t === "eve") {
      return '<line x1="32" y1="14" x2="32" y2="3.5" stroke="' + p.lo + '" stroke-width="1.8" stroke-linecap="round"/>' +
        '<circle class="sov-tr sov-tr-ring" cx="32" cy="2" r="3" fill="none" stroke="#f3dcff" stroke-width="1.4"/>' +
        '<circle class="sov-tr sov-tr-bulb" cx="32" cy="2" r="3.1" fill="#fbefff" stroke="' + p.mid + '" stroke-width="1"/>';
    }
    if (t === "t_critic") {
      return '<path class="sov-tr sov-tr-brow" d="M19.5 22.6 Q24.6 19.4 29.4 22.2" fill="none" stroke="#14110e" stroke-width="1.6" stroke-linecap="round"/>' +
        '<g class="sov-tr sov-tr-monocle"><circle cx="39.4" cy="29.2" r="6.4" fill="rgba(255,255,255,0.10)" stroke="#f4dfb4" stroke-width="1.7"/>' +
        '<path d="M45.6 31.5 Q49 40 46.5 47" fill="none" stroke="#f4dfb4" stroke-width="0.9"/>' +
        '<path class="sov-tr-glint" d="M35.6 26.4 L38.6 23.6" stroke="#fff" stroke-width="1.3" stroke-linecap="round"/></g>';
    }
    if (t === "t_scout") {
      return '<g class="sov-tr sov-tr-radar"><circle cx="54" cy="8" r="2" fill="#e6f4ff"/>' +
        '<circle class="sov-tr-ping" cx="54" cy="8" r="2" fill="none" stroke="#cfe6f7" stroke-width="1.3"/>' +
        '<circle class="sov-tr-ping sov-tr-ping2" cx="54" cy="8" r="2" fill="none" stroke="#cfe6f7" stroke-width="1.3"/></g>' +
        '<line x1="47" y1="15" x2="52.6" y2="9.6" stroke="' + p.lo + '" stroke-width="1.6" stroke-linecap="round"/>';
    }
    if (t === "pondwright") {
      return '<g class="sov-tr sov-tr-pond" fill="none" stroke="#9fe3d6" stroke-width="1.3">' +
        '<ellipse class="sov-tr-ripple" cx="32" cy="59" rx="10" ry="2.4"/>' +
        '<ellipse class="sov-tr-ripple sov-tr-ripple2" cx="32" cy="59" rx="10" ry="2.4"/></g>' +
        '<path class="sov-tr sov-tr-leaf" d="M50 12 C 56 6, 62 8, 61 14 C 58 18, 52 17, 50 12 Z" fill="#7fd08a" stroke="#2e6b3a" stroke-width="0.9"/>';
    }
    if (t === "atticus") {
      return '<g class="sov-tr sov-tr-specs" fill="rgba(255,255,255,0.08)" stroke="#f1e2c2" stroke-width="1.5">' +
        '<circle cx="24.6" cy="29.2" r="5.6"/><circle cx="39.4" cy="29.2" r="5.6"/>' +
        '<path d="M30.2 28.6 Q32 27 33.8 28.6" fill="none"/></g>' +
        '<g class="sov-tr sov-tr-page"><rect x="49" y="4" width="10" height="12" rx="1.4" fill="#fbf4e4" stroke="#8a6a4a" stroke-width="0.8"/>' +
        '<path d="M51 8 H57 M51 10.5 H57 M51 13 H55" stroke="#8a6a4a" stroke-width="0.7"/></g>';
    }
    return "";
  }

  function svgInner(id, letter, shape) {
    var n = norm(id);
    var p = PALETTE[n] || PALETTE.aetheria;
    var u = ids(n || "x");
    var sh = shape || shapeFor(n);
    if (SHAPES.indexOf(sh) < 0) sh = "round";
    var L = letter || (n ? n.charAt(0).toUpperCase() : "?");
    return (
      '<svg viewBox="-4 -6 72 72" aria-hidden="true" focusable="false">' +
        '<circle class="sov-aura" cx="32" cy="32" r="30" fill="none" stroke="' + p.mid + '" stroke-width="2.4"/>' +
        '<g class="sov-bob">' +
          bodyPath(sh, p, u) +
          eyes() +
          trait(n, p) +
        "</g>" +
      "</svg>" +
      '<span class="sov-cit-letter">' + esc(L) + "</span>"
    );
  }

  function soverynCitizenIcon(id, opts) {
    opts = opts || {};
    var n = norm(id);
    var cls = ["sov-cit", "sov-cit--" + (PALETTE[n] ? n : "generic"), "has-eyes"];
    if (opts.busy) cls.push("is-busy");
    var st = STATES[opts.state] ? opts.state : "";
    if (opts.className) cls.push(String(opts.className));
    var size = opts.size ? Number(opts.size) : 0;
    var style = size ? ' style="width:' + size + "px;height:" + size + 'px"' : "";
    var label = opts.label || NAMES[n] || n || "citizen";
    return (
      '<span class="' + cls.join(" ") + '"' +
        ' role="img" aria-label="' + esc(label) + '"' +
        ' data-agent="' + esc(n) + '" data-citizen="' + esc(n) + '"' +
        ' data-shape="' + esc(opts.shape || shapeFor(n)) + '"' +
        (opts.busy ? ' data-busy="1"' : "") +
        (st ? ' data-state="' + st + '"' : "") +
        style + ">" + svgInner(n, opts.letter, opts.shape) + "</span>"
    );
  }

  function paint(el, id, opts) {
    if (!el) return el;
    opts = opts || {};
    var n = norm(id);
    el.className = (el.className || "").replace(/\bsov-cit--\w+/g, "").trim();
    el.classList.add("sov-cit", "sov-cit--" + (PALETTE[n] ? n : "generic"), "has-eyes");
    if (opts.className) {
      String(opts.className).split(/\s+/).forEach(function (c) { if (c) el.classList.add(c); });
    }
    el.classList.toggle("is-busy", !!opts.busy);
    if (opts.busy) el.setAttribute("data-busy", "1");
    else el.removeAttribute("data-busy");
    el.setAttribute("data-agent", n);
    el.setAttribute("data-citizen", n);
    el.setAttribute("data-shape", opts.shape || shapeFor(n));
    if (STATES[opts.state]) el.setAttribute("data-state", opts.state);
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", opts.label || NAMES[n] || n || "citizen");
    el.removeAttribute("aria-hidden");
    if (opts.size) {
      el.style.width = Number(opts.size) + "px";
      el.style.height = Number(opts.size) + "px";
    }
    el.innerHTML = svgInner(n, opts.letter, opts.shape);
    return el;
  }

  function repaintAll() {
    var nodes = document.querySelectorAll(".sov-cit[data-agent]");
    for (var i = 0; i < nodes.length; i += 1) {
      var el = nodes[i];
      var id = el.getAttribute("data-agent");
      var busy = el.classList.contains("is-busy") || el.getAttribute("data-busy") === "1";
      var label = el.getAttribute("aria-label");
      var w = parseInt(el.style.width, 10) || 0;
      paint(el, id, { busy: busy, label: label, size: w || undefined, state: el.getAttribute("data-state") || "" });
    }
  }

  function hydrate() {
    if (typeof fetch === "undefined") return Promise.resolve(cache);
    return fetch("/api/citizen-shapes", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) {
        if (data && data.shapes) {
          Object.keys(data.shapes).forEach(function (k) {
            if (SHAPES.indexOf(data.shapes[k]) >= 0) cache[k] = data.shapes[k];
          });
        }
        hydrated = true;
        repaintAll();
        document.dispatchEvent(new Event("soveryn-shapes-ready"));
        return cache;
      })
      .catch(function () { hydrated = true; return cache; });
  }

  function setShape(agent, shape) {
    var n = norm(agent);
    cache[n] = shape;
    repaintAll();
    return fetch("/api/citizen-shapes", {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ agent: n, shape: shape })
    }).catch(function () { return null; });
  }

  function closePicker() {
    var el = document.getElementById("sov-shape-sheet");
    if (el) el.remove();
  }

  function openPicker(agent) {
    var n = norm(agent);
    closePicker();
    var name = NAMES[n] || n;
    var current = shapeFor(n);
    var sheet = document.createElement("div");
    sheet.id = "sov-shape-sheet";
    sheet.className = "sov-shape-sheet";
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-label", "Choose a shape for " + name);
    var chips = SHAPES.map(function (sh) {
      var on = sh === current ? " is-on" : "";
      return (
        '<button type="button" class="sov-shape-chip' + on + '" data-shape="' + sh + '">' +
          soverynCitizenIcon(n, { size: 56, shape: sh, label: SHAPE_LABELS[sh] }) +
          '<span>' + esc(SHAPE_LABELS[sh]) + "</span>" +
        "</button>"
      );
    }).join("");
    sheet.innerHTML =
      '<div class="sov-shape-card">' +
        "<p>Shape for <strong>" + esc(name) + "</strong></p>" +
        '<div class="sov-shape-row">' + chips + "</div>" +
        '<button type="button" class="sov-shape-done">Done</button>' +
      "</div>";
    sheet.addEventListener("click", function (ev) {
      if (ev.target === sheet) closePicker();
    });
    sheet.querySelector(".sov-shape-done").addEventListener("click", closePicker);
    var btns = sheet.querySelectorAll("[data-shape]");
    for (var i = 0; i < btns.length; i += 1) {
      btns[i].addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var sh = this.getAttribute("data-shape");
        setShape(n, sh);
        var all = sheet.querySelectorAll(".sov-shape-chip");
        for (var j = 0; j < all.length; j += 1) {
          all[j].classList.toggle("is-on", all[j].getAttribute("data-shape") === sh);
        }
      });
    }
    document.body.appendChild(sheet);
  }

  function bindPicker(rootEl) {
    var host = rootEl || document;
    host.addEventListener("click", function (ev) {
      var hit = ev.target.closest ? ev.target.closest("[data-pick-shape]") : null;
      if (!hit) return;
      ev.preventDefault();
      ev.stopPropagation();
      openPicker(hit.getAttribute("data-pick-shape"));
    }, true);
  }

  /* Live state for every badge of a citizen on the page (status dots drive this). */
  function setState(agent, state) {
    var n = norm(agent);
    if (!STATES[state]) return;
    var sel = '.sov-cit[data-agent="' + n + '"]' + (n === "forge" ? ',.sov-cit[data-agent="kernel"]' : "");
    var nodes = document.querySelectorAll(sel);
    for (var i = 0; i < nodes.length; i += 1) nodes[i].setAttribute("data-state", state);
  }
  var presence = {};
  function applyPresence(list) {
    (list || []).forEach(function (c) { if (c && c.id) { presence[norm(c.id)] = c.state; setState(c.id, c.state); } });
  }
  function stateOf(agent) { var n = norm(agent); return presence[n] || (n === "kernel" ? presence.forge : "") || ""; }
  var watching = null;
  function watchPresence(ms) {
    if (watching || typeof fetch === "undefined") return;
    var tick = function () {
      if (document.visibilityState === "hidden") return;
      fetch("/api/messages/presence", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d) applyPresence(d.citizens); })
        .catch(function () {});
    };
    tick();
    watching = setInterval(tick, ms || 30000);
    document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") tick(); });
  }
  /* keep state across shape repaints */
  if (typeof document !== "undefined") {
    document.addEventListener("soveryn-shapes-ready", function () {
      Object.keys(presence).forEach(function (k) { setState(k, presence[k]); });
    });
  }

  soverynCitizenIcon.setState = setState;
  soverynCitizenIcon.applyPresence = applyPresence;
  soverynCitizenIcon.stateOf = stateOf;
  soverynCitizenIcon.watchPresence = watchPresence;
  soverynCitizenIcon.svg = svgInner;
  soverynCitizenIcon.paint = paint;
  soverynCitizenIcon.shapes = SHAPES;
  soverynCitizenIcon.shapeFor = shapeFor;
  soverynCitizenIcon.setShape = setShape;
  soverynCitizenIcon.openPicker = openPicker;
  soverynCitizenIcon.bindPicker = bindPicker;
  soverynCitizenIcon.hydrate = hydrate;
  soverynCitizenIcon.ids = Object.keys(PALETTE);
  root.soverynCitizenIcon = soverynCitizenIcon;

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        bindPicker(document);
        hydrate();
      });
    } else {
      bindPicker(document);
      hydrate();
    }
  }
})(typeof window !== "undefined" ? window : this);
