/* Enable Web Push for installed Messages PWA (Gate / needs-you). */
(function () {
  const KEY = "soveryn_push_prompted";

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function ensureSubscription() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return { ok: false, reason: "unsupported" };
    }
    const reg = await navigator.serviceWorker.register("/messages-sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;

    let perm = Notification.permission;
    if (perm === "default") {
      perm = await Notification.requestPermission();
    }
    if (perm !== "granted") {
      return { ok: false, reason: "denied" };
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

  function paintChip(state) {
    const el = document.querySelector("[data-push-chip]");
    if (!el) return;
    if (state === "on") {
      el.textContent = "Alerts on";
      el.dataset.state = "on";
      el.hidden = false;
    } else if (state === "off") {
      el.textContent = "Enable alerts";
      el.dataset.state = "off";
      el.hidden = false;
    } else {
      el.hidden = true;
    }
  }

  async function boot() {
    const chip = document.querySelector("[data-push-chip]");
    if (!chip) return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      paintChip("hide");
      return;
    }
    // Register SW early so install + push work even before permission.
    try {
      await navigator.serviceWorker.register("/messages-sw.js", { scope: "/" });
    } catch (_) {}

    if (Notification.permission === "granted") {
      const r = await ensureSubscription().catch(() => ({ ok: false }));
      paintChip(r.ok ? "on" : "off");
      return;
    }
    paintChip("off");
    chip.addEventListener("click", async (ev) => {
      ev.preventDefault();
      chip.textContent = "…";
      const r = await ensureSubscription().catch(() => ({ ok: false }));
      paintChip(r.ok ? "on" : "off");
      try { localStorage.setItem(KEY, "1"); } catch (_) {}
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
