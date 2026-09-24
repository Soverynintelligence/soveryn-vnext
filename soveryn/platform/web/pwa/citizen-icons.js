/* Grok-style badges: a colored shape + two black eyes. User picks the shape. */
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
    kernel: "squircle",
    eve: "pill",
    t_critic: "diamond",
    t_scout: "bean",
    vett: "round",
    scotty: "squircle"
  };
  var NAMES = {
    aetheria: "Aetheria", kernel: "Kernel", eve: "Eve",
    t_critic: "Critic", t_scout: "Scout", vett: "Vett", scotty: "Scotty"
  };
  var PALETTE = {
    aetheria: { hi: "#f0e2b8", mid: "#c6a664", lo: "#8a7038" },
    kernel:   { hi: "#c5f0d4", mid: "#9ee0b8", lo: "#3d7a55" },
    eve:      { hi: "#f0d4ff", mid: "#e0b0ff", lo: "#7a4a9a" },
    t_critic: { hi: "#e8c9a0", mid: "#d4a574", lo: "#6b4a2e" },
    t_scout:  { hi: "#c5dcec", mid: "#8eb8d4", lo: "#3a5a70" },
    vett:     { hi: "#d4f0f8", mid: "#7ec8e3", lo: "#3a7a9a" },
    scotty:   { hi: "#f0c9a8", mid: "#e8a87c", lo: "#a65d3b" }
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
    var g = u("g");
    var c = u("c");
    return (
      "<defs>" +
        '<radialGradient id="' + g + '" cx="34%" cy="28%">' +
          '<stop offset="0%" stop-color="' + p.hi + '"/>' +
          '<stop offset="52%" stop-color="' + p.mid + '"/>' +
          '<stop offset="100%" stop-color="' + p.lo + '"/>' +
        "</radialGradient>" +
        '<clipPath id="' + c + '">' + shapeEl(shape, "") + "</clipPath>" +
      "</defs>" +
      '<g clip-path="url(#' + c + ')">' +
        shapeEl(shape, ' fill="url(#' + g + ')"') +
        '<ellipse class="sov-shine" cx="24" cy="22" rx="12" ry="8" fill="#fff" opacity="0.28"/>' +
        '<ellipse cx="34" cy="42" rx="14" ry="8" fill="#000" opacity="0.12"/>' +
      "</g>" +
      shapeEl(shape, ' fill="none" stroke="' + p.lo + '" stroke-width="1.7"')
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

  function svgInner(id, letter, shape) {
    var n = norm(id);
    var p = PALETTE[n] || PALETTE.aetheria;
    var u = ids(n || "x");
    var sh = shape || shapeFor(n);
    if (SHAPES.indexOf(sh) < 0) sh = "round";
    var L = letter || (n ? n.charAt(0).toUpperCase() : "?");
    return (
      '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">' +
        '<g class="sov-bob">' +
          bodyPath(sh, p, u) +
          eyes() +
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
      paint(el, id, { busy: busy, label: label, size: w || undefined });
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
