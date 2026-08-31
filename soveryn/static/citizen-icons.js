/* Shared citizen faces. window.soverynCitizenIcon(id, {size, busy, letter, className, label, attrs}) */
(function (root) {
  "use strict";

  var SEQ = 0;
  var LETTERS = {
    aetheria: "A",
    kernel: "K",
    eve: "E",
    t_critic: "C",
    t_scout: "Sc",
    vett: "V",
    scotty: "S"
  };
  var NAMES = {
    aetheria: "Aetheria",
    kernel: "Kernel",
    eve: "Eve",
    t_critic: "Critic",
    t_scout: "Scout",
    vett: "Vett",
    scotty: "Scotty"
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
  var EYES = { aetheria: true, eve: true };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function norm(id) {
    return String(id || "").toLowerCase().replace(/[^a-z0-9_]/g, "");
  }

  function ids(prefix) {
    SEQ += 1;
    var n = SEQ;
    return function (name) {
      return "sci-" + prefix + "-" + name + "-" + n;
    };
  }

  function disc(p, u) {
    var g = u("g");
    var c = u("c");
    return (
      '<defs>' +
        '<radialGradient id="' + g + '" cx="36%" cy="28%">' +
          '<stop offset="0%" stop-color="' + p.lo + '" stop-opacity="0.62"/>' +
          '<stop offset="100%" stop-color="#080807" stop-opacity="1"/>' +
        "</radialGradient>" +
        '<clipPath id="' + c + '"><circle cx="32" cy="32" r="32"/></clipPath>' +
      "</defs>" +
      '<g clip-path="url(#' + c + ')">' +
        '<circle cx="32" cy="32" r="32" fill="url(#' + g + ')"/>' +
        '<circle class="sov-ring" cx="32" cy="32" r="30.4" fill="none" stroke="' + p.mid + '" stroke-width="1.2" opacity="0.72"/>'
    );
  }

  function closeDisc() {
    return "</g>";
  }

  function liveFace(p, u, extras) {
    extras = extras || "";
    return (
      disc(p, u) +
      '<circle cx="32" cy="33" r="20.2" fill="' + p.lo + '" opacity="0.42"/>' +
      '<circle cx="32" cy="33.4" r="16.8" fill="' + p.mid + '"/>' +
      extras +
      '<g class="sov-eyes">' +
        '<ellipse cx="24.1" cy="31" rx="5.7" ry="6.6" fill="#f3eee3"/>' +
        '<ellipse cx="39.9" cy="31" rx="5.7" ry="6.6" fill="#f3eee3"/>' +
        '<g class="sov-pupils">' +
          '<circle cx="24.1" cy="31.6" r="2.55" fill="#16120f"/>' +
          '<circle cx="39.9" cy="31.6" r="2.55" fill="#16120f"/>' +
          '<circle cx="23.15" cy="30.4" r="0.72" fill="#f7f4ec"/>' +
          '<circle cx="38.95" cy="30.4" r="0.72" fill="#f7f4ec"/>' +
        "</g>" +
      "</g>" +
      closeDisc()
    );
  }

  function markAetheria(p, u) {
    var extra =
      '<path fill="' + p.hi + '" d="M32 13.4 L33.05 18.6 L38.4 19.7 L33.05 20.8 L32 26 L30.95 20.8 L25.6 19.7 L30.95 18.6 Z"/>' +
      '<circle cx="18.6" cy="41.4" r="1.1" fill="' + p.hi + '" opacity="0.9"/>' +
      '<circle cx="45.4" cy="41.4" r="1.1" fill="' + p.hi + '" opacity="0.9"/>';
    return liveFace(p, u, extra);
  }

  function markKernel(p, u) {
    var hex = u("hex");
    return (
      disc(p, u) +
      '<defs><clipPath id="' + hex + '">' +
        '<polygon points="32,12.2 49.1,22.1 49.1,41.9 32,51.8 14.9,41.9 14.9,22.1"/>' +
      "</clipPath></defs>" +
      '<polygon fill="none" stroke="' + p.mid + '" stroke-width="1.45" points="32,12.2 49.1,22.1 49.1,41.9 32,51.8 14.9,41.9 14.9,22.1"/>' +
      '<polygon fill="none" stroke="' + p.hi + '" stroke-width="1.05" opacity="0.9" points="32,20.4 42.3,26.3 42.3,37.7 32,43.6 21.7,37.7 21.7,26.3"/>' +
      '<rect x="29.4" y="8.2" width="5.2" height="3" rx="0.4" fill="' + p.mid + '"/>' +
      '<rect x="29.4" y="52.8" width="5.2" height="3" rx="0.4" fill="' + p.mid + '"/>' +
      '<rect x="8.2" y="29.4" width="3" height="5.2" rx="0.4" fill="' + p.mid + '"/>' +
      '<rect x="52.8" y="29.4" width="3" height="5.2" rx="0.4" fill="' + p.mid + '"/>' +
      '<g clip-path="url(#' + hex + ')">' +
        '<rect class="sov-scan" x="13" y="11" width="38" height="2.8" fill="' + p.hi + '" opacity="0.92"/>' +
      "</g>" +
      '<circle cx="32" cy="32" r="2" fill="' + p.hi + '"/>' +
      closeDisc()
    );
  }

  function markEve(p, u) {
    var extra =
      '<g fill="' + p.hi + '">' +
        '<ellipse cx="46.4" cy="16.6" rx="1.45" ry="2.55" opacity="0.92"/>' +
        '<ellipse cx="44.2" cy="19.4" rx="1.45" ry="2.55" opacity="0.75" transform="rotate(-55 44.2 19.4)"/>' +
        '<ellipse cx="48.5" cy="19.4" rx="1.45" ry="2.55" opacity="0.75" transform="rotate(55 48.5 19.4)"/>' +
      "</g>";
    return liveFace(p, u, extra);
  }

  function markCritic(p, u) {
    return (
      disc(p, u) +
      '<circle cx="32" cy="32" r="16.5" fill="none" stroke="' + p.mid + '" stroke-width="1.5"/>' +
      '<circle cx="32" cy="32" r="11.2" fill="none" stroke="' + p.hi + '" stroke-width="1.05" opacity="0.85"/>' +
      '<circle cx="32" cy="32" r="5.6" fill="' + p.lo + '" stroke="' + p.mid + '" stroke-width="0.9"/>' +
      '<circle cx="32" cy="32" r="2.2" fill="#0a0908"/>' +
      '<circle cx="30.2" cy="30.4" r="0.85" fill="' + p.hi + '" opacity="0.9"/>' +
      '<path fill="none" stroke="' + p.mid + '" stroke-width="1.1" d="M32 12.8 V16.6 M32 47.4 V51.2 M12.8 32 H16.6 M47.4 32 H51.2"/>' +
      '<ellipse class="sov-lid" cx="32" cy="32" rx="17" ry="17" fill="#0a0908"/>' +
      closeDisc()
    );
  }

  function markScout(p, u) {
    return (
      disc(p, u) +
      '<circle cx="32" cy="32" r="20" fill="none" stroke="' + p.mid + '" stroke-width="0.75" opacity="0.45"/>' +
      '<circle cx="32" cy="32" r="13.5" fill="none" stroke="' + p.mid + '" stroke-width="0.75" opacity="0.55"/>' +
      '<circle cx="32" cy="32" r="7" fill="none" stroke="' + p.hi + '" stroke-width="0.8" opacity="0.75"/>' +
      '<path fill="none" stroke="' + p.mid + '" stroke-width="0.7" opacity="0.5" d="M32 10 V54 M10 32 H54"/>' +
      '<g class="sov-sweep">' +
        '<path d="M32 32 L32 11 A21 21 0 0 1 48.6 20.4 Z" fill="' + p.hi + '" opacity="0.42"/>' +
        '<path d="M32 32 L32 11" stroke="' + p.hi + '" stroke-width="1.15"/>' +
      "</g>" +
      '<circle cx="32" cy="32" r="2.1" fill="' + p.hi + '"/>' +
      closeDisc()
    );
  }

  function markVett(p, u) {
    return (
      disc(p, u) +
      '<polygon fill="none" stroke="' + p.mid + '" stroke-width="1.2" points="32,11 50,22.5 50,41.5 32,53 14,41.5 14,22.5"/>' +
      '<path fill="none" stroke="' + p.hi + '" stroke-width="0.9" opacity="0.85" d="M32 11 L32 53 M14 22.5 L50 41.5 M50 22.5 L14 41.5"/>' +
      '<polygon class="sov-shimmer" fill="' + p.hi + '" opacity="0.35" points="32,18 42,24 32,32 22,24"/>' +
      '<circle cx="32" cy="32" r="2.4" fill="' + p.mid + '"/>' +
      closeDisc()
    );
  }

  function markScotty(p, u) {
    return (
      disc(p, u) +
      '<circle cx="32" cy="32" r="18.5" fill="none" stroke="' + p.mid + '" stroke-width="2.1" stroke-dasharray="22 10" stroke-linecap="round" opacity="0.85"/>' +
      '<circle class="sov-pulse" cx="32" cy="32" r="12.5" fill="none" stroke="' + p.hi + '" stroke-width="1.5" stroke-dasharray="14 8" stroke-linecap="round"/>' +
      '<polygon fill="' + p.lo + '" stroke="' + p.mid + '" stroke-width="0.9" points="32,24.5 38.2,28.1 38.2,35.9 32,39.5 25.8,35.9 25.8,28.1"/>' +
      '<circle cx="32" cy="32" r="2" fill="' + p.hi + '"/>' +
      closeDisc()
    );
  }

  function markGeneric(p, u) {
    return (
      disc(p, u) +
      '<circle cx="32" cy="32" r="14" fill="none" stroke="' + p.mid + '" stroke-width="1.2"/>' +
      '<path fill="' + p.hi + '" d="M32 20 L34 31 L45 32 L34 33 L32 44 L30 33 L19 32 L30 31 Z"/>' +
      closeDisc()
    );
  }

  var MARKS = {
    aetheria: markAetheria,
    kernel: markKernel,
    eve: markEve,
    t_critic: markCritic,
    t_scout: markScout,
    vett: markVett,
    scotty: markScotty
  };

  function svgInner(id, letter) {
    var n = norm(id);
    var p = PALETTE[n] || PALETTE.aetheria;
    var u = ids(n || "x");
    var mark = (MARKS[n] || markGeneric)(p, u);
    var L = letter || LETTERS[n] || (n ? n.charAt(0).toUpperCase() : "?");
    return (
      '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">' + mark + "</svg>" +
      '<span class="sov-cit-letter">' + esc(L) + "</span>"
    );
  }

  function citClass(id) {
    var n = norm(id);
    return MARKS[n] ? n : "generic";
  }

  function soverynCitizenIcon(id, opts) {
    opts = opts || {};
    var n = norm(id);
    var cls = ["sov-cit", "sov-cit--" + citClass(n)];
    if (EYES[n]) cls.push("has-eyes");
    if (opts.busy) cls.push("is-busy");
    if (opts.className) cls.push(String(opts.className));
    var size = opts.size ? Number(opts.size) : 0;
    var style = size ? ' style="width:' + size + "px;height:" + size + 'px"' : "";
    var label = opts.label || NAMES[n] || n || "citizen";
    var extra = opts.attrs ? " " + opts.attrs : "";
    return (
      '<span class="' + cls.join(" ") + '"' +
        ' role="img" aria-label="' + esc(label) + '"' +
        ' data-agent="' + esc(n) + '"' +
        ' data-citizen="' + esc(n) + '"' +
        (opts.busy ? ' data-busy="1"' : "") +
        style + extra + ">" +
        svgInner(n, opts.letter) +
      "</span>"
    );
  }

  function paint(el, id, opts) {
    if (!el) return el;
    opts = opts || {};
    var n = norm(id);
    el.classList.add("sov-cit", "sov-cit--" + citClass(n));
    el.classList.toggle("has-eyes", !!EYES[n]);
    el.classList.toggle("is-busy", !!opts.busy);
    if (opts.busy) el.setAttribute("data-busy", "1");
    else el.removeAttribute("data-busy");
    el.setAttribute("data-agent", n);
    el.setAttribute("data-citizen", n);
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", opts.label || NAMES[n] || n || "citizen");
    el.removeAttribute("aria-hidden");
    if (opts.size) {
      el.style.width = Number(opts.size) + "px";
      el.style.height = Number(opts.size) + "px";
    }
    el.innerHTML = svgInner(n, opts.letter);
    return el;
  }

  soverynCitizenIcon.svg = svgInner;
  soverynCitizenIcon.paint = paint;
  soverynCitizenIcon.ids = Object.keys(MARKS);
  root.soverynCitizenIcon = soverynCitizenIcon;
})(typeof window !== "undefined" ? window : this);
