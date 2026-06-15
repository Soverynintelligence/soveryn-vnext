// soveryn/platform/web/pwa/app.js
// Minimal vanilla-JS SPA.
// Stores device secret in IndexedDB; renders thread list + thread view.

const $app = document.getElementById('app');

// IndexedDB wrapper — single DB `soveryn` v1, two stores: `secret` (kv) and
// `outbox` (keyPath: client_msg_id). The outbox is the pre/post-flight bracket
// around send_stream; the service worker drains it on the `sync` event so
// retries reuse the same client_msg_id and ride the server's idempotency layer.
const IDB = {
  _db: null,
  async open() {
    if (this._db) return this._db;
    return new Promise((resolve, reject) => {
      const req = indexedDB.open('soveryn', 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        db.createObjectStore('secret');
        db.createObjectStore('outbox', { keyPath: 'client_msg_id' });
      };
      req.onsuccess = () => { this._db = req.result; resolve(this._db); };
      req.onerror = () => reject(req.error);
    });
  },
  async getSecret() {
    const db = await this.open();
    return new Promise(res => {
      const r = db.transaction('secret').objectStore('secret').get('value');
      r.onsuccess = () => res(r.result || null);
      r.onerror = () => res(null);
    });
  },
  async setSecret(value) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('secret', 'readwrite');
      tx.objectStore('secret').put(value, 'value');
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  },
  async outboxPut(entry) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('outbox', 'readwrite');
      tx.objectStore('outbox').put(entry);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  },
  async outboxList() {
    const db = await this.open();
    return new Promise(res => {
      const r = db.transaction('outbox').objectStore('outbox').getAll();
      r.onsuccess = () => res(r.result || []);
      r.onerror = () => res([]);
    });
  },
  async outboxDelete(id) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('outbox', 'readwrite');
      tx.objectStore('outbox').delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  },
};

async function loadSecret() {
  return await IDB.getSecret();
}

async function fetchThreads(secret) {
  const r = await fetch('/m/threads', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (!r.ok) throw new Error('threads fetch failed');
  return (await r.json()).threads;
}

function renderPairingScreen() {
  $app.innerHTML = `
    <h1>SOVERYN</h1>
    <p style="color:var(--muted)">Not paired. Open localhost:5001/m/pair on the workstation, mint a code, paste it here:</p>
    <input id="pair-code" placeholder="ABCD-EFGH-1234" style="background:transparent;color:var(--fg);border:1px solid var(--rule);padding:12px;width:100%;font-family:var(--font-mono);">
    <button class="btn" id="pair-submit" style="margin-top:16px">Claim</button>
  `;
  document.getElementById('pair-submit').onclick = async () => {
    const code = document.getElementById('pair-code').value.trim();
    const r = await fetch(`/m/pair/${code}`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({device_label: 'Phone'}),
    });
    const j = await r.json();
    if (j.error) { alert(j.error); return; }
    await IDB.setSecret(j.secret);
    location.reload();
  };
}

async function renderThreadList() {
  const secret = await loadSecret();
  const threads = await fetchThreads(secret);
  $app.innerHTML = `
    <h1>SOVERYN</h1>
    <button class="btn" id="new-thread">+ New conversation</button>
    <div id="thread-list">
      ${threads.map(t => `
        <div class="thread-list-item" data-tid="${t.thread_id}" data-agent="${t.agent}">
          <div class="agent-label">${t.agent.toUpperCase()}</div>
          <div>${t.title}</div>
          <div class="timestamp">${t.last_activity}</div>
        </div>
      `).join('')}
    </div>
  `;
  document.getElementById('new-thread').onclick = renderNewThreadPicker;
  for (const el of document.querySelectorAll('.thread-list-item')) {
    el.onclick = () => renderThread(el.dataset.tid, el.dataset.agent);
  }
}

