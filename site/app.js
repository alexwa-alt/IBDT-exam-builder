// DT practice-paper builder: login, filters, question cards, paper list and the specimen-style paper button.
'use strict';

// Unit names, once the department has them, e.g. {1: 'Design fundamentals', 4: 'Packaging'}.
const UNIT_NAMES = {};
const DIFFICULTY = { 1: 'Foundation', 2: 'Standard', 3: 'Challenging' };
const SOURCE_TYPES = { 'original': 'Original', 'past-paper case study': 'Past-paper case study' };
const STATUS = { draft: 'Draft', reviewed: 'Reviewed', published: 'Published', rejected: 'Rejected' };
const ORIGIN = { staff: 'Staff', ai: 'AI (Gemini)' };
// Paper formats the "specimen-style" button can build. Add HL Paper 2 here later.
const FORMATS = {
  'SL-2': { label: 'SL Paper 2', level: 'SL', paper: 2, slots: [{ marks: 6, count: 5 }, { marks: 10, count: 2 }] },
};
const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const MARK_WORDS = { 6: 'six-mark', 10: 'ten-mark' };
const PAPER_KEY = 'dt-paper-v1';

const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, '');
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid);
  return e;
};
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* not remembered */ } },
};

let bank = [], byId = new Map(), syllabus = null;
let paper = [];
const F = {   // current filters; each Set holds ticked options (empty = no restriction)
  text: '', taught: '', rows: new Set(), marks: new Set(), difficulty: new Set(), terms: new Set(),
  units: new Set(), source: new Set(), status: new Set(), statements: new Set(), origin: new Set(),
};
const GROUPS = {   // how each checkbox group reads a question (a question may have several values)
  rows: q => q.rows, marks: q => [q.marks], difficulty: q => [q.difficulty], terms: q => q.command_terms,
  units: q => q.units, source: q => [q.sourceType], status: q => [q.status], statements: q => q.statements,
  origin: q => [q.generated ? 'ai' : 'staff'],
};

// ------------------------------------------------------------------ login
async function start() {
  if (!Vault.supported) {
    showLogin('This browser cannot open the question bank. Use an up-to-date browser and the https:// address.');
    return;
  }
  try {
    if (await Vault.resume()) return enter();
    showLogin();
  } catch (e) {
    showLogin(e.message);
  }
}

function showLogin(message) {
  $('app').hidden = true;
  $('login').hidden = false;
  const msg = $('login-msg');
  msg.textContent = message || '';
  msg.className = 'msg bad';
  $('password').focus();
}

$('login-form').addEventListener('submit', async ev => {
  ev.preventDefault();
  const btn = $('login-btn'), msg = $('login-msg');
  btn.disabled = true; btn.textContent = 'Checking…'; msg.textContent = '';
  try {
    if (await Vault.unlock($('password').value, $('remember').checked)) {
      $('password').value = '';
      await enter();
    } else {
      msg.textContent = 'Incorrect password'; msg.className = 'msg bad';
      $('password').select();
    }
  } catch (e) {
    msg.textContent = e.message; msg.className = 'msg bad';
  } finally {
    btn.disabled = false; btn.textContent = 'Open';
  }
});

$('logout').addEventListener('click', ev => {
  ev.preventDefault();
  Vault.logout();
  location.reload();
});

