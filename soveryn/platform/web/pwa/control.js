// soveryn/platform/web/pwa/control.js
//
// Mission Control inside the app.
//
// Loaded after app.js and deliberately additive: it registers its own view
// renderers into VIEW_RENDERERS and adds a tab layer to the shell. The chat
// code is not modified — a working, paired, installed messenger is not worth
// risking to add a dashboard.
//
// Data comes from /m/api/* (device-bearer auth, read-only, see
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

  // ── data ───────────────────────────────────────────────────────────────────

  async function api(path) {
    const secret = await loadSecret();
    if (!secret) throw new Error('unpaired');
    const r = await fetch(`/m/api/${path}`, {
      headers: { Authorization: `Bearer ${secret}` },
    });
    if (r.status === 401) throw new Error('unpaired');
    if (!r.ok) throw new Error(`http ${r.status}`);
    return r.json();
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
      <section class="mc-card${opts.wide ? ' mc-card-wide' : ''}">
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

  // ── panels ─────────────────────────────────────────────────────────────────

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

  async function panelCognition($slot) {
    const r = await settled('cognition/note');
    if (!r.ok) return ($slot.innerHTML = unavailable(r.error));
    const d = r.data || {};
    const text = d.content;   // endpoint returns {content, id}
    if (!text) {
      // Was true from June until 2026-08-01. Keep the honest empty state.
      $slot.innerHTML = `<p class="mc-unavailable">no note yet — the cognition engine hasn't run</p>`;
      return;
    }
    $slot.innerHTML = `<p class="mc-note">${escapeHtml(text)}</p>`;
  }

  const PANELS = [
    { id: 'daemons',    title: 'Fleet',      render: panelDaemons },
    { id: 'gpu',        title: 'GPU',        render: panelGpu },
    { id: 'rig',        title: 'Rig',        render: panelRig },
    { id: 'delegation', title: 'In flight',  render: panelDelegation },
    { id: 'cognition',  title: 'Sense of us', render: panelCognition },
    { id: 'heartbeat',  title: 'Recent pulses', render: panelHeartbeat, wide: true },
  ];

  // ── views ──────────────────────────────────────────────────────────────────

  async function renderControlHome($view) {
    setHeader({ title: 'Mission Control' });
    $view.innerHTML = `<div class="mc-grid">${
      PANELS.map(p => card(p.title, `<div id="mc-slot-${p.id}">${skeleton(2)}</div>`,
                           { wide: p.wide })).join('')
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
      if (paired && !document.getElementById('mc-tabbar')) renderTabs();
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
