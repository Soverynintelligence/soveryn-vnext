// soveryn/platform/web/pwa/control.js
//
// Mission Control inside the app — parity with desktop Command Center.
//
// Loaded after app.js and deliberately additive: it registers its own view
// renderers into VIEW_RENDERERS and adds a tab layer to the shell. The chat
// code is not modified — a working, paired, installed messenger is not worth
// risking to add a dashboard.
//
// Data comes from /m/api/* (device-bearer auth, see
// soveryn/app/routes/mobile_api.py). NOT from /api/*, which is behind the
// basic-auth gate the app cannot use.
//
// Layout: one implementation, two shapes. Phone gets a bottom tab bar above the
// home indicator; iPad gets the same tabs as a left sidebar. That is a media
// query, not a second codebase — see style.css.

(function () {
  'use strict';

  const TABS = [
    { id: 'control', label: 'Control', view: 'control-home', glyph: '▚' },
    { id: 'team',    label: 'Team',    view: 'thread-list',  glyph: '◗' },
  ];

  // Ops poll timers live for the life of the Control view.
  let brainPoll = null;
  let testPoll = null;

  function clearOpsPolls() {
    if (brainPoll) { clearInterval(brainPoll); brainPoll = null; }
    if (testPoll)  { clearInterval(testPoll);  testPoll = null; }
  }

  // ── data ───────────────────────────────────────────────────────────────────

  async function api(path, opts = {}) {
    const secret = await loadSecret();
    if (!secret) throw new Error('unpaired');
    const method = (opts.method || 'GET').toUpperCase();
    const headers = { Authorization: `Bearer ${secret}` };
    let body;
    if (method !== 'GET' && opts.body != null) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    const r = await fetch(`/m/api/${path}`, { method, headers, body });
    if (r.status === 401) throw new Error('unpaired');
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = (data && (data.message || data.error)) || `http ${r.status}`;
      const err = new Error(msg);
      err.status = r.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  // Every panel fetches independently. One slow or broken endpoint degrades its
  // own card rather than blanking the screen — a dashboard that shows nothing
  // because one number is missing is worse than one that admits the gap.
  async function settled(path) {
    try { return { ok: true, data: await api(path) }; }
    catch (e) { return { ok: false, error: String(e.message || e) }; }
  }

  // ── rendering helpers ──────────────────────────────────────────────────────

  function card(title, bodyHtml, opts = {}) {
    return `
      <section class="mc-card${opts.wide ? ' mc-card-wide' : ''}${opts.hud ? ' mc-card-hud' : ''}">
        <h2 class="mc-card-title">${escapeHtml(title)}</h2>
        <div class="mc-card-body">${bodyHtml}</div>
      </section>`;
  }

  function unavailable(msg) {
    // Say which thing is missing and why. "—" in a dashboard reads as zero.
    return `<p class="mc-unavailable">unavailable · ${escapeHtml(msg)}</p>`;
  }

  function statRow(label, value, tone) {
    return `
      <div class="mc-stat">
        <span class="mc-stat-label">${escapeHtml(label)}</span>
        <span class="mc-stat-value${tone ? ' tone-' + tone : ''}">${escapeHtml(String(value))}</span>
      </div>`;
  }

  function skeleton(n = 3) {
    return Array.from({ length: n }, () => `<div class="mc-skel"></div>`).join('');
  }

  function relTime(iso) {
    if (!iso) return '—';
    const t = Date.parse(iso);
    if (!t) return String(iso);
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 90) return 'just now';
    if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
    if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
    return Math.floor(sec / 86400) + 'd ago';
  }

  function statusClass(st) {
    if (st === 'ok') return 'ok';
    if (st === 'failed') return 'fail';
    if (st === 'running' || st === 'starting') return 'run';
    return '';
  }

  // ── panels ─────────────────────────────────────────────────────────────────

  async function panelOps($slot) {
    // Brain switch + test runner — same ops as desktop Command Center, via
    // device-auth POST /m/api/ops/* instead of localhost-only /api/ops/*.
    const [brainR, testsR] = await Promise.all([
      settled('ops/brain'),
      settled('ops/tests'),
    ]);

    if (!brainR.ok && !testsR.ok) {
      return ($slot.innerHTML = unavailable(brainR.error || testsR.error));
    }

    $slot.innerHTML = `
      <div class="mc-ops">
        <div class="mc-ops-block">
          <div class="mc-ops-h">Spark brain</div>
          <div class="mc-ops-meta" data-ops-brain-meta>…</div>
          <div class="mc-ops-row" data-ops-brain-buttons></div>
          <div class="mc-ops-status" data-ops-brain-status></div>
          <pre class="mc-ops-log" data-ops-brain-log hidden></pre>
        </div>
        <div class="mc-ops-block">
          <div class="mc-ops-h">Run tests</div>
          <div class="mc-ops-meta">Presets hit real pytest — no agent required.</div>
          <div class="mc-ops-row" data-ops-test-buttons></div>
          <div class="mc-ops-status" data-ops-test-status></div>
          <pre class="mc-ops-log" data-ops-test-log hidden></pre>
        </div>
      </div>`;

    const $brainMeta = $slot.querySelector('[data-ops-brain-meta]');
    const $brainBtns = $slot.querySelector('[data-ops-brain-buttons]');
    const $brainStatus = $slot.querySelector('[data-ops-brain-status]');
    const $brainLog = $slot.querySelector('[data-ops-brain-log]');
    const $testBtns = $slot.querySelector('[data-ops-test-buttons]');
    const $testStatus = $slot.querySelector('[data-ops-test-status]');
    const $testLog = $slot.querySelector('[data-ops-test-log]');

    function setStatus(el, cls, text) {
      if (!el) return;
      el.className = 'mc-ops-status' + (cls ? ' ' + cls : '');
      el.textContent = text || '';
    }
    function setLog(el, text) {
      if (!el) return;
      if (text && String(text).trim()) {
        el.textContent = text;
        el.hidden = false;
      } else {
        el.textContent = '';
        el.hidden = true;
      }
    }

    function paintBrain(d) {
      if (!d || brainR.ok === false && !d.brain) {
        $brainMeta.textContent = 'ops brain unavailable · ' + (brainR.error || '');
        return;
      }
      const cur = d.brain || '?';
      $brainMeta.innerHTML =
        'Active: <b>' + escapeHtml(cur) + '</b> · <code>' +
        escapeHtml(d.routed_alias || d.alias || '—') + '</code>' +
        (d.role ? '<br>' + escapeHtml(d.role) : '');
      $brainBtns.innerHTML = (d.brains || []).map(b => {
        const active = b.id === cur ? ' is-active' : '';
        return `<button type="button" class="mc-ops-btn${active}" data-brain="${escapeHtml(b.id)}" title="${escapeHtml(b.role || '')}">${escapeHtml(b.id)}</button>`;
      }).join('') || unavailable('no brains listed');
      $brainBtns.querySelectorAll('[data-brain]').forEach($b => {
        $b.onclick = () => switchBrain($b.getAttribute('data-brain'));
      });
      if (d.job && d.job.status) {
        const st = d.job.status;
        setStatus($brainStatus, statusClass(st), d.job.message || st);
        if (st === 'running' || st === 'starting') startBrainPoll();
      }
    }

    async function switchBrain(id) {
      if (!id) return;
      if (!confirm('Switch Spark brain to ' + id + '?\n\nThis reloads vLLM (minutes) and restarts the app briefly.')) return;
      $brainBtns.querySelectorAll('button').forEach(b => { b.disabled = true; });
      setStatus($brainStatus, 'run', 'Starting switch to ' + id + '…');
      setLog($brainLog, '');
      try {
        const j = await api('ops/brain', { method: 'POST', body: { brain: id } });
        setStatus($brainStatus, 'run', (j.job && j.job.message) || 'switching…');
        startBrainPoll();
      } catch (e) {
        setStatus($brainStatus, 'fail', e.message || String(e));
        $brainBtns.querySelectorAll('button').forEach(b => { b.disabled = false; });
      }
    }

    function startBrainPoll() {
      if (brainPoll) return;
      brainPoll = setInterval(async () => {
        try {
          const d = await api('ops/jobs/brain');
          setLog($brainLog, d.log_tail || '');
          const j = d.job;
          if (!j) return;
          const st = j.status;
          setStatus($brainStatus, statusClass(st), j.message || st);
          if (st === 'ok' || st === 'failed') {
            clearInterval(brainPoll); brainPoll = null;
            const fresh = await settled('ops/brain');
            if (fresh.ok) paintBrain(fresh.data);
            else $brainBtns.querySelectorAll('button').forEach(b => { b.disabled = false; });
          }
        } catch (_) { /* app may be restarting */ }
      }, 4000);
    }

    function paintTests(d) {
      if (!d) {
        $testStatus.textContent = 'ops tests unavailable';
        return;
      }
      $testBtns.innerHTML = (d.suites || []).map(s =>
        `<button type="button" class="mc-ops-btn" data-suite="${escapeHtml(s.id)}">${escapeHtml(s.label || s.id)}</button>`
      ).join('') || unavailable('no suites');
      $testBtns.querySelectorAll('[data-suite]').forEach($b => {
        $b.onclick = () => runTests($b.getAttribute('data-suite'));
      });
      if (d.job && d.job.status) {
        const st = d.job.status;
        setStatus($testStatus, statusClass(st), d.job.message || st);
        setLog($testLog, d.log_tail || d.job.summary || '');
        if (st === 'running' || st === 'starting') startTestPoll();
      }
    }

    async function runTests(suite) {
      $testBtns.querySelectorAll('button').forEach(b => { b.disabled = true; });
      setStatus($testStatus, 'run', 'Starting ' + suite + '…');
      setLog($testLog, '');
      try {
        const j = await api('ops/tests', { method: 'POST', body: { suite } });
        setStatus($testStatus, 'run', (j.job && j.job.message) || 'running…');
        startTestPoll();
      } catch (e) {
        setStatus($testStatus, 'fail', e.message || String(e));
        $testBtns.querySelectorAll('button').forEach(b => { b.disabled = false; });
      }
    }

    function startTestPoll() {
      if (testPoll) return;
      testPoll = setInterval(async () => {
        try {
          const d = await api('ops/jobs/tests');
          setLog($testLog, d.log_tail || '');
          const j = d.job;
          if (!j) return;
          const st = j.status;
          setStatus($testStatus, statusClass(st), j.message || st);
          if (st === 'ok' || st === 'failed') {
            clearInterval(testPoll); testPoll = null;
            $testBtns.querySelectorAll('button').forEach(b => { b.disabled = false; });
          }
        } catch (_) {}
      }, 2000);
    }

    if (brainR.ok) paintBrain(brainR.data);
    else $brainMeta.textContent = 'unavailable · ' + brainR.error;
    if (testsR.ok) paintTests(testsR.data);
    else setStatus($testStatus, 'fail', testsR.error);
  }

  async function panelPublicAgents($slot) {
    const r = await settled('system/public_agents');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const d = r.data || {};
    const agents = d.agents || [];
    if (!agents.length) return ($slot.innerHTML = `<p class="mc-unavailable">no public agents</p>`);

    const banner = (d.talking && d.talking.length)
      ? `<p class="mc-pa-banner hot">Talking today: ${escapeHtml(d.talking.join(', '))}</p>`
      : `<p class="mc-pa-banner">Quiet today (probes excluded)</p>`;

    const cards = agents.map(a => {
      const hot = (a.conversations_today || 0) > 0 || (a.turns_today || 0) > 0;
      const status = !a.reachable
        ? 'offline'
        : (a.model_ok === false
          ? 'model'
          : (hot ? 'talking' : (a.enabled === false ? 'paused' : 'quiet')));
      const tone = !a.reachable ? 'bad' : (hot ? 'hot' : null);
      const recent = (a.recent || []).slice(0, 2).map(x => `
        <div class="mc-pa-line">
          <span class="mc-pa-when">${escapeHtml(relTime(x.ts))}</span>
          ${escapeHtml(x.preview || '…')}${x.captured ? ' · lead' : ''}
        </div>`).join('') ||
        `<div class="mc-pa-line mc-muted">No recent visitor lines</div>`;
      return `
        <div class="mc-pa-card">
          <div class="mc-pa-head">
            <span class="mc-pa-name">${escapeHtml(a.name)}</span>
            <span class="mc-pa-status${tone ? ' tone-' + tone : ''}">
              <span class="mc-pa-dot ${status}"></span>${escapeHtml(status)}
            </span>
          </div>
          <div class="mc-pa-role">${escapeHtml(a.role || '')}</div>
          <div class="mc-pa-stats">
            <div><b>${a.conversations_today == null ? '—' : a.conversations_today}</b><span>today</span></div>
            <div><b>${a.turns_today == null ? '—' : a.turns_today}</b><span>turns</span></div>
            <div><b>${escapeHtml(relTime(a.last_activity))}</b><span>last</span></div>
          </div>
          ${recent}
          ${a.model ? `<div class="mc-pa-foot">${escapeHtml(a.model)}</div>` : ''}
        </div>`;
    }).join('');

    let crmHtml = '';
    const crm = d.crm;
    if (crm && crm.ok) {
      const lines = (crm.recent || []).slice(0, 5).map(L => {
        const bits = [L.name || '—'];
        if (L.phone) bits.push(L.phone);
        if (L.interest) bits.push(L.interest);
        return `
          <div class="mc-pa-line">
            <span class="mc-pa-when">${escapeHtml(relTime(L.created_at))}</span>
            ${escapeHtml(bits.join(' · '))}
            <span class="mc-muted"> · ${escapeHtml(L.status || 'new')}</span>
          </div>`;
      }).join('') || `<div class="mc-pa-line mc-muted">No leads in pipeline</div>`;
      crmHtml = `
        <div class="mc-crm">
          <div class="mc-pa-head" style="margin-top:10px">
            <span class="mc-pa-name" style="font-size:12px">PondWright CRM</span>
            <span class="mc-pa-status">${escapeHtml(String(crm.leads_new ?? '—'))} new</span>
          </div>
          <div class="mc-pa-stats">
            <div><b>${crm.leads_new == null ? '—' : crm.leads_new}</b><span>new</span></div>
            <div><b>${crm.leads_today == null ? '—' : crm.leads_today}</b><span>today</span></div>
            <div><b>${crm.leads_total == null ? '—' : crm.leads_total}</b><span>total</span></div>
          </div>
          ${lines}
        </div>`;
    } else if (crm && crm.error) {
      crmHtml = `<p class="mc-unavailable">CRM · ${escapeHtml(crm.error)}</p>`;
    }

    $slot.innerHTML = banner + `<div class="mc-pa-grid">${cards}</div>` + crmHtml;
  }

  async function panelCognition($slot) {
    const [noteR, reflR] = await Promise.all([
      settled('cognition/note'),
      settled('cognition/reflections'),
    ]);
    if (!noteR.ok && !reflR.ok) {
      return ($slot.innerHTML = unavailable(noteR.error || reflR.error));
    }

    let html = '';
    const note = noteR.ok && noteR.data && noteR.data.content;
    html += `<div class="mc-cog-label">Sense of us</div>`;
    if (note && String(note).trim()) {
      html += `<p class="mc-note">${escapeHtml(note)}</p>`;
    } else if (noteR.ok) {
      html += `<p class="mc-unavailable">no note yet — the cognition engine hasn't run</p>`;
    } else {
      html += unavailable(noteR.error);
    }

    html += `<div class="mc-cog-label">Reflections</div>`;
    if (!reflR.ok) {
      html += unavailable(reflR.error);
    } else {
      const list = Array.isArray(reflR.data)
        ? reflR.data
        : (reflR.data && reflR.data.reflections) || [];
      if (!list.length) {
        html += `<p class="mc-unavailable">no reflections yet.</p>`;
      } else {
        html += list.slice(0, 8).map(r => {
          const scope = r.scope || 'unsure';
          const jon = r.jon_originated
            ? `<span class="mc-jon-badge" title="originated from Jon">Jon</span>`
            : '';
          return `
            <div class="mc-cog-item">
              <div class="mc-cog-head">
                <span class="mc-cog-scope" data-scope="${escapeHtml(scope)}">${escapeHtml(scope)}</span>
                ${jon}
              </div>
              <div class="mc-cog-body">${escapeHtml(r.text || '')}</div>
            </div>`;
        }).join('');
      }
    }
    $slot.innerHTML = html;
  }

  async function panelRig($slot) {
    // /system/rig returns the same gpus[] as /system/gpu on this deployment,
    // plus `residents` — which process owns which card. That is the part the
    // GPU panel does not show, so this panel shows only that rather than
    // repeating numbers.
    const r = await settled('system/rig');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const d = r.data || {};
    if (d.residents_known === false) return ($slot.innerHTML = unavailable('residents unknown'));
    const rows = (d.gpus || []).flatMap(g => {
      const res = g.residents || [];
      const label = (g.name || `GPU ${g.index}`).replace(/^NVIDIA /, '');
      if (!res.length) return [statRow(label, 'idle')];
      return res.map(x => statRow(label, typeof x === 'string' ? x : (x.name || x.process || '?')));
    });
    $slot.innerHTML = rows.length ? rows.join('') : unavailable('no residents reported');
  }

  async function panelGpu($slot) {
    const r = await settled('system/gpu');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const d = r.data || {};
    if (d.available === false) return ($slot.innerHTML = unavailable(d.message || 'nvidia-smi unavailable'));
    const gpus = d.gpus || [];
    if (!gpus.length) return ($slot.innerHTML = unavailable('no gpus reported'));
    // Field names read off the live endpoint, not guessed: index, name,
    // mem_used_mib, mem_total_mib, temp_c, util_pct, residents.
    $slot.innerHTML = gpus.map(g => {
      const gb = v => (v == null ? null : Math.round(v / 1024));
      const used = gb(g.mem_used_mib), tot = gb(g.mem_total_mib);
      const bits = [];
      if (used != null && tot != null) bits.push(`${used}/${tot} GB`);
      if (g.util_pct != null) bits.push(`${Math.round(g.util_pct)}%`);
      if (g.temp_c != null) bits.push(`${g.temp_c}\u00B0C`);
      // 80C is where a runaway job has been caught before. Make it loud.
      const tone = g.temp_c != null && g.temp_c >= 80 ? 'hot' : null;
      const label = (g.name || `GPU ${g.index}`).replace(/^NVIDIA /, '');
      return statRow(label, bits.join('  \u00B7  '), tone);
    }).join('');
  }

  async function panelDaemons($slot) {
    const r = await settled('system/daemons');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const d = r.data || {};
    // Shape read off the live endpoint: a dict keyed by daemon name, NOT a
    // list. Each value carries some of {status, age_seconds, error, dry_run}.
    const names = Object.keys(d).filter(k => k !== 'fetched_at' && d[k] && typeof d[k] === 'object');
    if (!names.length) return ($slot.innerHTML = unavailable('none reported'));

    const mins = s => (s == null ? null : Math.round(s / 60));
    const rows = names.map(n => {
      const x = d[n] || {};
      const age = mins(x.age_seconds);
      let value, tone = null;
      if (x.error) { value = 'error'; tone = 'bad'; }
      else if (age != null) {
        value = age < 1 ? 'just now' : `${age}m ago`;
        // A heartbeat that has not ticked in over an hour is the signature of
        // the 26-hour silent outage: the daemon looks alive, the pipe is dead.
        if (age > 60) tone = 'bad';
      } else {
        value = x.status || 'unknown';
      }
      return { n, value, tone, bad: tone === 'bad' };
    });
    const bad = rows.filter(r => r.bad).length;
    const head = bad
      ? `<p class="mc-alert">${bad} stale or erroring</p>`
      : `<p class="mc-ok">${rows.length} reporting</p>`;
    $slot.innerHTML = head + rows.map(r => statRow(r.n, r.value, r.tone)).join('');
  }

  async function panelDelegation($slot) {
    const r = await settled('delegation/pending');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const list = Array.isArray(r.data) ? r.data : (r.data && r.data.tasks) || [];
    if (!list.length) return ($slot.innerHTML = `<p class="mc-ok">nothing in flight</p>`);
    $slot.innerHTML = list.slice(0, 8).map(t => `
      <div class="mc-item">
        <div class="mc-item-main">${escapeHtml(t.objective || t.title || t.id || '?')}</div>
        <div class="mc-item-meta">${escapeHtml(t.status || '')}</div>
      </div>`).join('');
  }

  async function panelHeartbeat($slot) {
    const r = await settled('heartbeat/recent');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const list = (r.data && r.data.pulses) || [];
    if (!list.length) return ($slot.innerHTML = unavailable('no pulses'));
    // Fields: note, completed_at, action_taken, error, dry_run, eligible.
    $slot.innerHTML = list.slice(0, 6).map(p => {
      const text = p.note || (p.error ? `error: ${p.error}` : '(silent pulse)');
      const marks = [];
      if (p.action_taken) marks.push('acted');
      if (p.dry_run) marks.push('dry run');
      if (p.error) marks.push('error');
      return `
      <div class="mc-item">
        <div class="mc-item-main${p.error ? ' tone-bad' : ''}">${escapeHtml(text)}</div>
        <div class="mc-item-meta">${escapeHtml(relativeTime(p.completed_at || ''))}${
          marks.length ? ' \u00B7 ' + escapeHtml(marks.join(' \u00B7 ')) : ''}</div>
      </div>`;
    }).join('');
  }

  // Order mirrors desktop Command Center priorities: ops first (actionable),
  // public talk + cognition (mind), then fleet/machine.
  const PANELS = [
    { id: 'ops',          title: 'Ops console',    render: panelOps, wide: true, hud: true },
    { id: 'public',       title: 'Public agents',  render: panelPublicAgents, wide: true },
    { id: 'cognition',    title: 'Cognition',      render: panelCognition, wide: true },
    { id: 'daemons',      title: 'Fleet',          render: panelDaemons },
    { id: 'gpu',          title: 'GPU',            render: panelGpu },
    { id: 'rig',          title: 'Rig',            render: panelRig },
    { id: 'delegation',   title: 'In flight',      render: panelDelegation },
    { id: 'heartbeat',    title: 'Recent pulses',  render: panelHeartbeat, wide: true },
  ];

  // ── views ──────────────────────────────────────────────────────────────────

  async function renderControlHome($view) {
    setHeader({ title: 'Mission Control' });
    clearOpsPolls();
    $view.innerHTML = `
      <div class="mc-build" data-mc-build="20260815-voice1">lab gold · ops · public · cognition</div>
      <div class="mc-grid">${
      PANELS.map(p => card(p.title, `<div id="mc-slot-${p.id}">${skeleton(2)}</div>`,
                           { wide: p.wide, hud: p.hud })).join('')
    }</div>`;
    // Fire all panels at once; each writes into its own slot as it lands, so the
    // screen fills progressively instead of waiting on the slowest endpoint.
    //
    // Query within $view, NOT document. renderTop() builds the view detached
    // and mounts it only after this renderer returns, so getElementById finds
    // nothing and every panel silently no-ops — which looks exactly like a
    // dashboard whose boxes are all empty.
    PANELS.forEach(p => {
      const $slot = $view.querySelector(`#mc-slot-${p.id}`);
      if (!$slot) { console.error('[control] slot missing', p.id); return; }
      p.render($slot).catch(e => { $slot.innerHTML = unavailable(String(e && e.message || e)); });
    });
  }

  // ── tab bar ────────────────────────────────────────────────────────────────

  let activeTab = 'control';

  function renderTabs() {
    let $bar = document.getElementById('mc-tabbar');
    if (!$bar) {
      $bar = document.createElement('nav');
      $bar.id = 'mc-tabbar';
      $bar.setAttribute('role', 'tablist');
      document.getElementById('app').appendChild($bar);
    }
    $bar.innerHTML = TABS.map(t => `
      <button class="mc-tab${t.id === activeTab ? ' is-active' : ''}"
              role="tab" aria-selected="${t.id === activeTab}" data-tab="${t.id}">
        <span class="mc-tab-glyph" aria-hidden="true">${t.glyph}</span>
        <span class="mc-tab-label">${escapeHtml(t.label)}</span>
      </button>`).join('');
    $bar.querySelectorAll('.mc-tab').forEach($b => {
      $b.onclick = () => selectTab($b.dataset.tab);
    });
  }

  async function selectTab(id) {
    if (id === activeTab) return;
    const tab = TABS.find(t => t.id === id);
    if (!tab) return;
    activeTab = id;
    if (id !== 'control') clearOpsPolls();
    renderTabs();
    // Each tab resets to its own root. Switching tabs is not "back", so the
    // stack is replaced rather than pushed — otherwise the back arrow walks
    // you into the other tab's history, which feels like a website.
    await reset({ kind: tab.view });
  }

  function showTabs(show) {
    const $bar = document.getElementById('mc-tabbar');
    if ($bar) $bar.style.display = show ? '' : 'none';
    document.body.classList.toggle('has-tabbar', !!show);
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

  function install() {
    if (typeof VIEW_RENDERERS === 'undefined') {
      console.error('[control] app.js not loaded first; tabs disabled');
      return;
    }
    VIEW_RENDERERS['control-home'] = renderControlHome;

    // The tab bar belongs to the paired app. While pairing, it would be a row
    // of buttons leading to 401s.
    window.__mcOnViewChange = (view) => {
      const paired = view && view.kind !== 'pairing';
      showTabs(paired);
      // Keep the tab highlight honest when boot or back-stack lands on a view.
      if (view && view.kind === 'control-home') activeTab = 'control';
      else if (view && (view.kind === 'thread-list' || view.kind === 'thread'
                        || view.kind === 'agent-pick' || view.kind === 'voice')) {
        activeTab = 'team';
      }
      if (paired) renderTabs();
      if (!paired || (view && view.kind !== 'control-home')) clearOpsPolls();
    };
    console.info('[control] Mission Control views registered');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }

  window.SOVERYN_CONTROL = { selectTab, renderTabs, showTabs, PANELS };
})();