async function enter() {
  const [questions, tags, syl] = await Promise.all(
    ['questions.json', 'tags.json', 'syllabus.json'].map(n => Vault.json(n)));
  syllabus = syl;
  bank = questions.filter(q => tags[q.id]).map(q => ({
    ...q, ...tags[q.id], sourceType: (q.source && q.source.type) || 'original',
  })).sort((a, b) => a.title.localeCompare(b.title));
  byId = new Map(bank.map(q => [q.id, q]));
  paper = (store.get(PAPER_KEY) || []).filter(id => byId.has(id));

  const built = Vault.built ? new Date(Vault.built).toLocaleDateString('en-GB',
    { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  const live = bank.filter(q => q.status !== 'rejected').length;
  $('bank-info').textContent = `${live} question${live === 1 ? '' : 's'} in the bank` +
    (built ? ` · updated ${built}` : '');
  buildFilters();
  $('login').hidden = true;
  $('app').hidden = false;
  refresh();
  renderPaper();
  if (typeof Staff !== 'undefined') await Staff.afterEnter();
}

// ------------------------------------------------------------------ filters
function matches(q, skip) {
  // Rejected questions stay hidden unless the Rejected box under Status is ticked.
  if (skip !== 'status' && q.status === 'rejected' && !F.status.has('rejected')) return false;
  if (F.text) {
    const hay = (q.title + ' ' + q.text).toLowerCase();
    if (!F.text.toLowerCase().split(/\s+/).filter(Boolean).every(w => hay.includes(w))) return false;
  }
  if (F.taught !== '' && q.taught_by != null && q.taught_by > Number(F.taught)) return false;
  for (const [g, read] of Object.entries(GROUPS)) {
    if (g === skip || !F[g].size) continue;
    if (!read(q).some(v => F[g].has(String(v)))) return false;
  }
  return true;
}

function checkbox(group, value, label, title) {
  const input = el('input', { type: 'checkbox', value: String(value) });
  input.addEventListener('change', () => {
    input.checked ? F[group].add(input.value) : F[group].delete(input.value);
    refresh();
  });
  const count = el('span', { class: 'count', 'data-group': group, 'data-value': String(value) });
  return el('label', { class: 'check', title: title || false }, input, el('span', {}, label, ' ', count));
}

function fillChecks(id, group, options) {
  const box = $(id);
  box.replaceChildren(...options.map(([v, label, title]) => checkbox(group, v, label, title)));
  box.closest('fieldset').hidden = options.length === 0;
}

const uniq = (list) => [...new Set(list)];
const present = read => uniq(bank.flatMap(read));

function buildFilters() {
  const sel = $('f-taught');
  sel.replaceChildren(el('option', { value: '', text: 'Any time (whole course)' }),
    ...syllabus.terms.map((t, i) => el('option', { value: String(i), text: 'By the end of ' + t })));
  sel.onchange = () => { F.taught = sel.value; refresh(); };
  $('f-text').oninput = e => { F.text = e.target.value.trim(); refresh(); };

  const rowNames = Object.values(syllabus.rows);
  fillChecks('f-rows', 'rows', rowNames.map(r => [r, r]));
  fillChecks('f-marks', 'marks', present(q => [q.marks]).sort((a, b) => a - b).map(m => [m, m + ' marks']));
  fillChecks('f-difficulty', 'difficulty', [1, 2, 3].map(d => [d, `${d} ${DIFFICULTY[d]}`]));
  const terms = present(q => q.command_terms).sort();
  const ctInfo = new Map(syllabus.command_terms.map(c => [c.term, c]));
  fillChecks('f-terms', 'terms', terms.map(t => [t, t, ctInfo.get(t) ? `${ctInfo.get(t).ao}: ${ctInfo.get(t).include}` : '']));
  fillChecks('f-units', 'units', present(q => q.units).sort((a, b) => a - b)
    .map(u => [u, UNIT_NAMES[u] ? `Unit ${u}: ${UNIT_NAMES[u]}` : `Unit ${u}`]));
  fillChecks('f-source', 'source', Object.entries(SOURCE_TYPES).filter(([k]) => bank.some(q => q.sourceType === k)));
  fillChecks('f-status', 'status', Object.entries(STATUS).filter(([k]) => bank.some(q => q.status === k)));
  fillChecks('f-origin', 'origin', bank.some(q => q.generated) ? Object.entries(ORIGIN) : []);
  buildTree();

  $('clear-filters').onclick = () => {
    for (const g of Object.keys(GROUPS)) F[g].clear();
    F.text = ''; F.taught = '';
    $('f-text').value = ''; sel.value = '';
    document.querySelectorAll('.filters input[type=checkbox]').forEach(c => { c.checked = false; c.indeterminate = false; });
    refresh();
  };
}

// Topic -> statement tree. Ticking a topic ticks all its statements.
function buildTree() {
  const used = new Set(bank.flatMap(q => q.statements));
  const byTopic = new Map();
  for (const s of syllabus.statements) {
    if (s.level !== 'SL' && !used.has(s.id)) continue;   // HL-only content isn't in SL questions
    if (!byTopic.has(s.topic)) byTopic.set(s.topic, []);
    byTopic.get(s.topic).push(s);
  }
  const tree = $('f-topics');
  tree.replaceChildren();
  for (const [topic, title] of Object.entries(syllabus.topics)) {
    const sts = byTopic.get(topic);
    if (!sts) continue;
    const topicBox = el('input', { type: 'checkbox' });
    const boxes = sts.map(s => {
      const label = checkbox('statements', s.id, s.id + ' ' + shorten(s.text, 60), s.text);
      if (!used.has(s.id)) label.classList.add('empty');
      return label;
    });
    const inputs = boxes.map(b => b.querySelector('input'));
    const sync = () => {
      const n = inputs.filter(i => i.checked).length;
      topicBox.checked = n === inputs.length; topicBox.indeterminate = n > 0 && n < inputs.length;
    };
    inputs.forEach(i => i.addEventListener('change', sync));
    topicBox.addEventListener('change', () => {
      inputs.forEach(i => { i.checked = topicBox.checked; topicBox.checked ? F.statements.add(i.value) : F.statements.delete(i.value); });
      topicBox.indeterminate = false;
      refresh();
    });
    topicBox.addEventListener('click', e => e.stopPropagation());   // ticking doesn't open/close the list
    const count = el('span', { class: 'count', 'data-topic': topic });
    const summary = el('summary', {}, el('label', { class: 'check', onclick: e => e.stopPropagation() },
      topicBox, el('span', {}, `${topic} ${title} `, count)));
    tree.append(el('details', { class: used.size && sts.some(s => used.has(s.id)) ? '' : 'empty' },
      summary, el('div', { class: 'statements' }, boxes)));
  }
}

const shorten = (t, n) => (t.length > n ? t.slice(0, n - 1).trimEnd() + '…' : t);

function updateCounts() {
  document.querySelectorAll('.filters .count[data-group]').forEach(c => {
    const g = c.dataset.group, v = c.dataset.value;
    const n = bank.filter(q => matches(q, g) && GROUPS[g](q).map(String).includes(v)).length;
    c.textContent = `(${n})`;
  });
  document.querySelectorAll('.filters .count[data-topic]').forEach(c => {
    const n = bank.filter(q => matches(q, 'statements') && q.topics.includes(c.dataset.topic)).length;
    c.textContent = `(${n})`;
  });
}

// ------------------------------------------------------------------ cards
let observer = null;

function refresh() {
  const shown = bank.filter(q => matches(q));
  updateCounts();
  const total = bank.filter(q => q.status !== 'rejected').length;
  $('result-count').textContent = shown.length === total
    ? `All ${total} questions`
    : `${shown.length} of ${total} questions match`;
  if (observer) observer.disconnect();
  observer = 'IntersectionObserver' in window ? new IntersectionObserver(loadPreviews, { rootMargin: '300px' }) : null;
  const cards = $('cards');
  if (!shown.length) {
    cards.replaceChildren(el('p', { class: 'empty-state', text: bank.length
      ? 'No questions match these filters. Try clearing some of them.'
      : 'The bank has no questions yet.' }));
    return;
  }
  cards.replaceChildren(...shown.map(card));
}

function card(q) {
  const inPaper = paper.includes(q.id);
  const img = el('img', { alt: `First page of ${q.title}`, 'data-src': q.pages[0] && q.pages[0].image, hidden: true });
  const preview = el('button', { class: 'preview', type: 'button', title: 'View the whole question',
    onclick: () => openViewer(q.id) }, el('span', { class: 'loading', text: 'Loading…' }), img);
  if (observer) observer.observe(preview); else showPreview(preview);
  const badge = q.status !== 'published'
    ? el('span', { class: 'badge ' + q.status, text: STATUS[q.status] || q.status }) : null;
  return el('article', { class: 'card' + (inPaper ? ' in-paper' : ''), 'data-id': q.id },
    preview,
    el('div', { class: 'card-body' },
      el('div', { class: 'card-title' }, el('h3', { text: q.title }), el('span', { class: 'marks', text: `[${q.marks}]` })),
      el('div', { class: 'meta' }, `${DIFFICULTY[q.difficulty] || ''} · ${q.rows.join(', ')}`,
        q.taught_by != null ? ` · taught by ${syllabus.terms[q.taught_by]}` : ''),
      el('div', { class: 'tags' }, badge, typeof Staff !== 'undefined' ? Staff.cardExtras(q) : null, q.sourceType !== 'original' ? el('span', { class: 'tag', text: 'Past-paper case study' }) : null,
        q.topics.map(t => el('span', { class: 'tag', title: syllabus.topics[t] || '', text: t }))),
      el('div', { class: 'card-actions' },
        el('button', { type: 'button', class: inPaper ? '' : 'primary', text: inPaper ? 'Remove from paper' : 'Add to paper',
          onclick: () => togglePaper(q.id) }))));
}

function loadPreviews(entries) {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    observer.unobserve(e.target);
    showPreview(e.target);
  }
}

async function showPreview(button) {
  const img = button.querySelector('img');
  if (!img.dataset.src) return;
  try {
    img.src = await Vault.imageURL(img.dataset.src);
    img.hidden = false;
    button.querySelector('.loading').remove();
  } catch (e) {
    button.querySelector('.loading').textContent = 'Preview unavailable';
  }
}

// ------------------------------------------------------------------ viewer
let viewing = null, viewingMs = false;

async function openViewer(id, showMs = false) {
  const q = byId.get(id);
  viewing = id; viewingMs = showMs;
  $('viewer-title').textContent = `${q.title} [${q.marks}]`;
  $('viewer-toggle').textContent = showMs ? 'Show question' : 'Show markscheme';
  $('viewer-toggle').disabled = !q.ms.length;
  updateViewerButton();
  if (typeof Staff !== 'undefined') Staff.updateViewer();
  const body = $('viewer-body');
  const pages = showMs ? q.ms : q.pages;
  body.replaceChildren(el('h3', { text: showMs ? 'Markscheme' : 'Question' }),
    ...pages.map(p => el('img', { alt: '', 'data-src': p.image })));
  if (!$('viewer').open) $('viewer').showModal();
  for (const img of body.querySelectorAll('img')) {
    try { img.src = await Vault.imageURL(img.dataset.src); } catch (e) { img.alt = 'Image unavailable'; }
  }
}
function updateViewerButton() {
  const inPaper = paper.includes(viewing);
  const b = $('viewer-add');
  b.textContent = inPaper ? 'Remove from paper' : 'Add to paper';
  b.className = inPaper ? '' : 'primary';
}
$('viewer-toggle').onclick = () => openViewer(viewing, !viewingMs);
$('viewer-add').onclick = () => { togglePaper(viewing); updateViewerButton(); };
$('viewer-close').onclick = () => $('viewer').close();
$('viewer').addEventListener('click', e => { if (e.target === $('viewer')) $('viewer').close(); });

// ------------------------------------------------------------------ paper list
function savePaper() { store.set(PAPER_KEY, paper); }

function togglePaper(id) {
  paper = paper.includes(id) ? paper.filter(x => x !== id) : paper.concat(id);
  setMsg('paper-msg', '');
  savePaper(); renderPaper(); syncCards();
}

function syncCards() {
  document.querySelectorAll('.card').forEach(c => {
    const inPaper = paper.includes(c.dataset.id);
    c.classList.toggle('in-paper', inPaper);
    const b = c.querySelector('.card-actions button');
    b.textContent = inPaper ? 'Remove from paper' : 'Add to paper';
    b.className = inPaper ? '' : 'primary';
  });
}

function move(i, d) {
  const j = i + d;
  if (j < 0 || j >= paper.length) return;
  [paper[i], paper[j]] = [paper[j], paper[i]];
  savePaper(); renderPaper();
}

function renderPaper() {
  const list = $('paper-list');
  if (!paper.length) {
    list.replaceChildren(el('li', { class: 'empty', text: 'No questions yet. Add questions from the list, or build a specimen-style paper.' }));
  } else {
    list.replaceChildren(...paper.map((id, i) => {
      const q = byId.get(id);
      return el('li', {},
        el('span', { class: 'num', text: `${i + 1}.` }),
        el('span', {}, el('a', { href: '#', onclick: e => { e.preventDefault(); openViewer(id); }, text: q.title }), ` [${q.marks}]`),
        el('span', { class: 'small-btns' },
          el('button', { type: 'button', title: 'Move up', 'aria-label': `Move ${q.title} up`, disabled: i === 0, onclick: () => move(i, -1), text: '↑' }),
          el('button', { type: 'button', title: 'Move down', 'aria-label': `Move ${q.title} down`, disabled: i === paper.length - 1, onclick: () => move(i, 1), text: '↓' }),
          el('button', { type: 'button', title: 'Remove', 'aria-label': `Remove ${q.title}`, onclick: () => togglePaper(id), text: '✕' })));
    }));
  }
  const marks = paper.reduce((s, id) => s + byId.get(id).marks, 0);
  $('paper-total').textContent = paper.length
    ? `${paper.length} question${paper.length === 1 ? '' : 's'} · ${marks} marks · ${DTPaper.duration(marks)}`
    : '';
  $('download').disabled = $('download-word').disabled = !paper.length;
}

function setMsg(id, text, kind, action) {
  const m = $(id);
  m.replaceChildren(text);
  m.className = 'msg' + (kind ? ' ' + kind : '');
  if (action) m.append(' ', el('button', { type: 'button', class: 'link', text: action.label, onclick: action.run }));
}

$('clear-paper').onclick = () => {
  if (!paper.length) return;
  const before = paper;
  paper = []; savePaper(); renderPaper(); syncCards();
  setMsg('paper-msg', 'Paper cleared.', '', { label: 'Undo', run: () => restore(before) });
};

function restore(list) {
  paper = list.filter(id => byId.has(id)); savePaper(); renderPaper(); syncCards(); setMsg('paper-msg', '');
}

// ------------------------------------------------------------------ specimen-style paper
const count = (n, word) => `${n <= 10 ? NUMBER_WORDS[n] : n} ${word} question${n === 1 ? '' : 's'}`;

function shuffle(a) {
  a = a.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

// Choose questions for each slot from the pool, keeping topic overlap low. Returns {ids} or {missing}.
function chooseSpecimen(pool, format) {
  const missing = [];
  for (const s of format.slots) {
    const n = pool.filter(q => q.marks === s.marks).length;
    if (n < s.count) {
      const word = MARK_WORDS[s.marks] || `${s.marks}-mark`;
      missing.push(`${n ? 'only ' : ''}${count(n, word)} match${n === 1 ? 'es' : ''} these filters (${s.count} needed)`);
    }
  }
  if (missing.length) return { missing };

  // Try many random orders; keep every distinct paper. Then pick at random among the papers whose topic
  // overlap is at most one more than the best, so repeated presses give different (but still varied) papers.
  const papers = new Map();
  for (let attempt = 0; attempt < 400; attempt++) {
    const chosen = [], topics = new Map();
    let overlap = 0;
    for (const s of shuffle(format.slots)) {      // random slot order, so every combination can be reached
      const options = shuffle(pool.filter(q => q.marks === s.marks));
      for (let k = 0; k < s.count; k++) {
        let pick = null, pickScore = Infinity;
        for (const q of options) {
          if (chosen.includes(q)) continue;
          const score = q.topics.reduce((t, x) => t + (topics.get(x) || 0), 0);
          if (score < pickScore) { pick = q; pickScore = score; }
        }
        chosen.push(pick); overlap += pickScore;
        pick.topics.forEach(x => topics.set(x, (topics.get(x) || 0) + 1));
      }
    }
    const key = chosen.map(q => q.id).sort().join(' ');
    if (!papers.has(key) || papers.get(key).overlap > overlap) papers.set(key, { chosen, overlap });
  }
  const all = [...papers.values()];
  const lowest = Math.min(...all.map(p => p.overlap));
  const good = all.filter(p => p.overlap <= lowest + 1);
  const pick = good[Math.floor(Math.random() * good.length)];
  const slotOrder = q => format.slots.findIndex(s => s.marks === q.marks);   // 6-mark questions first
  const ordered = pick.chosen.slice().sort((a, b) => slotOrder(a) - slotOrder(b));
  return { ids: ordered.map(q => q.id), overlap: pick.overlap };
}

$('specimen').onclick = () => {
  const format = FORMATS['SL-2'];
  const pool = bank.filter(q => matches(q) && q.level === format.level && q.paper === format.paper);
  const result = chooseSpecimen(pool, format);
  if (result.missing) {
    const text = result.missing.join('; ');
    setMsg('paper-msg', `Can't build a full ${format.label}: ${text}. Try widening the filters.`, 'bad');
    return;
  }
  const before = paper;
  paper = result.ids; savePaper(); renderPaper(); syncCards();
  const total = paper.reduce((s, id) => s + byId.get(id).marks, 0);
  const note = result.overlap ? ' Some topics appear twice: the filtered bank is too small to avoid it.' : '';
  setMsg('paper-msg', `Built a ${total}-mark ${format.label}.${note}`, 'good',
    before.length ? { label: 'Undo', run: () => restore(before) } : null);
};

// ------------------------------------------------------------------ downloads (PDF and Word)
const FORMATS_OUT = {
  pdf: { button: 'download', label: 'PDF', make: async opts => (await DTPaper.build(opts)).output('blob'),
         name: DTPaper.fileName },
  docx: { button: 'download-word', label: 'Word document', make: opts => DTWord.build(opts), name: DTWord.fileName },
};

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

async function download(kind) {
  const f = FORMATS_OUT[kind];
  const buttons = Object.values(FORMATS_OUT).map(x => $(x.button));
  buttons.forEach(b => { b.disabled = true; });
  setMsg('pdf-msg', `Preparing the ${f.label}…`);
  try {
    const qs = paper.map(id => byId.get(id));
    const opts = { questions: qs, level: qs[0].level, paper: qs[0].paper, markscheme: $('include-ms').checked,
      loadImage: n => Vault.bytes(n),
      onProgress: (d, t) => setMsg('pdf-msg', `Preparing the ${f.label}… (${d} of ${t} images)`) };
    const blob = await f.make(opts);
    const marks = qs.reduce((s, q) => s + q.marks, 0);
    saveBlob(blob, f.name(opts, marks));
    setMsg('pdf-msg', `${f.label[0].toUpperCase() + f.label.slice(1)} downloaded.`, 'good');
  } catch (e) {
    console.error(e);
    setMsg('pdf-msg', `Sorry, the ${f.label} could not be made: ${e.message}`, 'bad');
  } finally {
    buttons.forEach(b => { b.disabled = !paper.length; });
  }
}
$('download').onclick = () => download('pdf');
$('download-word').onclick = () => download('docx');

start();
