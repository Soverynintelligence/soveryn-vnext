// soveryn/platform/web/pwa/service_worker.js
// Minimal — IDB outbox + offline retry land in Task 14.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
