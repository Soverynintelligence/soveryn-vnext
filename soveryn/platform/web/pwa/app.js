// soveryn/platform/web/pwa/app.js
// Vanilla-JS PWA shell — paired-device messenger with app-furniture
// navigation (Task 241). Header + view-stack + sliding transitions so it
// stops feeling like a webpage and starts feeling like an app.
//
// Design contract (Aetheria, 2026-06-14): see style.css preamble. The
// chrome is mono caps + Void-Gold accents, the agent labels carry the
// asymmetric weight (Aetheria gold, Vett/Scotty muted).

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

// --- Agent presentation -----------------------------------------------------
const AGENT_TAGLINE = {
  aetheria: 'Strategy + coordination',
  vett:     'Research + verification',
  scotty:   'Execution + bounded fixes',
};

// Relative-time helper for thread cards ("2h", "now", "Mon").
// Falls back to date for >6d.
function relativeTime(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const delta = (Date.now() - t) / 1000;
  if (delta < 45) return 'now';
  if (delta < 60 * 60) return `${Math.round(delta / 60)}m`;
  if (delta < 60 * 60 * 24) return `${Math.round(delta / 3600)}h`;
  if (delta < 60 * 60 * 24 * 7) return `${Math.round(delta / 86400)}d`;
  const d = new Date(t);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

// --- Navigation stack -------------------------------------------------------
// Single source of truth for which view is on screen. Each entry is a
// {kind, params} record; render() rebuilds the view container from it.
// `back()` pops; `push()` pushes; both animate.
const navStack = [];

function currentView() {
  return navStack[navStack.length - 1] || null;
}

function ensureShell() {
  if (document.getElementById('view-stack')) return;
  $app.innerHTML = `
    <header class="app-header">
      <div class="app-header-inner">
        <div class="app-header-left"  id="hdr-left"></div>
        <div class="app-header-title" id="hdr-title"></div>
        <div class="app-header-right" id="hdr-right"></div>
      </div>
    </header>
    <div id="view-stack"></div>
  `;
}

function setHeader({ title, agent, showBack, rightHtml, onBack, onRight }) {
  const $left  = document.getElementById('hdr-left');
  const $title = document.getElementById('hdr-title');
  const $right = document.getElementById('hdr-right');
  $left.innerHTML  = showBack
    ? `<button class="icon-btn" id="hdr-back" aria-label="Back">&larr;</button>`
    : '';
  $title.innerHTML = escapeHtml(title || '');
  $title.className = `app-header-title${agent ? ' agent-' + agent : ''}`;
  $right.innerHTML = rightHtml || '';
  if (showBack) {
    document.getElementById('hdr-back').onclick = onBack || back;
  }
  if (onRight && $right.firstElementChild) {
    $right.firstElementChild.onclick = onRight;
  }
}

// Push a new view on top of the stack with a slide-in-from-right transition.
// `direction` defaults to 'push' (slide in from right). 'pop' slides out the
// current view to the right, revealing the previous (already-rendered) one.
async function push(view) {
  navStack.push(view);
  await renderTop('push');
}

async function back() {
  if (navStack.length <= 1) return;
  navStack.pop();
  await renderTop('pop');
}

// Replace the entire stack (used for pairing → list transition, or after
// creating a fresh thread from the agent picker — we don't want the picker
// sitting in history once the thread opens).
async function reset(view) {
  navStack.length = 0;
  navStack.push(view);
  await renderTop('replace');
}

async function renderTop(direction) {
  ensureShell();
  const $stack = document.getElementById('view-stack');
  const view = currentView();
  if (!view) return;

  // Build the new view DOM in detached form, then mount it.
  const $new = document.createElement('section');
  $new.className = 'view ' + (view.kind === 'thread' ? 'view-thread' : '');
  $new.dataset.kind = view.kind;
  await VIEW_RENDERERS[view.kind]($new, view.params || {});

  const $old = $stack.querySelector('.view');

  if (direction === 'replace' || !$old) {
    $stack.innerHTML = '';
    $stack.appendChild($new);
    return;
  }

  if (direction === 'pop') {
    // New view mounts underneath, old view slides out to the right.
    $stack.insertBefore($new, $old);
    $old.classList.add('leave-active');
    // Force reflow so the transition kicks off.
    // eslint-disable-next-line no-unused-expressions
    $old.offsetHeight;
    $old.style.transform = 'translateX(100%)';
    await wait(200);
    $old.remove();
    return;
  }

  // push — new view starts off-screen-right (absolute), slides in over old.
  // Use `enter-right` (which carries position:absolute via the .view styles
  // we add inline below) so the slide overlays the old view rather than
  // pushing it down the document.
  $new.style.position = 'absolute';
  $new.style.top = 'calc(var(--header-h) + env(safe-area-inset-top, 0px))';
  $new.style.left = '0';
  $new.style.right = '0';
  $new.style.transform = 'translateX(100%)';
  $stack.appendChild($new);
  // eslint-disable-next-line no-unused-expressions
  $new.offsetHeight;
  $new.style.transition = 'transform 200ms ease-out';
  $new.style.transform = 'translateX(0)';
  await wait(200);
  // Drop the absolute positioning so subsequent renders work normally.
  $new.style.transition = '';
  $new.style.position = '';
  $new.style.top = '';
  $new.style.left = '';
  $new.style.right = '';
  $new.style.transform = '';
  if ($old) $old.remove();
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

// --- View renderers --------------------------------------------------------
const VIEW_RENDERERS = {
  pairing:      renderPairingView,
  'thread-list': renderThreadListView,
  'agent-pick':  renderAgentPickView,
  thread:       renderThreadView,
};

async function renderPairingView($view) {
  setHeader({
    title: 'SOVERYN',
    showBack: false,
    rightHtml: '',
  });
  $view.innerHTML = `
    <div class="pairing-wrap">
      <h1>SOVERYN</h1>
      <p>Not paired. Open localhost:5001/m/pair on the workstation, mint a code, paste it here:</p>
      <input id="pair-code" class="pairing-input" placeholder="ABCD-EFGH-1234">
      <div style="margin-top:16px">
        <button class="btn" id="pair-submit">Claim</button>
      </div>
    </div>
  `;
  $view.querySelector('#pair-submit').onclick = async () => {
    const code = $view.querySelector('#pair-code').value.trim();
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

async function renderThreadListView($view) {
  const secret = await loadSecret();
  setHeader({
    title: 'SOVERYN',
    showBack: false,
    rightHtml: `<button class="icon-btn accent" id="hdr-new" aria-label="New conversation">+</button>`,
    onRight: () => push({ kind: 'agent-pick' }),
  });

  let threads = [];
  try {
    threads = await fetchThreads(secret);
  } catch (e) {
    $view.innerHTML = `<div class="thread-list-empty">Couldn't load threads.</div>`;
    return;
  }

  if (!threads.length) {
    $view.innerHTML = `
      <div class="thread-list-empty">
        NO CONVERSATIONS YET<br>
        <span style="opacity:0.5">Tap + to start one.</span>
      </div>
    `;
    return;
  }

  $view.innerHTML = `
    <div id="thread-list">
      ${threads.map(t => `
        <div class="thread-card${t.unread ? ' has-unread' : ''}"
             data-tid="${escapeHtml(t.thread_id)}"
             data-agent="${escapeHtml(t.agent)}">
          <span class="agent-dot agent-dot thread-card-dot agent-${escapeHtml(t.agent)}"></span>
          <div class="thread-card-body">
            <div class="thread-card-row1">
              <span class="thread-card-name agent-${escapeHtml(t.agent)}">${escapeHtml(t.agent)}</span>
              <span class="thread-card-time">${escapeHtml(relativeTime(t.last_activity))}</span>
            </div>
            <div class="thread-card-preview${t.last_message_preview ? '' : ' empty'}">
              ${t.last_message_preview ? escapeHtml(t.last_message_preview) : 'No messages yet'}
            </div>
          </div>
          <span class="thread-card-unread" aria-hidden="true"></span>
        </div>
      `).join('')}
    </div>
  `;
  for (const el of $view.querySelectorAll('.thread-card')) {
    el.onclick = () => push({
      kind: 'thread',
      params: { tid: el.dataset.tid, agent: el.dataset.agent },
    });
  }
}

async function renderAgentPickView($view) {
  setHeader({
    title: 'NEW CONVERSATION',
    showBack: true,
    rightHtml: '',
  });
  const agents = ['aetheria', 'vett', 'scotty'];
  $view.innerHTML = `
    <div id="agent-pick-list">
      ${agents.map(a => `
        <div class="agent-pick-card" data-agent="${a}">
          <span class="agent-dot agent-${a}"></span>
          <div>
            <div class="agent-pick-name agent-${a}">${a.toUpperCase()}</div>
            <div class="agent-pick-tagline">${escapeHtml(AGENT_TAGLINE[a] || '')}</div>
          </div>
        </div>
      `).join('')}
    </div>
  `;
  for (const el of $view.querySelectorAll('.agent-pick-card')) {
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
      if (j.error) { alert(j.error); return; }
      // Replace the picker with the thread list + thread on top, so back
      // from the thread returns to the list (not the now-stale picker).
      navStack.length = 0;
      navStack.push({ kind: 'thread-list' });
      await push({
        kind: 'thread',
        params: { tid: j.thread_id, agent },
      });
    };
  }
}

async function renderThreadView($view, { tid, agent }) {
  const currentThreadAgent = agent || 'aetheria';
  setHeader({
    title: currentThreadAgent.toUpperCase(),
    agent: currentThreadAgent,
    showBack: true,
    rightHtml: `<span class="agent-dot agent-${currentThreadAgent}" style="margin:0 12px"></span>`,
  });
  $view.innerHTML = `
    <div id="messages"></div>
    <div class="compose-box">
      <div class="compose-inner">
        <textarea id="compose" rows="2" placeholder="Write..."></textarea>
        <button class="btn send-btn" id="send">Send</button>
      </div>
    </div>
  `;
  const $send = $view.querySelector('#send');
  $send.onclick = () => sendMessage(tid, currentThreadAgent, $view);

  // Rehydrate the thread's prior messages from the server. Fix for the
  // 2026-06-15 bug Jon flagged: re-entering a thread used to render an
  // empty list because the client never fetched history.
  await loadAndRenderHistory(tid, currentThreadAgent, $view);
}

async function loadAndRenderHistory(tid, currentThreadAgent, $view) {
  const secret = await loadSecret();
  if (!secret) return;
  let data;
  try {
    const r = await fetch(`/m/threads/${tid}/messages`, {
      headers: { Authorization: `Bearer ${secret}` },
    });
    if (!r.ok) return;
    data = await r.json();
  } catch (e) {
    return; // offline / network blip — just render empty; next send still works
  }
  const msgsEl = $view.querySelector('#messages');
  if (!msgsEl || !data || !data.messages) return;
  for (const turn of data.messages) {
    const msg = document.createElement('div');
    const label = document.createElement('div');
    label.className = 'agent-label';
    const content = document.createElement('div');
    content.className = 'message-content';
    content.textContent = turn.content || '';
    if (turn.role === 'user') {
      // User messages: no agent class (neutral) per spec §14 Q4
      msg.className = 'message';
      label.textContent = 'YOU';
    } else if (turn.role === 'assistant') {
      // Agent messages: asymmetric weight via agent-class
      // (Aetheria gets the Sovereign Edge; Vett/Scotty stay compact)
      msg.className = `message agent-${currentThreadAgent}`;
      label.textContent = currentThreadAgent.toUpperCase();
    } else {
      continue; // skip tool/system turns for the messenger surface
    }
    msg.appendChild(label);
    msg.appendChild(content);
    msgsEl.appendChild(msg);
  }
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

async function sendMessage(tid, currentThreadAgent, $view) {
  const secret = await loadSecret();
  const $compose = $view.querySelector('#compose');
  const text = $compose.value;
  if (!text.trim()) return;
  const msgsEl = $view.querySelector('#messages');

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
  $compose.value = '';

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
  agentMsg.scrollIntoView({ behavior: 'smooth', block: 'end' });

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
        agentMsg.scrollIntoView({ block: 'end' });
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
  if (!secret) {
    await reset({ kind: 'pairing' });
  } else {
    await reset({ kind: 'thread-list' });
  }
  showInstallBanner();
})();