function renderNewThreadPicker() {
  $app.innerHTML = `
    <h2>Who?</h2>
    <div>
      ${['aetheria','vett','scotty'].map(a => `
        <div class="thread-list-item" data-agent="${a}">${a.toUpperCase()}</div>
      `).join('')}
    </div>
  `;
  for (const el of document.querySelectorAll('[data-agent]')) {
    el.onclick = async () => {
      const secret = await loadSecret();
      const agent = el.dataset.agent;
      const r = await fetch('/m/threads', {
        method: 'POST',
        headers: {
          'Content-Type':'application/json',
          'Authorization': `Bearer ${secret}`,
        },
        body: JSON.stringify({agent}),
      });
      const j = await r.json();
      renderThread(j.thread_id, agent);
    };
  }
}

async function renderThread(tid, agent) {
  // Minimal: just compose-box for now. Message history rendering lands in Task 13.
  // `currentThreadAgent` carries the agent identity so when message DOM is
  // appended (here and in Task 13), the `.message agent-${currentThreadAgent}`
  // class can drive the asymmetric-weight CSS contract.
  const currentThreadAgent = agent || 'aetheria';
  $app.innerHTML = `
    <h2>Thread ${tid.slice(0, 8)}</h2>
    <div id="messages"></div>
    <div class="compose-box">
      <textarea id="compose" rows="3" placeholder="Write..."></textarea>
      <button class="btn" id="send">Send</button>
    </div>
  `;
  document.getElementById('send').onclick = async () => {
    const secret = await loadSecret();
    const text = document.getElementById('compose').value;
    if (!text.trim()) return;
    const msgsEl = document.getElementById('messages');
    // Echo user message (Jon's messages stay neutral — no agent class
    // per spec §14 Q4; only agent replies carry the asymmetric weight).
    const userMsg = document.createElement('div');
    userMsg.className = 'message';
    const userLabel = document.createElement('div');
    userLabel.className = 'agent-label';
    userLabel.textContent = 'YOU';
    const userContent = document.createElement('div');
    userContent.className = 'message-content';
    userContent.textContent = text;
    userMsg.appendChild(userLabel);
    userMsg.appendChild(userContent);
    msgsEl.appendChild(userMsg);
    document.getElementById('compose').value = '';
    // Stream agent reply — agent class drives the asymmetric styling
    // (Aetheria gets the Sovereign Edge; Vett/Scotty stay compact).
    const agentMsg = document.createElement('div');
    agentMsg.className = `message agent-${currentThreadAgent}`;
    const agentLabel = document.createElement('div');
    agentLabel.className = 'agent-label';
    agentLabel.textContent = currentThreadAgent.toUpperCase();
    const contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    agentMsg.appendChild(agentLabel);
    agentMsg.appendChild(contentEl);
    msgsEl.appendChild(agentMsg);
    // Outbox bracket — write entry BEFORE the fetch so a network failure
    // mid-flight leaves a durable record. Body is pre-serialized JSON so the
    // service worker can pass it straight through to fetch() on retry; headers
    // are a plain object (not a Headers instance) so they survive IDB
    // round-trip cleanly.
    const client_msg_id = crypto.randomUUID();
    const url = `/m/threads/${tid}/send_stream`;
    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${secret}`,
    };
    const body = JSON.stringify({
      client_msg_id,
      agent: currentThreadAgent,
      content: text,
      device_id: '',
      client_ts: new Date().toISOString(),
    });
    await IDB.outboxPut({ client_msg_id, url, headers, body });
    let r;
    try {
      r = await fetch(url, { method: 'POST', headers, body });
    } catch (netErr) {
      // Network failure — entry stays in outbox. Register a background-sync
      // so the SW drains it once connectivity returns. Server idempotency
      // (Task 6) makes the same client_msg_id replay safe.
      contentEl.textContent = '[queued for retry — offline]';
      if ('serviceWorker' in navigator && 'SyncManager' in self) {
        try {
          const reg = await navigator.serviceWorker.ready;
          await reg.sync.register('soveryn-outbox-drain');
        } catch (e) { /* sync register best-effort */ }
      }
      return;
    }
    if (!r.ok) {
      contentEl.textContent += `\n[error: HTTP ${r.status}]`;
      return;
    }
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const evt = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (!evt.startsWith('data: ')) continue;
        let payload;
        try {
          payload = JSON.parse(evt.slice(6));
        } catch (e) {
          continue;
        }
        if (payload.type === 'token') {
          contentEl.textContent += payload.delta;
        } else if (payload.type === 'tool_call') {
          console.log('tool_call', payload);
        } else if (payload.type === 'tool_result') {
          console.log('tool_result', payload);
        } else if (payload.type === 'done') {
          // final marker — content already accumulated
        } else if (payload.type === 'error') {
          contentEl.textContent += `\n[error: ${payload.message}]`;
        }
      }
    }
    // Stream completed successfully — clear the outbox entry.
    await IDB.outboxDelete(client_msg_id);
  };
}

// Register the service worker so its `sync` listener can drain the outbox
// when the browser sees connectivity return. Best-effort — Firefox lacks
// Background Sync; in that case the SW still installs and the next manual
// send replays from the outbox via the regular send flow.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/m/pwa/service_worker.js').catch(() => {});
}

// --- Install banner ---------------------------------------------------------
// iOS Safari ignores beforeinstallprompt; the only path is share sheet →
// Add to Home Screen. We surface a slide-up banner with the instruction.
// On Chromium/Android we capture beforeinstallprompt and offer a real button.
// Either way: dismiss is remembered for 7 days so it doesn't nag.
function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true;
}
function isIOSSafari() {
  const ua = navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
}
function installBannerDismissed() {
  const ts = localStorage.getItem('soveryn_install_banner_dismissed');
  if (!ts) return false;
  const sevenDays = 7 * 24 * 60 * 60 * 1000;
  return (Date.now() - parseInt(ts, 10)) < sevenDays;
}

let deferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
});

function showInstallBanner() {
  if (isStandalone() || installBannerDismissed()) return;
  // Only surface on iOS (instructional) or where a native prompt is queued.
  // Other browsers skip silently — desktop Chrome will surface its own omnibar
  // affordance and Firefox lacks install entirely.
  const ios = isIOSSafari();
  if (!ios && !deferredInstallPrompt) {
    // Give beforeinstallprompt a moment to fire on first paint, then re-check.
    setTimeout(() => {
      if (deferredInstallPrompt && !isStandalone() && !installBannerDismissed()) {
        renderInstallBanner(false);
      }
    }, 1500);
    return;
  }
  renderInstallBanner(ios);
}

function renderInstallBanner(ios) {
  if (document.getElementById('install-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'install-banner';
  banner.innerHTML = ios
    ? `<div class="install-text">Install SOVERYN — tap <strong>Share</strong> then <strong>Add to Home Screen</strong></div>
       <button class="install-dismiss" aria-label="Dismiss">&times;</button>`
    : `<div class="install-text">Install SOVERYN as an app</div>
       <button class="install-do">Install</button>
       <button class="install-dismiss" aria-label="Dismiss">&times;</button>`;
  document.body.appendChild(banner);
  banner.querySelector('.install-dismiss').onclick = () => {
    localStorage.setItem('soveryn_install_banner_dismissed', Date.now().toString());
    banner.remove();
  };
  const installBtn = banner.querySelector('.install-do');
  if (installBtn) {
    installBtn.onclick = async () => {
      if (!deferredInstallPrompt) return;
      deferredInstallPrompt.prompt();
      try {
        await deferredInstallPrompt.userChoice;
      } catch (e) { /* best-effort */ }
      deferredInstallPrompt = null;
      banner.remove();
    };
  }
}

(async function init() {
  const secret = await loadSecret();
  if (!secret) renderPairingScreen();
  else renderThreadList();
  showInstallBanner();
})();
