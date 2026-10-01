/* SOVERYN Messages service worker — Web Push for Gate / needs-you. */
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = { title: "SOVERYN", body: "Needs you", url: "/messages", tag: "soveryn" };
  try {
    if (event.data) {
      const parsed = event.data.json();
      data = Object.assign(data, parsed || {});
    }
  } catch (_) {
    try {
      const t = event.data && event.data.text();
      if (t) data.body = t.slice(0, 140);
    } catch (__) {}
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "SOVERYN", {
      body: data.body || "",
      icon: "/static/messages/icons/icon-192.png",
      badge: "/static/messages/icons/icon-192.png",
      tag: data.tag || "soveryn-needs-you",
      renotify: true,
      data: { url: data.url || "/messages" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/messages";
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of all) {
        if ("focus" in client) {
          await client.focus();
          if ("navigate" in client) {
            try { await client.navigate(target); } catch (_) {}
          }
          return;
        }
      }
      if (self.clients.openWindow) {
        await self.clients.openWindow(target);
      }
    })()
  );
});
