// soveryn/platform/web/pwa/app.js
// Minimal vanilla-JS SPA.
// Stores device secret in IndexedDB; renders thread list + thread view.

const $app = document.getElementById('app');

// IDB placeholder — full IndexedDB (outbox + secret store) lands in Task 14.
// For now, secret persistence falls back to localStorage.
const IDB = {
  // Reserved namespace; Task 14 wires open()/get()/put()/outbox here.
};

async function loadSecret() {
  // IndexedDB fetch — falls back to null if not paired
  // (Full IDB implementation in Task 14)
  return localStorage.getItem('soveryn_device_secret');
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
    localStorage.setItem('soveryn_device_secret', j.secret);
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
    // Fire request; rendering loop lands in Task 13
    const r = await fetch(`/m/threads/${tid}/send_stream`, {
      method: 'POST',
      headers: {
        'Content-Type':'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        client_msg_id: crypto.randomUUID(),
        agent: currentThreadAgent,
        content: text,
        device_id: '',
        client_ts: new Date().toISOString(),
      }),
    });
    // Stub rendering — Task 13 swaps this for streamed message DOM with
    // `msg.className = \`message agent-${currentThreadAgent}\`` driving the
    // Sovereign Edge contract.
    const msgs = document.getElementById('messages');
    const msg = document.createElement('div');
    msg.className = `message agent-${currentThreadAgent}`;
    const label = document.createElement('div');
    label.className = 'agent-label';
    label.textContent = currentThreadAgent.toUpperCase();
    const content = document.createElement('div');
    content.className = 'message-content';
    try {
      content.textContent = JSON.stringify(await r.json(), null, 2);
    } catch (e) {
      content.textContent = await r.text();
    }
    msg.appendChild(label);
    msg.appendChild(content);
    msgs.appendChild(msg);
  };
}

(async function init() {
  const secret = await loadSecret();
  if (!secret) renderPairingScreen();
  else renderThreadList();
})();
