// Living voice orb — no figure. Soft gold core that breathes and
// reacts to mic/TTS amplitude. Instant paint, light draw path.
//
//   LivingPresence.mount(host, { agent })
//   .setState("speaking") / .setLevels({ out, inn }) / .destroy()

(function (global) {
  "use strict";

  const PALETTES = {
    aetheria: {
      hot: [255, 236, 190],
      mid: [198, 166, 100],
      dim: [122, 103, 64],
      deep: [42, 36, 24],
    },
    vett: {
      hot: [210, 228, 240],
      mid: [107, 130, 144],
      dim: [64, 78, 89],
      deep: [26, 34, 40],
    },
    scotty: {
      hot: [255, 200, 185],
      mid: [196, 122, 110],
      dim: [107, 51, 35],
      deep: [42, 20, 14],
    },
  };

  function rgba(c, a) {
    return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  class LivingPresence {
    constructor(host, opts = {}) {
      this.host = host;
      this.agent = (opts.agent || "aetheria").toLowerCase();
      this.palette = PALETTES[this.agent] || PALETTES.aetheria;
      this.state = "idle";
      this.outLevel = 0;
      this.inLevel = 0;
      this._outEma = 0;
      this._inEma = 0;
      this.t0 = performance.now();
      this.raf = null;
      this.running = false;
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.cssSize = 0;

      host.classList.add("voice-presence");
      host.dataset.agent = this.agent;
      host.dataset.state = this.state;
      host.innerHTML = "";

      this.wrap = document.createElement("div");
      this.wrap.className = "voice-presence-inner";

      this.rings = document.createElement("div");
      this.rings.className = "voice-presence-rings";
      this.rings.innerHTML =
        '<i class="r r1"></i><i class="r r2"></i><i class="r r3"></i>';

      this.canvas = document.createElement("canvas");
      this.canvas.className = "voice-presence-canvas";
      this.canvas.setAttribute("aria-hidden", "true");

      this.wrap.appendChild(this.rings);
      this.wrap.appendChild(this.canvas);
      host.appendChild(this.wrap);

      this.ctx = this.canvas.getContext("2d", { alpha: true });
      this._resize();
      this._onResize = () => this._resize();
      window.addEventListener("resize", this._onResize);

      this._draw(performance.now());
      this.start();
    }

    static mount(host, opts) {
      if (!host) return null;
      if (host._livingPresence) {
        const existing = host._livingPresence;
        if (opts && opts.agent) existing.setAgent(opts.agent);
        existing.start();
        return existing;
      }
      const p = new LivingPresence(host, opts);
      host._livingPresence = p;
      return p;
    }

    setAgent(agent) {
      this.agent = (agent || "aetheria").toLowerCase();
      this.palette = PALETTES[this.agent] || PALETTES.aetheria;
      this.host.dataset.agent = this.agent;
    }

    setState(state) {
      if (!state || state === this.state) return;
      this.state = state;
      this.host.dataset.state = state;
    }

    setLevels({ out = 0, inn = 0 } = {}) {
      this._outEma = this._outEma * 0.8 + out * 0.2;
      this._inEma = this._inEma * 0.8 + inn * 0.2;
      this.outLevel = this._outEma;
      this.inLevel = this._inEma;
    }

    start() {
      if (this.running) return;
      this.running = true;
      const loop = (now) => {
        if (!this.running) return;
        this._draw(now);
        this.raf = requestAnimationFrame(loop);
      };
      this.raf = requestAnimationFrame(loop);
    }

    stop() {
      this.running = false;
      if (this.raf) {
        cancelAnimationFrame(this.raf);
        this.raf = null;
      }
    }

    destroy() {
      this.stop();
      window.removeEventListener("resize", this._onResize);
      if (this.host._livingPresence === this) delete this.host._livingPresence;
      this.host.classList.remove("voice-presence");
      this.host.innerHTML = "";
    }

    _resize() {
      const rect = this.host.getBoundingClientRect();
      const size = Math.max(200, Math.min(rect.width || 280, rect.height || 280, 360));
      if (size === this.cssSize && this.canvas.width) return;
      this.cssSize = size;
      this.canvas.style.width = size + "px";
      this.canvas.style.height = size + "px";
      this.canvas.width = Math.floor(size * this.dpr);
      this.canvas.height = Math.floor(size * this.dpr);
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      this.wrap.style.width = size + "px";
      this.wrap.style.height = size + "px";
    }

    _mood(t) {
      const breath = 0.5 + 0.5 * Math.sin(t * 1.05);
      const out = this.outLevel;
      const inn = this.inLevel;
      const s = this.state;

      // base = calm living orb
      let glow = 0.55 + breath * 0.12;
      let core = 0.5 + breath * 0.14;
      let pulse = 0.4 + breath * 0.16;
      let wave = 0.35 + breath * 0.1;
      let spin = 0.12;

      if (s === "listening") {
        glow = 0.65 + breath * 0.12;
        core = 0.6 + breath * 0.12;
        pulse = 0.5 + breath * 0.2;
      } else if (s === "hearing") {
        glow = 0.7 + out * 1.6;
        core = 0.55 + out * 0.8;
        pulse = 0.55 + out * 1.3;
        wave = 0.4 + out * 0.7;
      } else if (s === "thinking") {
        glow = 0.6 + 0.08 * Math.sin(t * 0.7);
        core = 0.65 + 0.12 * Math.sin(t * 1.7);
        pulse = 0.45 + 0.12 * Math.sin(t * 1.15);
        spin = 0.7;
        wave = 0.5 + 0.15 * Math.sin(t * 2);
      } else if (s === "speaking") {
        glow = 0.8 + inn * 2.0;
        core = 0.9 + inn * 2.2;
        pulse = 0.7 + inn * 1.5;
        wave = 0.7 + inn * 1.8;
        spin = 0.25 + inn * 0.35;
      } else if (s === "connecting") {
        glow = 0.5 + 0.1 * Math.sin(t * 2.4);
        core = 0.45 + 0.12 * Math.sin(t * 3);
        spin = 0.9;
      } else if (s === "interrupted") {
        glow = 0.45;
        core = 0.35;
        pulse = 0.3;
      }

      return {
        glow: clamp(glow, 0, 2.8),
        core: clamp(core, 0, 3),
        pulse: clamp(pulse, 0, 2.5),
        wave: clamp(wave, 0, 3),
        spin,
        breath,
      };
    }

    _draw(now) {
      const ctx = this.ctx;
      const S = this.cssSize;
      if (!S || !ctx) return;

      const t = (now - this.t0) / 1000;
      const pal = this.palette;
      const m = this._mood(t);

      this.host.style.setProperty("--vp-pulse", String(m.pulse));
      this.host.style.setProperty("--vp-energy", String(m.glow));
      this.host.style.setProperty("--vp-face", String(m.core));

      ctx.clearRect(0, 0, S, S);

      const cx = S * 0.5;
      const cy = S * 0.5;
      const baseR = S * 0.28;
      const scale = 1 + Math.sin(t * 1.05) * 0.018 + m.glow * 0.012;
      const R = baseR * scale;

      // Far bloom
      const bloom = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 2.1);
      bloom.addColorStop(0, rgba(pal.mid, 0.16 + m.glow * 0.08));
      bloom.addColorStop(0.45, rgba(pal.mid, 0.06 + m.glow * 0.03));
      bloom.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = bloom;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 2.1, 0, Math.PI * 2);
      ctx.fill();

      // Main orb body — multi-stop sphere
      const body = ctx.createRadialGradient(
        cx - R * 0.28,
        cy - R * 0.32,
        R * 0.05,
        cx,
        cy,
        R
      );
      body.addColorStop(0, rgba(pal.hot, 0.95));
      body.addColorStop(0.22, rgba(pal.hot, 0.7));
      body.addColorStop(0.5, rgba(pal.mid, 0.92));
      body.addColorStop(0.78, rgba(pal.dim, 0.95));
      body.addColorStop(1, rgba(pal.deep, 0.98));
      ctx.fillStyle = body;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();

      // Inner luminous core
      const coreR = R * (0.38 + m.core * 0.06);
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 1.6);
      core.addColorStop(0, rgba([255, 250, 235], 0.55 + m.core * 0.12));
      core.addColorStop(0.35, rgba(pal.hot, 0.35 + m.core * 0.1));
      core.addColorStop(1, rgba(pal.mid, 0));
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * 1.6, 0, Math.PI * 2);
      ctx.fill();

      // Voice waves inside the orb (alive when she speaks)
      const waves = 4;
      const speed = 1.4 + m.wave * 1.8;
      for (let i = 0; i < waves; i++) {
        const phase = t * speed - i * 0.6;
        const pulse = 0.5 + 0.5 * Math.sin(phase);
        const wr =
          R * (0.18 + i * 0.12) * (1 + m.wave * 0.04) +
          pulse * R * 0.04 * (0.4 + m.wave * 0.4);
        const a =
          (0.22 + m.wave * 0.1) *
          (1 - i / (waves + 0.5)) *
          (0.45 + pulse * 0.55);
        ctx.beginPath();
        ctx.ellipse(cx, cy, wr * 1.15, wr * 0.55, 0, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(pal.hot, clamp(a, 0, 0.7));
        ctx.lineWidth = 1.1 + m.wave * 0.25;
        ctx.stroke();
      }

      // Slow orbit ring on the surface
      const orbit = t * (0.35 + m.spin * 0.4);
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.72, orbit, orbit + Math.PI * 1.25);
      ctx.strokeStyle = rgba(pal.hot, 0.18 + m.glow * 0.06);
      ctx.lineWidth = 1;
      ctx.stroke();

      // Rim light
      ctx.beginPath();
      ctx.arc(cx, cy, R - 0.5, 0, Math.PI * 2);
      ctx.strokeStyle = rgba(pal.hot, 0.28 + m.glow * 0.08);
      ctx.lineWidth = 1.25;
      ctx.stroke();

      // Soft bottom shade (volume)
      const shade = ctx.createRadialGradient(cx, cy + R * 0.35, 0, cx, cy + R * 0.2, R * 0.9);
      shade.addColorStop(0, "rgba(0,0,0,0.18)");
      shade.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = shade;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();

      // Specular highlight
      const spec = ctx.createRadialGradient(
        cx - R * 0.28,
        cy - R * 0.32,
        0,
        cx - R * 0.2,
        cy - R * 0.25,
        R * 0.45
      );
      spec.addColorStop(0, "rgba(255,255,255,0.35)");
      spec.addColorStop(0.4, "rgba(255,255,255,0.08)");
      spec.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = spec;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  global.LivingPresence = LivingPresence;
})(typeof window !== "undefined" ? window : globalThis);
