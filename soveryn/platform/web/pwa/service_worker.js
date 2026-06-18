// soveryn/platform/web/pwa/service_worker.js
// Lifecycle + outbox drain.
//
// On `sync` with tag `soveryn-outbox-drain`, open IDB `soveryn` v1, walk the
// `outbox` store, and re-POST each entry. The server's idempotency layer
// (Task 6) keys on `client_msg_id` so replays are safe — same id in, same
// envelope out, no duplicate writes. Entries that succeed are deleted; ones
// that still fail stay queued for the next sync trigger.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('sync', e => {
  if (e.tag !== 'soveryn-outbox-drain') return;
  e.waitUntil((async () => {
    const db = await new Promise((res, rej) => {
      const r = indexedDB.open('soveryn', 1);
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    const all = await new Promise(r => {
      const req = db.transaction('outbox').objectStore('outbox').getAll();
      req.onsuccess = () => r(req.result || []);
      req.onerror = () => r([]);
    });
    for (const entry of all) {
      try {
        const resp = await fetch(entry.url, {
          method: 'POST',
          headers: entry.headers,
          body: entry.body,
        });
        if (resp.ok) {
          const txw = db.transaction('outbox', 'readwrite');
          txw.objectStore('outbox').delete(entry.client_msg_id);
        }
      } catch (err) { /* network still bad; leave in outbox */ }
    }
  })());
});
