// Staff tools: generate new questions with Gemini and review drafts, without opening the Drive folder.
// Both start a GitHub Actions workflow (generate.yml / review.yml) through GitHub's "run workflow" API, using
// a limited token stored encrypted in the site (dispatch.json). Each request is itself encrypted with the
// bank key (Vault.seal), because workflow inputs are visible on this public repository's Actions page.
// Uses app.js globals: $, el, store, bank, byId, refresh, openViewer, viewing.
'use strict';

const Staff = (() => {
  const PENDING_KEY = 'dt-reviews-pending-v1';   // decisions not yet sent
  const SENT_KEY = 'dt-reviews-sent-v1';         // decisions sent, waiting for the site to rebuild
  const NAME_KEY = 'dt-reviewer-name';
  const LABEL = { reviewed: 'Approve', published: 'Publish', rejected: 'Reject', draft: 'Back to draft' };
  let cfg = null;
  let pending = {};     // id -> {status, reason}
  let sent = {};        // id -> {status, at}

  const enabled = () => !!cfg;

  // ---------------------------------------------------------------- GitHub
  async function dispatch(workflow, payload) {
    const request = await Vault.seal({ ...payload, sent: Date.now() });
    const r = await fetch(`https://api.github.com/repos/${cfg.repo}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${cfg.token}`, Accept: 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28' },
      body: JSON.stringify({ ref: cfg.ref || 'main', inputs: { request } }),
    });
    if (r.status === 401 || r.status === 403) throw new Error('GitHub refused the request: the site\'s token may have expired. Ask the site administrator to renew GEN_DISPATCH_TOKEN.');
    if (!r.ok) throw new Error(`GitHub could not start the job (error ${r.status}).`);
  }

  // Follow the newest run of a workflow started after `since`, calling show(text, kind, url) as it changes.
  function watch(workflow, since, show, doneText) {
    const stop = Date.now() + 40 * 60 * 1000;
    const tick = async () => {
      try {
        const r = await fetch(`https://api.github.com/repos/${cfg.repo}/actions/workflows/${workflow}/runs?event=workflow_dispatch&per_page=5`,
          { headers: { Authorization: `Bearer ${cfg.token}`, Accept: 'application/vnd.github+json' } });
        const runs = r.ok ? (await r.json()).workflow_runs : [];
        const run = runs.find(x => new Date(x.created_at).getTime() >= since - 60000);
        if (run && run.status === 'completed') {
          if (run.conclusion === 'success') show(doneText, 'good', run.html_url);
          else show(`The job finished with a problem (${run.conclusion}).`, 'bad', run.html_url);
          return;
        }
        if (run) show(run.status === 'queued' ? 'Waiting to start…' : 'Working… (this page can be closed)', '', run.html_url);
      } catch (e) { /* network blip: try again */ }
      if (Date.now() < stop) setTimeout(tick, 15000);
    };
    setTimeout(tick, 5000);
  }

  function status(id, text, kind, url) {
    const m = $(id);
    m.replaceChildren(text);
    m.className = 'msg' + (kind ? ' ' + kind : '');
    if (url) m.append(' ', el('a', { href: url, target: '_blank', rel: 'noopener', text: 'Details' }));
  }

  // ---------------------------------------------------------------- reviews
  function save() { store.set(PENDING_KEY, pending); store.set(SENT_KEY, sent); }

  function decide(id, decision, reason) {
    const q = byId.get(id);
    if (!q) return;
    if (decision === q.status && !pending[id]) return;
    if (decision === q.status) delete pending[id];
    else pending[id] = { status: decision, reason: reason || '' };
    save(); renderTray(); refresh(); updateViewer();
  }

  function renderTray() {
    const ids = Object.keys(pending).filter(id => byId.has(id));
    $('review-tray').hidden = !ids.length;
    $('review-list').replaceChildren(...ids.map(id => el('li', {},
      el('span', {}, el('a', { href: '#', text: byId.get(id).title,
        onclick: e => { e.preventDefault(); openViewer(id); } }), ` → ${LABEL[pending[id].status]}`,
        pending[id].reason ? el('span', { class: 'muted small', text: ` (“${pending[id].reason}”)` }) : null),
      el('span', { class: 'small-btns' }, el('button', { type: 'button', text: '✕', title: 'Undo',
        'aria-label': `Undo the decision for ${byId.get(id).title}`, onclick: () => { delete pending[id]; save(); renderTray(); refresh(); updateViewer(); } })))));
    $('review-count').textContent = ids.length ? `(${ids.length})` : '';
  }

  async function sendReviews() {
    const name = $('reviewer-name').value.trim();
    if (!name) { status('review-msg', 'Type your name first, so the bank records who reviewed.', 'bad'); $('reviewer-name').focus(); return; }
    store.set(NAME_KEY, name);
    const items = Object.entries(pending).filter(([id]) => byId.has(id))
      .map(([id, d]) => ({ id, status: d.status, reason: d.reason }));
    if (!items.length) return;
    const btn = $('send-reviews');
    btn.disabled = true;
    status('review-msg', 'Sending…');
    const since = Date.now();
    try {
      await dispatch('review.yml', { kind: 'review', by: name, items });
      for (const it of items) sent[it.id] = { status: it.status, at: since };
      pending = {}; save(); renderTray(); refresh();
      $('review-tray').hidden = false;
      status('review-msg', 'Sent. Saving to the bank…');
      watch('review.yml', since, (t, k, u) => status('review-msg', t, k, u),
        'Saved. The site is rebuilding: reload in about 5 minutes to see the changes.');
    } catch (e) {
      status('review-msg', e.message, 'bad');
    } finally { btn.disabled = false; }
  }

  // Badges on a card: "AI draft", and a decision waiting to be sent or saved.
  function cardExtras(q) {
    const out = [];
    if (q.generated) out.push(el('span', { class: 'tag ai', title: 'Written by Gemini; check before use', text: 'AI-written' }));
    if (pending[q.id]) out.push(el('span', { class: 'tag pending', text: `To send: ${LABEL[pending[q.id].status]}` }));
    else if (sent[q.id]) out.push(el('span', { class: 'tag pending', text: `Saving: ${LABEL[sent[q.id].status]}` }));
    return out;
  }

  // Review buttons in the question viewer.
  function updateViewer() {
    const box = $('viewer-review');
    if (!box) return;
    const q = byId.get(viewing);
    box.hidden = !enabled() || !q;
    $('reject-row').hidden = true;
    if (!q) return;
    const current = (pending[q.id] && pending[q.id].status) || q.status;
    const btn = (decision, cls) => el('button', { type: 'button', class: (current === decision ? 'chosen ' : '') + (cls || ''),
      text: LABEL[decision], 'aria-pressed': String(current === decision),
      onclick: () => {
        if (decision === 'rejected') { $('reject-row').hidden = false; $('reject-reason').focus(); return; }
        decide(q.id, decision);
      } });
    const review = q.review ? el('span', { class: 'muted small',
      text: `Last review: ${q.review.status} by ${q.review.by}, ${q.review.date}` }) : null;
    box.replaceChildren(...[el('span', { class: 'small', text: 'Review: ' }),
      q.status !== 'draft' ? btn('draft') : null,
      q.status !== 'reviewed' ? btn('reviewed') : null,
      q.status !== 'published' ? btn('published') : null,
      q.status !== 'rejected' ? btn('rejected', 'danger') : null, review].filter(Boolean));
  }

  // ---------------------------------------------------------------- generate
  async function generate(ev) {
    ev.preventDefault();
    const f = ev.target;
    const name = f.elements['gen-name'].value.trim();
    if (name) store.set(NAME_KEY, name);
    const payload = {
      kind: 'generate', by: name || 'staff', count: Number(f.elements['gen-count'].value) || 1,
      marks: f.elements['gen-marks'].value || null, difficulty: f.elements['gen-difficulty'].value || null,
      statements: f.elements['gen-statements'].value.trim() || null,
      case_study: f.elements['gen-case'].value.trim() || null,
    };
    const btn = $('gen-submit');
    btn.disabled = true;
    status('gen-msg', 'Starting…');
    const since = Date.now();
    try {
      await dispatch('generate.yml', payload);
      status('gen-msg', 'Started. Gemini usually takes 2–5 minutes per question.');
      watch('generate.yml', since, (t, k, u) => status('gen-msg', t, k, u),
        'Finished. New drafts appear after the site rebuilds (about 5 minutes): reload then, and tick "Draft" under Status.');
    } catch (e) {
      status('gen-msg', e.message, 'bad');
    } finally { btn.disabled = false; }
  }

  // ---------------------------------------------------------------- start
  async function afterEnter() {
    pending = store.get(PENDING_KEY) || {};
    sent = store.get(SENT_KEY) || {};
    const day = 24 * 3600 * 1000;
    for (const [id, s] of Object.entries(sent)) {         // forget decisions the bank now shows, or old ones
      const q = byId.get(id);
      if (!q || q.status === s.status || Date.now() - s.at > day) delete sent[id];
    }
    save();
    try {
      cfg = Vault.has('dispatch.json') ? await Vault.json('dispatch.json') : null;
      if (cfg && !(cfg.token && cfg.repo)) cfg = null;
    } catch (e) { cfg = null; }
    $('open-generate').hidden = !enabled();
    $('reviewer-name').value = store.get(NAME_KEY) || '';
    $('gen-name').value = store.get(NAME_KEY) || '';
    renderTray();
    if (Object.keys(pending).length || Object.keys(sent).length) refresh();
  }

  $('send-reviews').onclick = sendReviews;
  $('open-generate').onclick = () => {
    if (!$('gen-name').value) $('gen-name').value = store.get(NAME_KEY) || '';
    $('gen-dialog').showModal();
  };
  $('gen-close').onclick = () => $('gen-dialog').close();
  $('gen-form').addEventListener('submit', generate);
  $('reject-confirm').onclick = () => {
    const reason = $('reject-reason').value.trim();
    if (!reason) { $('reject-reason').focus(); return; }
    decide(viewing, 'rejected', reason);
    $('reject-reason').value = '';
  };

  return { afterEnter, cardExtras, updateViewer, get enabled() { return enabled(); } };
})();
