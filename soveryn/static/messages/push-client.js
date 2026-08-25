/* Enable Web Push for installed Messages PWA (Gate / needs-you).
   Always show a clear Allow path — never a blank header with no agree option. */
(function () {
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function banner() {
    return document.querySelector("[data-push-banner]");
  }

  function setBanner(html, { tone } = {}) {
    const el = banner();
    if (!el) return;
    el.hidden = false;
    el.dataset.tone = tone || "ask";
    el.innerHTML = html;
  }

  function hideBanner() {
    const el = banner();
    if (el) el.hidden = true;
  }

  async function ensureSubscription() {
    if (!pushSupported()) {
      return { ok: false, reason: "unsupported" };
    }
    const reg = await navigator.serviceWorker.register("/messages-sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;

    let perm = Notification.permission;
    if (perm === "default") {
      perm = await Notification.requestPermission();
    }
    if (perm !== "granted") {
      return { ok: false, reason: perm === "denied" ? "denied" : "dismissed" };
    }

    const keyResp = await fetch("/api/push/vapid-public-key");
    if (!keyResp.ok) return { ok: false, reason: "vapid" };
    const { publicKey } = await keyResp.json();
    if (!publicKey) return { ok: false, reason: "vapid" };

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
    }
    const raw = sub.toJSON();
    const save = await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        endpoint: raw.endpoint,
        keys: raw.keys,
      }),
    });
    if (!save.ok) return { ok: false, reason: "subscribe" };
    return { ok: true };
  }

  function paintAsk(canEnable, note) {
    const btn = canEnable
      ? '<button type="button" data-push-allow class="push-allow">Allow house alerts</button>'
      : "";
    setBanner(
      "<div class=\"push-copy\">" +
        "<strong>House alerts</strong> — Gate and needs-you from any citizen (not only Signal)." +
        (note ? "<br><span class=\"push-note\">" + note + "</span>" : "") +
        "</div>" +
        btn,
      { tone: "ask" }
    );
    const allow = document.querySelector("[data-push-allow]");
    if (allow) {
      allow.addEventListener("click", onAllowClick);
    }
  }

  function paintOn() {
    setBanner(
      "<div class=\"push-copy\"><strong>House alerts on</strong> — we’ll wake you for Gate and needs-you.</div>",
      { tone: "on" }
    );
  }

  async function onAllowClick(ev) {
    ev.preventDefault();
    const btn = ev.currentTarget;
    btn.disabled = true;
    btn.textContent = "Asking…";
    const r = await ensureSubscription().catch((e) => ({
      ok: false,
      reason: e && e.message ? e.message : "error",
    }));
    if (r.ok) {
      paintOn();
      return;
    }
    if (r.reason === "denied") {
      paintAsk(
        false,
        "Notifications blocked for this app — iPhone Settings → SOVERYN → Notifications → Allow."
      );
      return;
    }
    paintAsk(
      true,
      "Couldn’t enable (" + (r.reason || "error") + "). Try again from the Home Screen app."
    );
  }

  async function boot() {
    if (!banner()) return;

    // iOS: Web Push only works from the installed Home Screen app.
    if (!isStandalone()) {
      paintAsk(
        false,
        "On iPhone: Safari Share → <strong>Add to Home Screen</strong>, open SOVERYN from the icon, then Allow alerts here."
      );
      // Still register SW when possible so install is ready.
      if ("serviceWorker" in navigator) {
        try {
          await navigator.serviceWorker.register("/messages-sw.js", { scope: "/" });
        } catch (_) {}
      }
      return;
    }

    if (!pushSupported()) {
      paintAsk(
        false,
        "This install doesn’t support Web Push yet — use a current iOS/Android, or reopen from the Home Screen icon."
      );
      return;
    }

    try {
      await navigator.serviceWorker.register("/messages-sw.js", { scope: "/" });
    } catch (_) {}

    if (Notification.permission === "granted") {
      const r = await ensureSubscription().catch(() => ({ ok: false }));
      if (r.ok) {
        paintOn();
        return;
      }
    }
    if (Notification.permission === "denied") {
      paintAsk(
        false,
        "Notifications blocked — iPhone Settings → SOVERYN → Notifications → Allow, then reopen."
      );
      return;
    }
    paintAsk(true, "Tap Allow — we’ll only buzz for Gate and when someone needs you.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
