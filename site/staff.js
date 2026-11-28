// Staff tools: generate new questions with Gemini and review drafts, without opening the Drive folder.
// Both start a GitHub Actions workflow (generate.yml / review.yml) through GitHub's "run workflow" API, using
// a limited token stored encrypted in the site (dispatch.json). Each request is itself encrypted with the
// bank key (Vault.seal), because workflow inputs are visible on this public repository's Actions page.
// The Generate dialog can also send a product photo: it is shrunk to fit GitHub's limit on workflow inputs
// (65,535 characters for all of them together), encrypted, and sent as a second input beside the request.
// Uses app.js globals: $, el, store, bank, byId, syllabus, refresh, openViewer, viewing, shorten.
'use strict';

const Staff = (() => {
  const PENDING_KEY = 'dt-reviews-pending-v1';   // decisions not yet sent
  const SENT_KEY = 'dt-reviews-sent-v1';         // decisions sent, waiting for the site to rebuild
  const NAME_KEY = 'dt-reviewer-name';
  const LABEL = { reviewed: 'Approve', published: 'Publish', rejected: 'Reject', draft: 'Back to draft' };
  const INPUT_LIMIT = 65000;          // GitHub: 65,535 characters across all of a run's inputs
  const PHOTO_MAX_BYTES = 45000;      // JPEG size that, encrypted and in base64, leaves room for the request
  const MAX_TERMS = 3, MAX_STATEMENTS = 4;       // match scripts/generator/coverage.py
  const BANNED_TERMS = ['Discuss', 'Determine']; // never used in generated questions (extra_checks.py)
  const SL_TOPICS = ['A1.1', 'A2.1', 'A2.2', 'A3.1', 'B1.1', 'B2.1', 'B2.2', 'B3.1', 'C1.1', 'C1.2', 'C2.1', 'C2.2', 'C3.1'];
  let photo = null;     // {blob, w, h} after shrinking
  let cfg = null;
  let pending = {};     // id -> {status, reason}
  let sent = {};        // id -> {status, at}

  const enabled = () => !!cfg;

  // ---------------------------------------------------------------- GitHub
  // extra: more workflow inputs (already encrypted), e.g. {photo}.
  async function dispatch(workflow, payload, extra = {}) {
    const request = await Vault.seal({ ...payload, sent: Date.now() });
    const inputs = { request, ...extra };
    if (Object.values(inputs).reduce((n, v) => n + v.length, 0) > INPUT_LIMIT)
      throw new Error('The request is too large for GitHub. Try a smaller or simpler photo.');
    const r = await fetch(`https://api.github.com/repos/${cfg.repo}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${cfg.token}`, Accept: 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28' },
      body: JSON.stringify({ ref: cfg.ref || 'main', inputs }),
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
  const mode = () => $('gen-form').elements['gen-mode'].value;

  function showMode() {
    const isPhoto = mode() === 'photo';
    $('gen-photo-box').hidden = !isPhoto;
    $('gen-case-field').hidden = isPhoto;
  }

  // Checkboxes for command terms and syllabus statements, with how often the bank already uses each.
  function limit(box, max, countEl, text) {
    const boxes = [...box.querySelectorAll('input[type=checkbox]')];
    const n = boxes.filter(b => b.checked).length;
    boxes.forEach(b => { b.disabled = !b.checked && n >= max; });
    countEl.textContent = n ? `(${n} of ${max} chosen)` : text;
  }

  function buildPickers() {
    const live = bank.filter(q => q.status !== 'rejected');
    const termUse = new Map(), stUse = new Map();
    for (const q of live) {
      for (const t of q.command_terms || []) termUse.set(t, (termUse.get(t) || 0) + 1);
      for (const st of q.statements || []) stUse.set(st, (stUse.get(st) || 0) + 1);
    }
    const termsText = $('gen-terms-count').textContent, stText = $('gen-statements-count').textContent;
    const terms = (syllabus.command_terms || []).filter(c => !BANNED_TERMS.includes(c.term))
      .sort((a, b) => a.term.localeCompare(b.term));
    $('gen-terms').replaceChildren(...terms.map(c => el('label', { class: 'check',
      title: [c.ao, c.include].filter(Boolean).join(': ') + (c.marks && c.marks.length ? ` (usually ${c.marks.join(' or ')} marks)` : '') },
      el('input', { type: 'checkbox', name: 'gen-term', value: c.term,
        onchange: () => limit($('gen-terms'), MAX_TERMS, $('gen-terms-count'), termsText) }),
      `${c.term} `, el('span', { class: 'muted', text: `(${termUse.get(c.term) || 0})` }))));

    const groups = [];
    for (const topic of SL_TOPICS) {
      const sts = syllabus.statements.filter(x => x.topic === topic && x.level === 'SL');
      if (!sts.length) continue;
      const used = sts.reduce((n, x) => n + (stUse.get(x.id) || 0), 0);
      groups.push(el('details', { 'data-topic': topic },
        el('summary', { text: `${topic} ${(syllabus.topics || {})[topic] || ''} (${used})` }),
        ...sts.map(x => el('label', { class: 'check', title: x.text, 'data-search': `${x.id} ${x.text}`.toLowerCase() },
          el('input', { type: 'checkbox', name: 'gen-statement', value: x.id,
            onchange: () => limit($('gen-statements'), MAX_STATEMENTS, $('gen-statements-count'), stText) }),
          el('span', {}, el('b', { text: x.id }), ` ${shorten(x.text, 90)} `,
            el('span', { class: 'muted', text: `(${stUse.get(x.id) || 0})` }))))));
    }
    $('gen-statements').replaceChildren(...groups);
    $('gen-statement-search').oninput = e => {
      const words = e.target.value.toLowerCase().split(/\s+/).filter(Boolean);
      for (const d of $('gen-statements').querySelectorAll('details')) {
        let any = false;
        for (const l of d.querySelectorAll('label')) {
          const hit = words.every(w => l.dataset.search.includes(w));
          l.hidden = !hit; any = any || hit;
        }
        d.hidden = !any;
        d.open = words.length > 0 && any;
      }
    };
  }

  // Shrink a photo to a JPEG of at most PHOTO_MAX_BYTES, as large as possible.
  async function decode(file) {
    try { return await createImageBitmap(file, { imageOrientation: 'from-image' }); } catch (e) { /* try <img> */ }
    const url = URL.createObjectURL(file);
    try {
      return await new Promise((ok, fail) => {
        const im = new Image();
        im.onload = () => ok(im);
        im.onerror = () => fail(new Error('This browser cannot open that file. Use a JPEG or PNG photo (iPhone HEIC photos open only in Safari).'));
        im.src = url;
      });
    } finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
  }

  async function shrink(file) {
    const src = await decode(file);
    const w0 = src.width, h0 = src.height;
    if (!w0 || !h0) throw new Error('That file is not a picture.');
    const canvas = document.createElement('canvas');
    for (const side of [1024, 900, 800, 700, 600, 500, 400]) {
      const s = Math.min(1, side / Math.max(w0, h0));
      canvas.width = Math.round(w0 * s); canvas.height = Math.round(h0 * s);
      const g = canvas.getContext('2d');
      g.fillStyle = '#fff'; g.fillRect(0, 0, canvas.width, canvas.height);   // transparent PNGs -> white
      g.drawImage(src, 0, 0, canvas.width, canvas.height);
      for (const quality of [0.85, 0.75, 0.65]) {
        const blob = await new Promise(ok => canvas.toBlob(ok, 'image/jpeg', quality));
        if (blob && blob.size <= PHOTO_MAX_BYTES) return { blob, w: canvas.width, h: canvas.height };
      }
    }
    throw new Error('This photo has too much detail to send, even when shrunk. Try cropping it to the product.');
  }

  async function choosePhoto() {
    const file = $('gen-photo').files[0];
    photo = null;
    $('gen-preview').hidden = true;
    status('gen-msg', '');
    if (!file) return;
    status('gen-msg', 'Preparing the photo…');
    try {
      photo = await shrink(file);
      const old = $('gen-preview-img').src;
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
      $('gen-preview-img').src = URL.createObjectURL(photo.blob);
      $('gen-photo-info').textContent = `Will be sent as ${photo.w} × ${photo.h} pixels (${Math.round(photo.blob.size / 1024)} KB).`;
      $('gen-preview').hidden = false;
      status('gen-msg', '');
    } catch (e) {
      $('gen-photo').value = '';
      status('gen-msg', e.message, 'bad');
    }
  }

  async function sha256Hex(bytes) {
    const d = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    return [...d].map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function generate(ev) {
    ev.preventDefault();
    const f = ev.target;
    const name = f.elements['gen-name'].value.trim();
    if (name) store.set(NAME_KEY, name);
    const ticked = n => [...f.querySelectorAll(`input[name=${n}]:checked`)].map(i => i.value);
    const isPhoto = mode() === 'photo';
    if (isPhoto && !photo) {
      status('gen-msg', 'Choose a photo of the product first.', 'bad');
      $('gen-photo').focus();
      return;
    }
    const payload = {
      kind: 'generate', by: name || 'staff', count: Number(f.elements['gen-count'].value) || 1,
      marks: f.elements['gen-marks'].value || null, difficulty: f.elements['gen-difficulty'].value || null,
      statements: ticked('gen-statement').join(',') || null,
      command_terms: ticked('gen-term').join(',') || null,
      case_study: isPhoto ? null : (f.elements['gen-case'].value.trim() || null),
    };
    const btn = $('gen-submit');
    btn.disabled = true;
    status('gen-msg', 'Starting…');
    const since = Date.now();
    try {
      const extra = {};
      if (isPhoto) {
        const bytes = new Uint8Array(await photo.blob.arrayBuffer());
        payload.photo = { sha256: await sha256Hex(bytes), note: f.elements['gen-note'].value.trim() || null,
                          credit: f.elements['gen-credit'].value.trim() || null };
        extra.photo = await Vault.sealBytes(bytes);
      }
      await dispatch('generate.yml', payload, extra);
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
    if (enabled()) buildPickers();
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
  $('gen-form').querySelectorAll('input[name=gen-mode]').forEach(r => r.addEventListener('change', showMode));
  $('gen-photo').addEventListener('change', choosePhoto);
  $('reject-confirm').onclick = () => {
    const reason = $('reject-reason').value.trim();
    if (!reason) { $('reject-reason').focus(); return; }
    decide(viewing, 'rejected', reason);
    $('reject-reason').value = '';
  };

  return { afterEnter, cardExtras, updateViewer, get enabled() { return enabled(); } };
})();
