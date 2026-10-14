/* QA Engineer front end: Board, Run, History and Integrations. Plain JS, no build step.
   State lives in S; render() redraws the screen; clicks, inputs and changes are delegated by data-act / data-in. */
'use strict';

const $app = document.getElementById('app');
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem('qa.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('qa.' + k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } },
};

/* ------------------------------------------------------------------ icons */
const svg = (d, cls = 'ic', extra = '') => `<svg class="${cls}" ${extra} viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const IC = {
  board: '<rect x="3.5" y="4" width="5" height="16" rx="1.2"></rect><rect x="9.5" y="4" width="5" height="10" rx="1.2"></rect><rect x="15.5" y="4" width="5" height="13" rx="1.2"></rect>',
  run: '<circle cx="12" cy="12" r="9"></circle><path d="M10 8.5v7l5.5-3.5z"></path>',
  history: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"></path><path d="M3.5 3.5v5h5"></path><path d="M12 7.5V12l3 2"></path>',
  integ: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"></rect><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"></rect><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"></rect><path d="M17 14v6M14 17h6"></path>',
  sun: '<circle cx="12" cy="12" r="4"></circle><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4"></path>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"></path>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"></rect><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"></path>',
  sync: '<path d="M20 11a8 8 0 0 0-14.7-4.3L3.5 9M4 13a8 8 0 0 0 14.7 4.3l1.8-2.3"></path><path d="M3.5 4v5h5M20.5 20v-5h-5"></path>',
  search: '<circle cx="11" cy="11" r="6.5"></circle><path d="M20 20l-4.2-4.2"></path>',
  spin: '<path d="M12 3a9 9 0 1 0 9 9"></path>',
  person: '<circle cx="12" cy="8" r="3.5"></circle><path d="M5 20a7 7 0 0 1 14 0"></path>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"></path>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"></path>',
  close: '<path d="M6 6l12 12M18 6L6 18"></path>',
  warn: '<path d="M12 4l9 16H3z"></path><path d="M12 10v4M12 17v.01"></path>',
  info: '<circle cx="12" cy="12" r="9"></circle><path d="M12 11v5M12 8v.01"></path>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"></path>',
  dotc: '<circle cx="12" cy="12" r="3"></circle>',
  err: '<circle cx="12" cy="12" r="9"></circle><path d="M12 7.5v5.5M12 16.5v.01"></path>',
  globe: '<circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"></path>',
  play: '<path d="M7 5v14l12-7z" fill="currentColor"></path>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor"></rect>',
  bug: '<rect x="8" y="6" width="8" height="13" rx="4"></rect><path d="M12 10v9M4 10h4M16 10h4M4.5 16H8M16 16h3.5M9.5 3.5l1.5 2.5M14.5 3.5L13 6"></path>',
  visual: '<rect x="3" y="4.5" width="18" height="15" rx="2"></rect><path d="M12 4.5v15M6 14l2-2.5 2 2.5M14 10.5l2 2.5 2-2.5"></path>',
  a11y: '<circle cx="12" cy="4.5" r="1.6"></circle><path d="M5 8.5l7 1.5 7-1.5M12 10v4.5M9 20.5l3-6 3 6"></path>',
  seo: '<circle cx="11" cy="11" r="6.5"></circle><path d="M20 20l-4.2-4.2M8.5 11h5"></path>',
  perf: '<path d="M4 17.5a8 8 0 1 1 16 0"></path><path d="M12 17.5l4-5.5"></path>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"></path><circle cx="16" cy="7" r="2"></circle><circle cx="10" cy="17" r="2"></circle>',
  chev: '<path d="M6 9l6 6 6-6"></path>',
  desktop: '<rect x="3" y="4.5" width="18" height="12" rx="1.5"></rect><path d="M9 20h6M12 16.5V20"></path>',
  tablet: '<rect x="5" y="3" width="14" height="18" rx="2"></rect><path d="M11 17.5h2"></path>',
  mobile: '<rect x="7" y="3" width="10" height="18" rx="2"></rect><path d="M11 17.5h2"></path>',
  term: '<rect x="3" y="4.5" width="18" height="15" rx="2"></rect><path d="M7 9.5l3 2.5-3 2.5M12.5 15H17"></path>',
  ticket: '<path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h11A2.5 2.5 0 0 1 20 7.5V9a3 3 0 0 0 0 6v1.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5V15a3 3 0 0 0 0-6z"></path><path d="M12 9.5v5M9.5 12h5"></path>',
  doc: '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20z"></path><path d="M13.5 3.5V8h4.5M9.5 12.5h5M9.5 16h5"></path>',
  folder: '<path d="M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4l2 2.5h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 17.5z"></path>',
  send: '<path d="M20.5 3.5L10 14M20.5 3.5l-6.5 17-4-6.5-6.5-4z"></path>',
  eye: '<path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"></path><circle cx="12" cy="12" r="3"></circle>',
  eyeoff: '<path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 8.5 4.5 9.5 6a15 15 0 0 1-2.8 3.3M6.5 7.6C4.6 9 3.2 10.9 2.5 12c1 1.5 4.5 6 9.5 6a9.6 9.6 0 0 0 4.6-1.2M9.9 9.9a3 3 0 0 0 4.2 4.2"></path>',
  bolt: '<path d="M13 3L5 13.5h6.5L10.5 21 19 10h-6.5z"></path>',
};
const LOGO = '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="7" fill="var(--accent)"></rect><path d="M7.5 13.5l3.5 3.5 7.5-8" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path></svg>';

/* ------------------------------------------------------------------ constants */
const LANES = [
  { name: 'Gather requirements', desc: 'Context from Jira and the linked PR, FE, BE or both, target environment, scenarios and the QA checklist.', gate: 'Gate 1 · you review the checklist', empty: 'New tickets from Jira land here' },
  { name: 'Create tests', desc: 'Builds the spec, plus a serial spec for multi-user scenarios, from the approved checklist.', gate: 'No gate · runs straight on', empty: 'Nothing to build' },
  { name: 'Run tests', desc: 'Runs against the resolved environment, fills in the checklist, writes the report and reverts every setting.', gate: 'Gate 2 · you review the results', empty: 'No runs in progress' },
  { name: 'Comment & move Jira ticket', desc: 'Posts the QA summary comment, then moves the ticket. Each one is approved on its own.', gate: 'Gate 3 · comment, then transition', empty: 'Nothing to report' },
  { name: 'Update TestRail tests', desc: 'Drafts cases from the passing items. Pushes only when you say so.', gate: 'Gate 4 · draft review, then push', empty: 'TestRail is up to date' },
];
/* Ticket type from the Jira components: FE, BE, FE+BE, or '' when no component is mapped. */
const TYPES = ['FE', 'BE', 'FE+BE', ''];
const typeName = (ty) => ({ FE: 'Frontend', BE: 'Backend', 'FE+BE': 'Frontend and backend' }[ty] || 'No FE/BE component');
function typeBadge(t) {
  const ty = t.type || '';
  const tip = esc(typeName(ty) + ' · Jira components: ' + ((t.components || []).join(', ') || 'none'));
  if (ty === 'FE+BE') return `<span class="ttype tt-both" title="${tip}"><i>FE</i><i>BE</i></span>`;
  if (ty) return `<span class="ttype tt-${ty.toLowerCase()}" title="${tip}">${ty}</span>`;
  return `<span class="ttype tt-none" title="${tip}">No type</span>`;
}
const RES = { pass: 'PASS', partial: 'PARTIAL', fail: 'FAIL', blocked: 'BLOCKED', nt: 'NOT TESTED' };
const CHECKS = { functional: 'Functional', visual: 'Visual', accessibility: 'Accessibility', seo: 'SEO', performance: 'Performance', 'best-practices': 'Best practices' };
const CHECK_INFO = [
  ['functional', 'Functional', 'Crawls pages, flags JS errors and broken links', IC.bug],
  ['visual', 'Visual regression', 'Pixel-diffs every page against its baseline', IC.visual],
  ['accessibility', 'Accessibility', 'axe-core WCAG 2.1 A and AA on every page', IC.a11y],
  ['seo', 'SEO', 'Titles, meta tags, headings, canonicals', IC.seo],
  ['performance', 'Performance', 'Timing, page weight and Lighthouse', IC.perf],
];
const SEVL = { critical: 'Critical', major: 'Major', minor: 'Minor', info: 'Info' };
const ROUTES = ['board', 'run', 'history', 'integrations'];


/* ------------------------------------------------------------------ state */
const S = {
  theme: store.get('theme', 'dark'),
  route: 'board', routeArg: '',
  toast: '', toastTimer: 0,
  board: { data: null, sel: null, q: '', you: false, type: store.get('boardType', 'all'), env: {}, comment: {}, busy: false, err: '' },
  run: {
    form: Object.assign({ url: '', ticket: '', checks: { functional: true, visual: true, accessibility: true, seo: true, performance: false }, max_pages: 10,
      viewports: { desktop: true, tablet: false, mobile: true }, threshold: 0.5, lighthouse: true, accept_baselines: false, headed: false, publish: false }, store.get('runForm2', {})),
    optsOpen: false, logOpen: true, cur: null, sel: null, sev: 'all', check: 'all', q: '', zoom: false, starting: false, err: '', jiraBusy: false,
  },
  hist: { runs: null, site: null, q: '', status: 'all', pub: {} },
  integ: { cards: null, vals: {}, enabled: {}, reveal: {}, results: {}, saved: {}, testing: {} },
  jira: { st: null, link: '', busy: '', err: '', col: '' },
};

/* ------------------------------------------------------------------ api */
async function api(method, path, body) {
  const r = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) {
    const err = new Error((data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))) || r.statusText);
    err.data = data; err.status = r.status;
    throw err;
  }
  return data;
}

function toast(msg) {
  S.toast = msg;
  clearTimeout(S.toastTimer);
  S.toastTimer = setTimeout(() => { S.toast = ''; schedule(); }, 6000);
  schedule();
}

/* ------------------------------------------------------------------ live events */
function connect() {
  const es = new EventSource('/api/events');
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    const d = S.board.data;
    if (ev.type === 'ticket' && d) {
      const i = d.tickets.findIndex((t) => t.key === ev.ticket.key);
      if (i > -1) d.tickets[i] = ev.ticket; else d.tickets.unshift(ev.ticket);
    } else if (ev.type === 'removed' && d) {
      d.tickets = d.tickets.filter((t) => t.key !== ev.key);
      d.finishedToday = ev.finished_today;
      if (S.board.sel === ev.key) S.board.sel = null;
    } else if (ev.type === 'toast') {
      toast(ev.message);
      return;
    } else if (ev.type === 'run') {
      if (S.run.cur && S.run.cur.id === ev.run.id) S.run.cur = ev.run;
      if (S.hist.runs) {
        const i = S.hist.runs.findIndex((r) => r.id === ev.run.id);
        if (i > -1) S.hist.runs[i] = ev.run; else S.hist.runs.unshift(ev.run);
      }
    }
    schedule();
  };
  es.onerror = () => { /* EventSource retries on its own */ };
}

/* ------------------------------------------------------------------ rendering */
let pending = false;
function schedule() {
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => { pending = false; render(); });
}

function render() {
  const a = document.activeElement;
  const focus = a && a.id ? { id: a.id, s: a.selectionStart, e: a.selectionEnd } : null;
  const scrolls = {};
  document.querySelectorAll('[data-keep]').forEach((el) => { scrolls[el.dataset.keep] = [el.scrollLeft, el.scrollTop]; });
  $app.dataset.theme = S.theme;
  document.documentElement.style.background = S.theme === 'dark' ? '#0B0C0E' : '#F6F6F7';
  const screen = { board: viewBoard, run: viewRun, history: viewHistory, integrations: viewIntegrations }[S.route]();
  $app.innerHTML = viewSide() + screen + (S.route === 'board' ? viewDrawer() : '') + viewToast() + (S.route === 'run' ? viewLightbox() : '');
  document.querySelectorAll('[data-keep]').forEach((el) => {
    const v = scrolls[el.dataset.keep];
    if (v) { el.scrollLeft = v[0]; el.scrollTop = v[1]; }
    if (el.dataset.stick === 'bottom' && (!v || v[1] + el.clientHeight >= el.scrollHeight - 40)) el.scrollTop = el.scrollHeight;
  });
  if (focus) {
    const el = document.getElementById(focus.id);
    if (el) {
      el.focus({ preventScroll: true });
      try { if (focus.s != null) el.setSelectionRange(focus.s, focus.e); } catch (e) { /* not a text input */ }
    }
  }
}

function viewSide() {
  const link = (r, label, icon, n) => `<a class="nav-link" href="#/${r}" ${S.route === r ? 'aria-current="page"' : ''}>${svg(icon)}${label}<span class="kbd">⌘${n}</span></a>`;
  return `<nav class="side" aria-label="Main">
<div style="display:flex;align-items:center;gap:10px;padding:4px 8px 18px">${LOGO}<span style="font-weight:600;font-size:14px;letter-spacing:-.01em">QA Engineer</span></div>
${link('board', 'Board', IC.board, 1)}${link('run', 'Run', IC.run, 2)}${link('history', 'History', IC.history, 3)}${link('integrations', 'Integrations', IC.integ, 4)}
<div class="theme-wrap" style="margin-top:auto;padding:16px 4px 4px">
${S.board.data && S.board.data.config.mode !== 'live' ? '<div style="padding:0 4px 10px"><a class="mode" href="#/integrations" title="The Testing board uses sample tickets and simulated Jira and TestRail. Turn it off on the Integrations screen.">Demo data</a></div>' : ''}
<div class="seg" role="group" aria-label="Theme">
<button type="button" aria-pressed="${S.theme === 'light'}" data-act="theme" data-v="light">${svg(IC.sun, 'ic', 'style="width:14px;height:14px"')}Light</button>
<button type="button" aria-pressed="${S.theme === 'dark'}" data-act="theme" data-v="dark">${svg(IC.moon, 'ic', 'style="width:14px;height:14px"')}Dark</button>
</div></div></nav>`;
}

function viewToast() {
  if (!S.toast) return '';
  return `<div class="toast" role="status">${svg(IC.check)}${esc(S.toast)}<button type="button" aria-label="Dismiss" data-act="dismissToast">${svg(IC.close, 'ic', 'style="width:14px;height:14px"')}</button></div>`;
}

/* ================================================================== BOARD */
function ago(ts) {
  if (!ts) return 'never synced';
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return 'synced just now';
  if (s < 3600) return `synced ${Math.round(s / 60)} min ago`;
  return `synced ${Math.round(s / 3600)} h ago`;
}
const isWorking = (t) => t.sub === 'working' || t.sub === 'drafting';
const allItems = (t) => t.checklist.flatMap((s) => s.items);

function deco(t) {
  const items = allItems(t);
  const counts = { pass: 0, partial: 0, fail: 0, blocked: 0, nt: 0 };
  items.forEach((i) => { counts[i.result] += 1; });
  const passes = items.filter((i) => i.result === 'pass');
  const working = isWorking(t) && !t.error;
  const st = t.stage, sub = t.sub;
  const d = { stateLabel: '', summary: '', act: 'Review', cls: 'state state-you', note: '', primary: '', disabled: false, counts, items, passes };
  if (st === 0 && sub === 'working') { d.stateLabel = 'Gathering'; d.summary = t.doing; }
  if (st === 0 && sub === 'blocked') { d.stateLabel = 'Needs environment'; d.cls = 'state state-warn'; d.summary = 'No PR environment link in the comments'; d.act = 'Add environment'; d.note = 'Stopped instead of guessing an environment.'; d.primary = 'Use this environment'; d.disabled = !/^https?:\/\/\S+/.test((S.board.env[t.key] || '').trim()); }
  if (st === 0 && sub === 'gate') { d.stateLabel = 'Gate 1 · your review'; d.summary = `Checklist ready · ${items.length} items in ${t.checklist.length} sections`; d.act = 'Review checklist'; d.note = 'Gate 1 of 4. Approving builds and runs the spec.'; d.primary = 'Approve checklist'; }
  if (st === 1) { d.stateLabel = 'Building'; d.summary = t.doing || `Building ${t.key}.spec.ts`; }
  if (st === 2 && sub === 'sso') { d.stateLabel = 'SSO login needed'; d.cls = 'state state-warn'; d.summary = 'Waiting for you to sign in'; d.act = 'Sign in'; d.note = 'The run continues once the session is ready.'; d.primary = "I've signed in"; }
  if (st === 2 && sub === 'working') { d.stateLabel = 'Running'; d.summary = t.doing || `Running ${t.key}.spec.ts`; }
  if (st === 2 && sub === 'gate') { d.stateLabel = 'Gate 2 · your review'; d.summary = `${counts.pass}/${items.length} pass${counts.fail ? ' · ' + counts.fail + ' fail' : ''} · ${t.cleanup.length ? t.cleanup.length + ' settings reverted' : 'no settings changed'}`; d.act = 'Review results'; d.note = 'Gate 2 of 4. Jira stays untouched until you approve.'; d.primary = 'Approve results'; }
  if (st === 3 && sub === 'comment') { d.stateLabel = 'Gate 3 · comment'; d.summary = 'Comment ready · then ' + (t.target ? 'move to ' + t.target : 'choose a target state'); d.act = 'Review comment'; d.note = 'Gate 3, part 1. Posting does not approve the move.'; d.primary = 'Post comment'; d.disabled = !((S.board.comment[t.key] != null ? S.board.comment[t.key] : t.comment) || '').trim(); }
  if (st === 3 && sub === 'transition') { d.stateLabel = 'Gate 3 · move ticket'; d.summary = `Comment posted · ${t.status} → ${t.target || 'target not set'}`; d.act = 'Review move'; d.note = 'Gate 3, part 2. A separate approval from the comment.'; d.primary = t.target ? 'Move to ' + t.target : 'Choose a state first'; d.disabled = !t.target; }
  if (st === 4 && sub === 'drafting') { d.stateLabel = 'Drafting cases'; d.summary = 'Checking section and duplicates (read-only)'; }
  if (st === 4 && sub === 'gate') { d.stateLabel = 'Gate 4 · your review'; d.summary = `${t.cases.length} cases drafted · ${t.section}`; d.act = 'Review draft'; d.note = 'Gate 4 of 4. Approving does not push anything.'; d.primary = 'Approve draft'; }
  if (st === 4 && sub === 'approved') { d.stateLabel = 'Draft approved'; d.cls = 'state state-ok'; d.summary = 'Not pushed · waiting for your go-ahead'; d.act = 'Push'; d.note = 'Pushes only on this explicit go-ahead, then verifies with get_cases.'; d.primary = `Push ${t.cases.length} cases to TestRail`; }
  if (working) d.cls = 'state state-work';
  if (t.error) { d.cls = 'state state-warn'; d.stateLabel = 'Stopped · needs you'; d.summary = t.error; d.act = 'See error'; }
  d.working = working;
  d.you = !working;
  return d;
}

function viewBoard() {
  const B = S.board, data = B.data;
  if (!data) {
    return `<main class="main"><h1 style="margin:0;font-size:18px;font-weight:600">Testing board</h1>
<div class="${B.err ? 'callout c-err' : 'notice'}">${B.err ? svg(IC.err) + esc(B.err) : 'Loading tickets…'}</div></main>`;
  }
  const c = data.config;
  const q = B.q.trim().toLowerCase();
  const waiting = data.tickets.filter((t) => !isWorking(t) || t.error).length;
  const base = data.tickets.filter((t) => (!q || (t.key + ' ' + t.title).toLowerCase().includes(q)) && (!B.you || !isWorking(t) || t.error));
  const typeCount = (ty) => base.filter((t) => (t.type || '') === ty).length;
  if (B.type !== 'all' && !TYPES.includes(B.type)) B.type = 'all';
  const visible = B.type === 'all' ? base : base.filter((t) => (t.type || '') === B.type);
  const typeOpts = [['all', 'All', base.length], ['FE', 'FE', typeCount('FE')], ['BE', 'BE', typeCount('BE')], ['FE+BE', 'FE+BE', typeCount('FE+BE')]];
  if (typeCount('') || B.type === '') typeOpts.push(['', 'No type', typeCount('')]);
  const typeSeg = `<div class="seg seg-type" role="group" aria-label="Ticket type">${typeOpts.map(([v, label, n]) =>
    `<button type="button" aria-pressed="${B.type === v}" data-act="ttype" data-v="${esc(v)}" title="${esc(v === 'all' ? 'Every ticket type' : typeName(v))}">${v && v !== 'all' ? `<span class="tdot tdot-${v === 'FE+BE' ? 'both' : v.toLowerCase()}" aria-hidden="true"></span>` : ''}${label}<span class="seg-n">${n}</span></button>`).join('')}</div>`;
  const lanes = LANES.map((l, i) => {
    const cards = visible.filter((t) => t.stage === i);
    return `<section class="lane" role="listitem" aria-labelledby="lane-${i + 1}">
<div class="lane-head">
<div style="display:flex;align-items:center;gap:8px"><span class="step" aria-hidden="true">${i + 1}</span><h2 id="lane-${i + 1}" style="margin:0;font-size:13px;font-weight:600">${l.name}</h2><span class="cnt" aria-label="${cards.length} tickets">${cards.length}</span></div>
<p style="margin:0;color:var(--muted);font-size:12px;line-height:1.4">${l.desc}</p>
<div class="gate-line${i === 1 ? '' : ' has-gate'}">${svg(IC.lock, 'ic ic-s')}${l.gate}</div>
</div>
<div class="lane-body">${cards.map(viewCard).join('') || `<div class="lane-empty">${l.empty}</div>`}</div>
</section>`;
  }).join('');
  return `<main class="main">
<header style="display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap">
<div style="min-width:0">
<h1 style="margin:0;font-size:18px;font-weight:600;letter-spacing:-.01em">Testing board</h1>
<p style="margin:2px 0 0;color:var(--muted)">Tickets in the Jira <strong style="color:var(--fg);font-weight:500">${esc(c.column)}</strong> column of ${esc(c.project)}, taken through the test-ticket workflow. <strong style="color:var(--fg);font-weight:500">${waiting} waiting on you</strong> · ${data.finishedToday} finished today.</p>
</div>
<div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<span class="pill" title="Auto mode never skips a review gate">${svg(IC.lock, 'ic ic-s')}Auto mode · 4 gates always stop</span>
<span class="pill" role="status"><span class="d d-ok"></span>Jira · ${esc(c.project)} · ${esc(c.column)} · ${ago(data.lastSync)}</span>
<button type="button" class="btn" data-act="sync" ${B.syncing ? 'disabled' : ''}>${svg(IC.sync, B.syncing ? 'ic spin' : 'ic')}Sync now</button>
</div>
</header>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<label class="search" style="flex:0 1 260px">${svg(IC.search, 'ic', 'style="width:14px;height:14px"')}<span class="sr-only">Search tickets</span><input id="board-q" type="search" placeholder="Search key or title" value="${esc(B.q)}" data-in="boardQ"></label>
<div class="seg" role="group" aria-label="Show"><button type="button" aria-pressed="${!B.you}" data-act="you" data-v="0">All tickets</button><button type="button" aria-pressed="${B.you}" data-act="you" data-v="1">Waiting on me</button></div>
${typeSeg}
<span class="mono" style="margin-left:auto;color:var(--muted);font-size:12px">Tests as ${esc(c.account)} · OU ${esc(c.ou)}</span>
</div>
${c.mode !== 'live' ? `<div class="notice jc-banner">${svg(IC.info)}<span>These are sample tickets. Paste your Jira board link to test real tickets.</span><a class="btn btn-sm btn-primary" href="#/integrations" style="margin-left:auto">Connect Jira${svg(IC.arrow, 'ic ic-s')}</a></div>` : ''}
<div class="board" role="list" aria-label="QA workflow steps" data-keep="board">${lanes}</div>
</main>`;
}

function viewCard(t) {
  const d = deco(t);
  const cls = 'tk' + (d.you ? ' is-you' : '') + (S.board.sel === t.key ? ' is-sel' : '');
  return `<article class="${cls}">
<button type="button" class="tk-open" data-act="open" data-key="${esc(t.key)}" aria-label="${esc(t.key + ', ' + (t.type || 'no type') + ', ' + t.title + ', ' + d.stateLabel)}">
<span class="tk-meta"><span class="mono">${esc(t.key)}</span>${typeBadge(t)}<span style="margin-left:auto">${esc(t.status)}</span></span>
<span class="tk-title">${esc(t.title)}</span>
</button>
<div class="tk-stage">
<span class="${d.cls}">${d.working ? svg(IC.spin, 'ic spin', 'style="width:11px;height:11px"') : ''}${d.you && d.cls.includes('state-you') ? svg(IC.person, 'ic ic-s') : ''}${esc(d.stateLabel)}</span>
<span class="trunc" style="white-space:normal">${esc(d.summary)}</span>
${d.working ? '<div class="bar" aria-hidden="true"><i></i></div>' : ''}
</div>
<div class="tk-foot"><span class="trunc mono" style="font-size:11px">${esc(t.env ? t.envShort : 'no environment yet')}</span><span style="margin-left:auto"></span>
${d.you ? `<button type="button" class="btn btn-sm" data-act="open" data-key="${esc(t.key)}">${esc(d.act)}${svg(IC.arrow, 'ic ic-s')}</button>` : ''}</div>
</article>`;
}

function gateTracker(t) {
  const st = t.stage, sub = t.sub;
  const g = [
    ['1 Checklist', st > 0, st === 0 && sub === 'gate'],
    ['2 Results', st > 2, st === 2 && sub === 'gate'],
    ['3a Comment', st > 3 || (st === 3 && sub === 'transition'), st === 3 && sub === 'comment'],
    ['3b Move', st > 3, st === 3 && sub === 'transition'],
    ['4 Draft', st === 4 && sub === 'approved', st === 4 && sub === 'gate'],
  ];
  return g.map((x) => `<div class="gate${x[1] ? ' g-done' : x[2] ? ' g-now' : ''}"><span></span><span class="trunc">${x[0]}</span></div>`).join('');
}

function viewDrawer() {
  const B = S.board;
  const t = B.data && B.data.tickets.find((x) => x.key === B.sel);
  if (!t) return '';
  const d = deco(t);
  const st = t.stage, sub = t.sub;
  const ran = t.ran;
  let body = '';

  body += `<div><div class="lbl">Target environment</div>`;
  if (t.env) {
    body += `<div class="box"><div class="brow" style="flex-direction:column;align-items:flex-start;gap:2px"><span style="color:var(--muted)">${esc(t.env.kind)}</span><span class="mono trunc" style="max-width:100%">${esc(t.env.url)}</span><span style="color:var(--faint);font-size:11.5px">${esc(t.env.api)}</span></div></div>`;
    if (/^https?:/.test(t.env.url)) body += `<a class="btn btn-quiet btn-sm" style="margin-top:6px" href="#/run?ticket=${encodeURIComponent(t.key)}&url=${encodeURIComponent(t.env.url)}">${svg(IC.run, 'ic ic-s')}Run site checks on this environment</a>`;
  } else {
    body += `<div class="callout c-warn">${svg(IC.warn)}<span>${esc(sub === 'blocked' && t.doing ? t.doing : 'No environment resolved yet.')} The workflow stops here instead of falling back to the shared environment, because the change may not be there yet.</span></div>`;
    if (sub === 'blocked') body += `<label class="lbl" for="env-input" style="margin-top:12px">PR environment URL</label><input id="env-input" class="inp mono" type="url" placeholder="https://pr-1234.ci-cd.on-eva.io/" value="${esc(B.env[t.key] || '')}" data-in="env" data-key="${esc(t.key)}">`;
  }
  body += '</div>';

  if (t.error) {
    body += `<div class="callout c-err">${svg(IC.err)}<div style="display:flex;flex-direction:column;gap:8px;min-width:0"><span>${esc(t.error)}</span>${isWorking(t) ? `<button type="button" class="btn btn-sm" style="align-self:flex-start" data-act="retry" data-key="${esc(t.key)}">Retry this step</button>` : ''}</div></div>`;
  }

  if (st === 0 && sub !== 'gate') {
    const steps = ['Context from Jira and the linked PR', sub === 'blocked' ? `Classified ${t.type || 'without FE/BE'} · no environment found` : `Classified ${t.type || 'without FE/BE'} · environment resolved`, 'Scenarios', 'QA checklist'];
    body += `<div><div class="lbl">Phase 1 progress</div><div class="box">${steps.map((x, i) => {
      const doneN = sub === 'blocked' ? 1 : t.p1 + 1;
      const done = i < doneN - 1;
      const now = sub === 'working' && i === doneN - 1 && !t.error;
      return `<div class="brow"><span class="fdot ${done ? 'f-yes' : 'f-no'}">${done ? svg(IC.check, 'ic ic-s') : now ? svg(IC.spin, 'ic ic-s spin') : ''}</span><span>${esc(x)}</span></div>`;
    }).join('')}</div>${t.doing && sub === 'working' ? `<p style="margin:6px 0 0;color:var(--muted);font-size:12px">${esc(t.doing)}</p>` : ''}</div>`;
  }
  if (st === 2 && sub === 'sso') {
    body += `<div class="callout c-warn">${svg(IC.person)}<span>Sign in with SSO as <span class="mono">${esc(B.data.config.account)}</span> in the browser window that just opened, then continue. This account has no password login. The automation account is only used for unattended runs.</span></div>`;
  }
  if ((st === 0 && sub === 'gate') || (st === 2 && sub === 'gate')) {
    const c = d.counts;
    const summary = ran ? `${c.pass} pass · ${c.partial} partial · ${c.fail} fail · ${c.blocked} blocked · ${c.nt} not tested` : `${d.items.length} items · all NOT TESTED`;
    let n = 0;
    body += `<div style="display:flex;flex-direction:column;gap:14px">
<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap"><span class="lbl" style="margin:0;white-space:nowrap">QA checklist</span><span class="mono" style="margin-left:auto;color:var(--muted);font-size:12px">${summary}</span></div>
${st === 0 ? `<div class="callout c-info">${svg(IC.info)}<span>Nothing has run yet. This is the plan, not a result.</span></div>` : ''}
${t.checklist.map((sec, si) => {
  const start = n + 1;
  const items = sec.items.map((it) => {
    n += 1;
    const r = ran ? it.result : 'nt';
    return `<li><span class="res r-${r}">${RES[r]}</span>${esc(it.text)}${ran && it.bug ? `<div class="bug">${esc(it.bug)}</div>` : ''}</li>`;
  }).join('');
  return `<div><h3 class="sec-h">${si + 1}. ${esc(sec.name)}</h3><ol class="cl" start="${start}">${items}</ol></div>`;
}).join('')}
</div>`;
  }
  if (st === 2 && sub === 'gate') {
    body += `<div><div class="lbl">Cleanup</div><div class="box">${t.cleanup.map((c) => `<div class="brow"><span class="fdot ${c.reread ? 'f-yes' : 'f-no'}">${svg(c.reread ? IC.check : IC.warn, 'ic ic-s')}</span><span class="mono trunc">${esc(c.name)}</span><span style="margin-left:auto;color:var(--muted);white-space:nowrap">reverted to ${esc(c.value)} · ${c.reread ? 're-read ✓' : 'not re-read'}</span></div>`).join('') || '<div class="brow" style="color:var(--muted)">No settings were changed.</div>'}</div>
${t.left ? `<div class="callout c-warn" style="margin-top:8px">${svg(IC.warn)}<span>Left behind: ${esc(t.left)}</span></div>` : ''}</div>`;
  }
  if (st === 3 && sub === 'comment') {
    const val = B.comment[t.key] != null ? B.comment[t.key] : (t.comment || '');
    body += `<div><label class="lbl" for="jira-comment">QA summary comment · exact text that will be posted</label><textarea id="jira-comment" class="inp mono" data-in="comment" data-key="${esc(t.key)}">${esc(val)}</textarea></div>
<div><label class="lbl" for="jira-pre-target">Planned target state <span style="color:var(--faint)">(moved only after its own approval)</span></label><input id="jira-pre-target" class="inp" value="${esc(t.target)}" data-in="target" data-key="${esc(t.key)}" placeholder="e.g. Docs"></div>`;
  }
  if (st === 3 && sub === 'transition') {
    body += `<div class="callout c-ok">${svg(IC.check)}<span>QA summary comment posted at ${esc(t.comment_at)}.</span></div>
<div><label class="lbl" for="jira-move">Move from <span class="mono" style="color:var(--fg)">${esc(t.status)}</span> to</label>
<select id="jira-move" class="inp" data-in="targetSel" data-key="${esc(t.key)}"><option value="">Choose a target state…</option>${t.transitions.map((o) => `<option value="${esc(o)}" ${o === t.target ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>
<p style="margin:6px 0 0;color:var(--muted);font-size:12px">Only transitions Jira returns for this ticket are listed. Names are matched exactly.</p></div>`;
  }
  if (st === 4 && sub !== 'drafting') {
    body += `<div><div class="lbl" style="justify-content:space-between"><span>TestRail cases · draft</span><span class="mono">${t.cases.length} cases</span></div>
<div class="box"><div class="brow" style="color:var(--muted)">Section <span class="mono" style="color:var(--fg)">${esc(t.section)}</span></div>
${t.cases.map((c, i) => `<div class="brow"><span class="mono" style="color:var(--faint);width:52px;flex:none">Draft ${i + 1}</span><span>${esc(c.title)}</span></div>`).join('')}</div>
<p style="margin:6px 0 0;color:var(--muted);font-size:12px">${t.dups ? t.dups + ' existing case' + (t.dups > 1 ? 's' : '') + ' matched and ' + (t.dups > 1 ? 'were' : 'was') + ' left out. ' : 'No duplicates found. '}Only PASS items become cases.</p></div>`;
  }
  body += `<div><div class="lbl">Files · tests/tickets/${esc(t.key)}/</div><div class="box">${t.files.map((f) => `<div class="brow"><span class="fdot ${f.ok ? 'f-yes' : 'f-no'}">${svg(f.ok ? IC.check : IC.dotc, 'ic ic-s')}</span>${f.ok ? `<a class="mono trunc file-link" href="/api/tickets/${encodeURIComponent(t.key)}/files/${encodeURIComponent(f.name)}" target="_blank" rel="noopener">${esc(f.name)}</a>` : `<span class="mono trunc">${esc(f.name)}</span>`}</div>`).join('')}</div></div>`;

  const canAct = d.primary && !t.error;
  return `<aside class="drawer" aria-label="Ticket details">
<div style="padding:16px 18px 14px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:10px">
<div style="display:flex;align-items:center;gap:8px">
<span class="mono" style="color:var(--muted)">${esc(t.key)}</span>${typeBadge(t)}<span style="color:var(--muted);font-size:12px">Jira status: ${esc(t.status)}</span>
<a class="btn btn-quiet btn-sm" href="${esc(t.jiraUrl)}" target="_blank" rel="noopener" style="margin-left:auto">Open in Jira${svg(IC.ext, 'ic ic-s')}</a>
<button type="button" class="btn btn-quiet btn-icon" aria-label="Close details" data-act="close">${svg(IC.close)}</button>
</div>
<h2 style="margin:0;font-size:17px;font-weight:600;line-height:1.3;letter-spacing:-.01em">${esc(t.title)}</h2>
<div class="gates" aria-label="Review gates">${gateTracker(t)}</div>
<div style="font-size:12px;color:var(--muted)">${LANES[st].name} · <strong style="color:var(--fg);font-weight:500">${esc(d.stateLabel)}</strong></div>
</div>
<div class="drawer-body" data-keep="drawer-${esc(t.key)}">${body}</div>
<div style="padding:12px 18px;border-top:1px solid var(--border);display:flex;gap:10px;align-items:center;background:var(--raised)">
<span style="color:${B.actErr ? 'var(--crit)' : 'var(--muted)'};font-size:12px;flex:1;min-width:0">${esc(B.actErr || (t.error ? 'Fix the problem above, then retry.' : d.note || 'Working. Nothing needs you yet.'))}</span>
${canAct ? `<button type="button" class="btn btn-primary" data-act="primary" data-key="${esc(t.key)}" ${d.disabled || B.busy ? 'disabled' : ''}>${B.busy ? svg(IC.spin, 'ic spin') : ''}${esc(d.primary)}</button>` : ''}
${d.working ? `<span class="state state-work">${svg(IC.spin, 'ic spin', 'style="width:11px;height:11px"')}Working</span>` : ''}
</div>
</aside>`;
}

async function primaryAction(key) {
  const B = S.board;
  const t = B.data.tickets.find((x) => x.key === key);
  if (!t || B.busy) return;
  const payload = {};
  if (t.sub === 'blocked') payload.url = (B.env[key] || '').trim();
  if (t.stage === 3 && t.sub === 'comment') payload.comment = B.comment[key] != null ? B.comment[key] : t.comment;
  if (t.stage === 3 && t.sub === 'transition') payload.target = t.target;
  B.busy = true; B.actErr = ''; schedule();
  try {
    const r = await api('POST', `/api/tickets/${encodeURIComponent(key)}/action`, { action: t.expected, stage: t.stage, sub: t.sub, payload });
    if (r.ticket) { const i = B.data.tickets.findIndex((x) => x.key === key); if (i > -1) B.data.tickets[i] = r.ticket; }
    if (r.done) { B.data.tickets = B.data.tickets.filter((x) => x.key !== key); B.sel = null; }
    delete B.comment[key];
  } catch (e) {
    B.actErr = e.message;
    if (e.data && e.data.transitions) { const i = B.data.tickets.findIndex((x) => x.key === key); if (i > -1) { B.data.tickets[i].transitions = e.data.transitions; B.data.tickets[i].target = ''; } }
    await loadBoard();
  } finally {
    B.busy = false; schedule();
  }
}

let draftTimer = 0;
function saveDraft(key, body) {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(async () => {
    try {
      const r = await api('PATCH', `/api/tickets/${encodeURIComponent(key)}/draft`, body);
      const i = S.board.data.tickets.findIndex((x) => x.key === key);
      if (i > -1) S.board.data.tickets[i] = r.ticket;
      S.board.actErr = '';
    } catch (e) { S.board.actErr = e.message; }
    schedule();
  }, 400);
}

async function loadBoard() {
  try { S.board.data = await api('GET', '/api/state'); S.board.err = ''; } catch (e) { S.board.err = 'Could not load the board: ' + e.message; }
  schedule();
}

/* ================================================================== RUN */
function fmtDur(sec) { sec = Math.max(0, Math.round(sec || 0)); return `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, '0')}s`; }
function fmtClock(sec) { sec = Math.max(0, Math.round(sec || 0)); return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`; }
const runPath = (r, p) => (p && p.startsWith('/') ? p : `/runs/${encodeURIComponent(r.id)}/${p}`);
const pathOf = (u) => { try { const x = new URL(u); return x.pathname + x.search; } catch (e) { return u; } };

function viewRun() {
  const R = S.run, f = R.form, r = R.cur;
  const st = r ? r.state : 'empty';
  const running = st === 'running';
  const done = ['passed', 'failed', 'stopped'].includes(st);
  const ticket = (r && r.ticket) || f.ticket;
  const tk = ticket && S.board.data ? S.board.data.tickets.find((t) => t.key === ticket) : null;
  const enabled = Object.values(f.checks).filter(Boolean).length;
  const vpNames = ['desktop', 'tablet', 'mobile'].filter((k) => f.viewports[k]).map((k) => k[0].toUpperCase() + k.slice(1)).join(', ') || 'No viewport';
  const optsSummary = [f.max_pages + ' pages', vpNames, f.threshold + '% diff', f.lighthouse ? 'Lighthouse' : 'No Lighthouse'].join('  ·  ');

  let html = `<main class="main">
<header style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-height:36px">
<div style="display:flex;flex-direction:column;gap:2px;min-width:0">
<div class="crumb"><a href="#/board">Board</a><span aria-hidden="true">/</span><span>Run tests</span>${ticket ? `<span aria-hidden="true">/</span><span class="mono" style="color:var(--fg)">${esc(ticket)}</span>` : ''}</div>
<div style="display:flex;align-items:baseline;gap:10px;min-width:0"><h1 style="margin:0;font-size:18px;font-weight:600;letter-spacing:-.01em" class="trunc">${esc(tk ? tk.title : (r ? r.url : 'New run'))}</h1><span class="mono" style="color:var(--muted);font-size:12px">${esc(r ? r.id : 'New run')}</span></div>
</div>
<div style="margin-left:auto;display:flex;gap:8px">
${done ? `<a class="btn" href="${runPath(r, 'report.html')}" target="_blank" rel="noopener">${svg(IC.ext)}Open full report</a>` : `<button type="button" class="btn" disabled>${svg(IC.ext)}Open full report</button>`}
${done && ticket ? `<a class="btn btn-primary" href="#/board" data-act="openTicket" data-key="${esc(ticket)}">Review results${svg(IC.arrow)}</a>` : ''}
${done && !ticket ? `<button type="button" class="btn" data-act="newRun">New run</button>` : ''}
</div>
</header>

<section class="card" aria-label="Run setup" style="padding:16px;display:flex;flex-direction:column;gap:14px">
<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
<label for="target-url" class="sr-only">Website URL</label>
<div class="urlbox" style="flex:1 1 420px;min-width:0">${svg(IC.globe, 'ic', 'style="width:18px;height:18px;color:var(--faint)"')}<input id="target-url" class="mono" type="url" value="${esc(f.url)}" data-in="runUrl" ${running ? 'readonly' : ''} placeholder="https://your-site.com" spellcheck="false"></div>
${running ? `<button type="button" class="btn btn-stop btn-lg" data-act="stopRun">${svg(IC.stop)}Stop</button>` : `<button type="button" class="btn btn-primary btn-lg" data-act="startRun" ${R.starting || !f.url.trim() || !enabled ? 'disabled' : ''}>${svg(IC.play)}Run tests<span class="mono" style="font-size:11px;opacity:.7;margin-left:4px">⌘↵</span></button>`}
</div>
${R.err ? `<div class="callout c-err">${svg(IC.err)}<span>${esc(R.err)}</span></div>` : ''}
<div><div class="lbl">Checks <span style="color:var(--faint)">· ${enabled} of 5 on</span></div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:10px">
${CHECK_INFO.map(([k, name, desc, icon]) => `<button type="button" class="tog" aria-pressed="${!!f.checks[k]}" data-act="ck" data-v="${k}" ${running ? 'disabled' : ''}>
<span style="display:flex;align-items:center;gap:8px;width:100%"><span class="tog-ic">${svg(icon)}</span><span style="font-weight:600">${name}</span><span class="sw" style="margin-left:auto" aria-hidden="true"></span></span>
<span style="color:var(--muted);font-size:12px">${desc}</span></button>`).join('')}
</div></div>
</section>

<section class="card" aria-label="Options">
<button type="button" class="disc" aria-expanded="${R.optsOpen}" aria-controls="run-options" data-act="opts">${svg(IC.sliders, 'ic', 'style="color:var(--muted)"')}<span style="font-weight:600">Options</span><span class="mono trunc" style="color:var(--muted);font-size:12px">${esc(optsSummary)}</span>${svg(IC.chev, 'ic chev', 'style="margin-left:auto"')}</button>
${R.optsOpen ? `<div id="run-options" style="padding:4px 16px 16px;display:flex;flex-direction:column;gap:16px">
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px">
<div><label class="lbl" for="opt-max">Max pages</label><input id="opt-max" class="inp mono" type="number" min="1" max="2000" value="${esc(f.max_pages)}" data-in="runMax"></div>
<div><div class="lbl" id="vp-label">Viewports</div><div role="group" aria-labelledby="vp-label" style="display:flex;gap:6px;flex-wrap:wrap">
${['desktop', 'tablet', 'mobile'].map((k) => `<button type="button" class="vchip" aria-pressed="${!!f.viewports[k]}" data-act="vp" data-v="${k}">${svg(IC[k], 'ic', 'style="width:14px;height:14px"')}${k[0].toUpperCase() + k.slice(1)}</button>`).join('')}
</div></div>
<div><label class="lbl" for="opt-thr">Visual diff threshold</label><div style="position:relative"><input id="opt-thr" class="inp mono" type="number" min="0" max="100" step="0.1" value="${esc(f.threshold)}" data-in="runThr" style="padding-right:30px"><span style="position:absolute;right:10px;top:7px;color:var(--muted)" aria-hidden="true">%</span></div></div>
<div><label class="lbl" for="opt-ticket">Ticket <span style="color:var(--faint)">(optional)</span></label><input id="opt-ticket" class="inp mono" value="${esc(f.ticket)}" data-in="runTicket" placeholder="OPTR-48466"></div>
</div>
<div style="display:flex;flex-wrap:wrap;gap:10px 24px;padding-top:12px;border-top:1px solid var(--border)">
${[['lighthouse', 'Use Lighthouse'], ['accept_baselines', 'Accept current screenshots as new baselines'], ['headed', 'Show browser window'], ['publish', 'Publish to integrations after run']].map(([k, l]) => `<label class="cb"><input type="checkbox" ${f[k] ? 'checked' : ''} data-in="runOpt" data-v="${k}">${l}</label>`).join('')}
</div></div>` : ''}
</section>`;

  if (!r) {
    html += `<section class="card" aria-label="No run yet" style="padding:48px 24px;display:flex;flex-direction:column;align-items:center;text-align:center;gap:10px">
<svg class="empty-ill" width="132" height="84" viewBox="0 0 132 84" fill="none" aria-hidden="true"><rect x="1" y="1" width="130" height="82" rx="8" stroke="currentColor" stroke-width="1.5"></rect><path d="M1 15h130" stroke="currentColor" stroke-width="1.5"></path><circle cx="10" cy="8" r="2" fill="currentColor"></circle><circle cx="17" cy="8" r="2" fill="currentColor"></circle><circle cx="24" cy="8" r="2" fill="currentColor"></circle><rect x="14" y="26" width="58" height="6" rx="3" fill="currentColor" opacity=".35"></rect><rect x="14" y="40" width="42" height="6" rx="3" fill="currentColor" opacity=".35"></rect><rect x="14" y="54" width="50" height="6" rx="3" fill="currentColor" opacity=".35"></rect><circle cx="100" cy="47" r="16" stroke="var(--accent)" stroke-width="2"></circle><path d="M93 47.5l5 5 9-10" stroke="var(--accent)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path></svg>
<h2 style="margin:8px 0 0;font-size:16px;font-weight:600">No run yet</h2>
<p style="margin:0;color:var(--muted);max-width:420px">Enter a URL and press Run tests. Findings stream in here while pages are crawled${ticket ? ', and the result goes back to the board' : ''}.</p>
<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;justify-content:center"><a class="btn" href="#/board">Back to board</a></div>
</section></main>`;
    return html;
  }

  if (st === 'error') {
    html += `<section class="card" role="alert" style="padding:16px;display:flex;gap:14px;align-items:flex-start;border-color:color-mix(in srgb,var(--crit-dot) 45%,var(--border))">
<span style="width:32px;height:32px;border-radius:8px;display:grid;place-items:center;background:var(--crit-bg);color:var(--crit);flex:none">${svg(IC.err)}</span>
<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:8px">
<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><h2 style="margin:0;font-size:15px;font-weight:600">Run couldn't ${r.crawled ? 'finish' : 'start'}</h2><span class="status sm st-error">Error</span></div>
<p style="margin:0;color:var(--muted)">${/timeout/i.test(r.error) ? "The site didn't respond before the navigation timeout. Check the URL, VPN or basic auth, then try again." : /executable|browser/i.test(r.error) ? 'The test browser is not installed. Run "python -m playwright install chromium", then try again.' : 'Something went wrong while testing the site.'}</p>
<pre class="pre mono">${esc(r.error)}</pre>
<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn btn-primary" data-act="startRun">Retry</button><button type="button" class="btn" data-act="openLog">Show log</button></div>
</div></section>`;
    return html + viewLog(r) + '</main>';
  }

  const counts = r.counts;
  const elapsed = (running ? Date.now() / 1000 : r.finished) - r.started;
  const pct = r.total ? Math.min(100, Math.round((r.crawled / r.total) * 100)) : 0;
  const statusCls = { running: 'st-running', passed: 'st-passed', failed: 'st-failed', stopped: 'st-stopped' }[st];
  html += `<section class="card" aria-label="Progress" style="padding:12px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:12px 28px">
<div style="flex:1 1 260px;min-width:0;display:flex;flex-direction:column;gap:8px">
<div style="display:flex;justify-content:space-between;gap:12px"><span><strong style="font-variant-numeric:tabular-nums">${r.crawled}</strong><span style="color:var(--muted)"> / ${r.total} pages crawled</span></span><span class="mono" style="color:var(--muted)">${pct}%</span></div>
<div class="pbar${running ? ' is-live' : ''}" role="progressbar" aria-valuemin="0" aria-valuemax="${r.total}" aria-valuenow="${r.crawled}" aria-label="Pages crawled"><i style="width:${pct}%"></i></div>
</div>
<div style="flex:2 1 300px;min-width:0"><div class="lbl" style="margin-bottom:2px">${running ? 'Now testing' : 'Last page tested'}</div><div class="mono trunc" style="font-size:12.5px">${esc(r.current || '—')}</div></div>
<div><div class="lbl" style="margin-bottom:2px">Elapsed</div><div class="mono" style="font-size:15px;font-variant-numeric:tabular-nums">${fmtClock(elapsed)}</div></div>
</section>
<section class="card" aria-label="Summary" style="display:flex;flex-wrap:wrap;overflow:hidden">
<div class="sum" style="flex:1.3 1 140px"><div class="lbl">Status</div><span class="status ${statusCls}">${running ? svg(IC.spin, 'ic spin', 'style="width:14px;height:14px"') : ''}${st}</span></div>
${['critical', 'major', 'minor', 'info'].map((k) => `<div class="sum"><div class="lbl"><span class="dot d-${k}"></span>${SEVL[k]}</div><div class="num">${counts[k]}</div></div>`).join('')}
<div class="sum"><div class="lbl">Pages tested</div><div class="num">${r.crawled}</div></div>
<div class="sum"><div class="lbl">Duration</div><div class="num">${fmtDur(elapsed)}</div></div>
</section>`;

  const q = R.q.trim().toLowerCase();
  const list = r.findings.filter((x) => (R.sev === 'all' || x.sev === R.sev) && (R.check === 'all' || x.check === R.check) && (!q || (x.title + ' ' + x.url + ' ' + x.details).toLowerCase().includes(q)));
  const sel = r.findings.find((x) => x.id === R.sel) || list[0] || null;
  html += `<div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start">
<section class="card" aria-label="Findings" style="flex:999 1 460px;min-width:0;overflow:hidden">
<div style="padding:12px 14px;display:flex;flex-wrap:wrap;align-items:center;gap:8px">
<h2 class="h-sec">Findings</h2><span class="mono" style="color:var(--muted);font-size:12px">${list.length} of ${r.findings.length}</span>
<label class="search" style="margin-left:auto;flex:0 1 220px;height:30px">${svg(IC.search, 'ic', 'style="width:14px;height:14px"')}<span class="sr-only">Search findings</span><input id="find-q" type="search" placeholder="Search findings" value="${esc(R.q)}" data-in="runQ"></label>
<label class="sr-only" for="check-filter">Filter by check</label>
<select id="check-filter" class="sel" data-in="runCheck"><option value="all">All checks</option>${Object.entries(CHECKS).map(([k, v]) => `<option value="${k}" ${R.check === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
</div>
<div role="group" aria-label="Filter by severity" style="display:flex;gap:6px;flex-wrap:wrap;padding:0 14px 12px">
${[['all', 'All', r.findings.length]].concat(['critical', 'major', 'minor', 'info'].map((k) => [k, SEVL[k], counts[k]])).map(([k, l, n]) => `<button type="button" class="fchip" aria-pressed="${R.sev === k}" data-act="sev" data-v="${k}"><span class="dot d-${k}"></span>${l}<span class="n">${n}</span></button>`).join('')}
</div>
<div style="overflow-x:auto"><div style="min-width:560px">
<div class="thead" aria-hidden="true"><span>Severity</span><span>Check</span><span>Title</span><span>Page</span></div>
${list.map((x) => `<button type="button" class="frow${sel && x.id === sel.id ? ' is-sel' : ''}" aria-pressed="${!!(sel && x.id === sel.id)}" data-act="pick" data-v="${esc(x.id)}">
<span><span class="chip sev-${x.sev}">${SEVL[x.sev]}</span></span><span style="color:var(--muted)">${CHECKS[x.check]}</span><span class="trunc" style="font-weight:500">${esc(x.title)}</span><span class="mono trunc u" title="${esc(x.url)}">${esc(pathOf(x.url))}</span></button>`).join('')}
${running ? `<div class="frow stream" aria-live="polite"><span><span class="skel" style="width:64px"></span></span><span><span class="skel" style="width:70px"></span></span><span class="trunc" style="font-size:12px">Scanning ${esc((r.current || '').replace(/^https?:\/\/[^/]+/, '') || '/')} …</span><span><span class="skel" style="width:120px"></span></span></div>` : ''}
${!running && r.findings.length === 0 ? `<div style="padding:28px 14px;text-align:center;color:var(--muted);border-top:1px solid var(--border)">No findings. Every enabled check passed.</div>` : ''}
${r.findings.length > 0 && list.length === 0 ? `<div style="padding:28px 14px;text-align:center;color:var(--muted);border-top:1px solid var(--border)">No findings match these filters. <button type="button" class="btn btn-quiet" style="height:26px;color:var(--link)" data-act="clearFilters">Clear filters</button></div>` : ''}
</div></div>
</section>
<aside class="card" aria-label="Finding details" style="flex:1 1 340px;min-width:0;overflow:hidden;display:flex;flex-direction:column">${sel ? viewFinding(r, sel) : '<div style="padding:40px 20px;text-align:center;color:var(--muted)">Findings will appear here as pages are crawled. Select one to see its details.</div>'}</aside>
</div>`;
  return html + viewLog(r) + '</main>';
}

function viewFinding(r, f) {
  const href = /^https?:/.test(f.url) ? f.url : (r.url || '').replace(/\/$/, '') + f.url;
  let media = '';
  if (f.kind === 'diff') {
    media = `<div><div class="lbl" style="justify-content:space-between"><span>Visual diff · ${esc(f.viewport)}</span><span style="color:var(--faint)">Click to enlarge</span></div>
<button type="button" class="shot-btn" data-act="zoom" aria-label="Enlarge visual diff"><span class="trip">
<span class="trip-col"><span class="cap">Baseline</span><img class="shot" src="${runPath(r, f.baseline)}" alt="Baseline"></span>
<span class="trip-col"><span class="cap">Current</span><img class="shot" src="${runPath(r, f.shot)}" alt="Current"></span>
<span class="trip-col"><span class="cap" style="color:var(--crit)">Diff</span><img class="shot" src="${runPath(r, f.diff)}" alt="Changed pixels"></span>
</span></button></div>`;
  } else if (f.kind === 'shot' && f.shot) {
    media = `<div><div class="lbl" style="justify-content:space-between"><span>Screenshot</span><span style="color:var(--faint)">Click to enlarge</span></div>
<button type="button" class="shot-btn" data-act="zoom" aria-label="Enlarge screenshot"><img class="shot" src="${runPath(r, f.shot)}" alt="Screenshot of ${esc(f.title)}"></button></div>`;
  }
  return `<div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:9px">
<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap"><span class="chip sev-${f.sev}">${SEVL[f.sev]}</span><span class="tag">${CHECKS[f.check]}</span><span class="mono" style="margin-left:auto;color:var(--faint);font-size:11.5px">${esc(f.id)}</span></div>
<h2 style="margin:0;font-size:16px;font-weight:600;line-height:1.35">${esc(f.title)}</h2>
<a class="mono trunc" href="${esc(href)}" target="_blank" rel="noopener" style="font-size:12px;display:block">${esc(href)}</a>
</div>
<div style="padding:14px 16px;display:flex;flex-direction:column;gap:14px"><div><div class="lbl">Details</div><pre class="pre mono">${esc(f.details)}</pre></div>${media}</div>
<div style="margin-top:auto;padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;align-items:center">
${f.jira_key ? `<span style="display:inline-flex;align-items:center;gap:8px;height:32px;padding:0 12px;border-radius:7px;background:var(--pass-bg);color:var(--pass);font-weight:500">${svg(IC.check)}Created <span class="mono">${esc(f.jira_key)}</span></span>`
    : `<button type="button" class="btn btn-primary" data-act="createJira" data-v="${esc(f.id)}" ${S.run.jiraBusy || r.state === 'running' ? 'disabled' : ''}>${svg(IC.ticket)}Create Jira issue</button>`}
<button type="button" class="btn" data-act="copyFinding" data-v="${esc(f.id)}">Copy details</button>
<a class="btn btn-quiet btn-icon" href="${esc(href)}" target="_blank" rel="noopener" aria-label="Open page in browser" title="Open page in browser" style="margin-left:auto">${svg(IC.ext)}</a>
</div>`;
}

function viewLog(r) {
  if (!r.logs || !r.logs.length) return '';
  return `<section class="card" aria-label="Log" style="overflow:hidden">
<button type="button" class="disc" aria-expanded="${S.run.logOpen}" data-act="log">${svg(IC.term, 'ic', 'style="color:var(--muted)"')}<span style="font-weight:600">Log</span><span class="mono" style="color:var(--muted);font-size:12px">${r.logs.length} lines</span>${svg(IC.chev, 'ic chev', 'style="margin-left:auto"')}</button>
${S.run.logOpen ? `<div class="console" role="log" aria-label="Run log" data-keep="console" data-stick="bottom">${r.logs.map((l) => `<div><span class="t">${esc(l.t)}</span>  <span class="lv lv-${l.lv.toLowerCase()}">${l.lv}</span>${esc(l.msg)}</div>`).join('')}</div>` : ''}
</section>`;
}

function viewLightbox() {
  const R = S.run, r = R.cur;
  if (!R.zoom || !r) return '';
  const f = r.findings.find((x) => x.id === R.sel) || r.findings[0];
  if (!f || f.kind === 'none') return '';
  const img = f.kind === 'diff'
    ? `<div class="trip" style="gap:14px"><div class="trip-col"><span class="cap">Baseline</span><img class="shot" src="${runPath(r, f.baseline)}" alt="Baseline"></div><div class="trip-col"><span class="cap">Current · this run</span><img class="shot" src="${runPath(r, f.shot)}" alt="Current"></div><div class="trip-col"><span class="cap" style="color:var(--crit)">Diff · changed pixels</span><img class="shot" src="${runPath(r, f.diff)}" alt="Diff"></div></div>`
    : `<img class="shot" src="${runPath(r, f.shot)}" alt="Screenshot">`;
  return `<div class="lightbox" role="dialog" aria-modal="true" aria-label="Enlarged image" data-act="unzoomBg">
<div class="card" style="width:100%;max-width:1180px;padding:16px;display:flex;flex-direction:column;gap:12px">
<div style="display:flex;align-items:center;gap:10px"><span class="chip sev-${f.sev}">${SEVL[f.sev]}</span><strong class="trunc">${esc(f.title)}</strong><span class="mono trunc" style="color:var(--muted);font-size:12px">${esc(f.url)}</span>
<button type="button" class="btn btn-quiet btn-icon" style="margin-left:auto" aria-label="Close" data-act="unzoom">${svg(IC.close)}</button></div>${img}</div></div>`;
}

async function startRun() {
  const R = S.run, f = R.form;
  if (!f.url.trim() || R.starting) return;
  R.starting = true; R.err = ''; schedule();
  try {
    const run = await api('POST', '/api/runs', { ...f, url: f.url.trim(), max_pages: Number(f.max_pages) || 50, threshold: Number(f.threshold) || 0.5 });
    R.cur = run; R.sel = null; R.sev = 'all'; R.check = 'all'; R.q = '';
    history.replaceState(null, '', '#/run/' + run.id);
    S.routeArg = run.id;
  } catch (e) { R.err = e.message; }
  R.starting = false; schedule();
}

function formFromRun(r) {
  // Viewing a run shows the setup it ran with, so Retry and Run tests repeat it.
  const o = r.options || {};
  Object.assign(S.run.form, { url: o.url || r.url, ticket: o.ticket || '', checks: { ...o.checks }, viewports: { ...o.viewports },
    max_pages: o.max_pages, threshold: o.threshold, lighthouse: o.lighthouse, accept_baselines: o.accept_baselines, headed: o.headed, publish: o.publish });
  store.set('runForm2', S.run.form);
}

async function loadRun(id) {
  try { S.run.cur = await api('GET', '/api/runs/' + encodeURIComponent(id)); S.run.err = ''; formFromRun(S.run.cur); } catch (e) { S.run.err = e.message; S.run.cur = null; }
  schedule();
}

/* ================================================================== HISTORY */
const hostOf = (u) => { try { return new URL(/^https?:/.test(u) ? u : 'https://' + u).host; } catch (e) { return u; } };
const fmtDT = (ts) => { const d = new Date(ts * 1000); return d.toLocaleString('en-US', { month: 'short', day: '2-digit' }) + ' · ' + d.toTimeString().slice(0, 5); };

function viewHistory() {
  const H = S.hist;
  if (!H.runs) return `<main class="main"><h1 style="margin:0;font-size:18px;font-weight:600">History</h1><div class="notice">Loading runs…</div></main>`;
  const runs = H.runs.filter((r) => r.state !== 'running');
  const bySite = {};
  runs.forEach((r) => { const h = hostOf(r.url); (bySite[h] = bySite[h] || []).push(r); });
  const sites = Object.keys(bySite).sort((a, b) => bySite[b].length - bySite[a].length);
  if (!H.site || !bySite[H.site]) H.site = sites[0] || null;
  let chart = '<div class="notice">No finished runs yet. Start one from the Run screen.</div>';
  if (H.site) {
    const data = bySite[H.site].slice(0, 10).reverse();
    const tot = (r) => r.counts.critical + r.counts.major + r.counts.minor;
    const max = Math.max(1, ...data.map(tot));
    const px = (v) => (v === 0 ? '0px' : Math.max(2, Math.round((v / max) * 100)) + 'px');
    const label = (r) => new Date(r.started * 1000).toLocaleDateString('en-US', { month: 'short', day: '2-digit' });
    const last = tot(data[data.length - 1]), first = tot(data[0]), diff = last - first;
    chart = `<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:stretch">
<div style="flex:999 1 420px;min-width:0">
<div class="bars" role="img" aria-label="Stacked bars of critical, major and minor issues for the last ${data.length} runs of ${esc(H.site)}. ${data.map((r) => label(r) + ': ' + r.counts.critical + ' critical, ' + r.counts.major + ' major, ' + r.counts.minor + ' minor').join('; ')}">
<div class="gl" style="bottom:50%"></div>
${data.map((r) => `<div class="bcol" title="${label(r)}: ${r.counts.critical} critical, ${r.counts.major} major, ${r.counts.minor} minor"><span class="mono" style="font-size:10.5px;color:var(--muted)">${tot(r)}</span><div class="stack"><span class="s-crit" style="height:${px(r.counts.critical)}"></span><span class="s-major" style="height:${px(r.counts.major)}"></span><span class="s-minor" style="height:${px(r.counts.minor)}"></span></div></div>`).join('')}
</div><div class="xl" aria-hidden="true">${data.map((r) => `<span>${label(r)}</span>`).join('')}</div></div>
<div style="flex:1 1 200px;display:flex;flex-direction:column;gap:12px;padding-left:20px;border-left:1px solid var(--border)">
<div><div class="lbl">Latest run</div><div style="display:flex;align-items:baseline;gap:8px"><span style="font-size:24px;font-weight:600;font-variant-numeric:tabular-nums">${last}</span><span style="color:var(--muted)">issues</span></div>
<div class="mono ${diff <= 0 ? 'ok' : 'c-crit'}" style="font-size:12px">${diff <= 0 ? '▼ ' + Math.abs(diff) : '▲ ' + diff} since ${label(data[0])}</div></div>
<div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted)">
<span style="display:flex;align-items:center;gap:8px"><span class="dot sq" style="background:var(--crit-dot)"></span>Critical</span>
<span style="display:flex;align-items:center;gap:8px"><span class="dot sq" style="background:var(--major-dot)"></span>Major</span>
<span style="display:flex;align-items:center;gap:8px"><span class="dot sq" style="background:var(--minor-dot)"></span>Minor</span>
</div></div></div>`;
  }
  const q = H.q.trim().toLowerCase();
  const rows = runs.filter((r) => {
    const failed = r.counts.critical > 0 || r.counts.major > 0;
    return (H.status === 'all' || (H.status === 'failed') === failed) && (!q || r.url.toLowerCase().includes(q));
  });
  const n = (v, c) => `<span class="${v ? c : 'zero'}">${v}</span>`;
  return `<main class="main">
<header style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-height:36px">
<h1 style="margin:0;font-size:18px;font-weight:600;letter-spacing:-.01em">History</h1><span style="color:var(--muted)">${runs.length} runs · ${sites.length} site${sites.length === 1 ? '' : 's'}</span>
<a class="btn btn-primary" href="#/run" data-act="newRun" style="margin-left:auto">${svg(IC.play)}New run</a>
</header>
<section class="card" aria-label="Issues over time" style="padding:16px;display:flex;flex-direction:column;gap:14px">
<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
<div><h2 style="margin:0;font-size:13px;font-weight:600">Issues per run</h2><div style="color:var(--muted);font-size:12px">${H.site ? `Last ${Math.min(10, bySite[H.site].length)} runs of <span class="mono">${esc(H.site)}</span>` : 'No data'}</div></div>
${sites.length ? `<div class="seg" role="group" aria-label="Site" style="margin-left:auto;flex-wrap:wrap">${sites.slice(0, 5).map((s) => `<button type="button" class="mono" aria-pressed="${s === H.site}" data-act="site" data-v="${esc(s)}">${esc(s)}</button>`).join('')}</div>` : ''}
</div>${chart}</section>
<section class="card" aria-label="Past runs" style="overflow:hidden">
<div style="padding:12px 14px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
<label class="search" style="flex:0 1 280px">${svg(IC.search, 'ic', 'style="width:14px;height:14px"')}<span class="sr-only">Search by URL</span><input id="hist-q" type="search" placeholder="Search by URL" value="${esc(H.q)}" data-in="histQ"></label>
<div class="seg" role="group" aria-label="Status">${[['all', 'All'], ['passed', 'Passed'], ['failed', 'Failed']].map(([k, l]) => `<button type="button" aria-pressed="${H.status === k}" data-act="histStatus" data-v="${k}">${l}</button>`).join('')}</div>
<span class="mono" style="margin-left:auto;color:var(--muted);font-size:12px">${rows.length} shown</span>
</div>
<div style="overflow-x:auto;border-top:1px solid var(--border)"><table class="tbl">
<thead><tr><th scope="col">Date / time</th><th scope="col">URL</th><th scope="col">Result</th><th scope="col" class="n"><span class="hcnt"><span class="dot sq" style="background:var(--crit-dot)"></span>Crit</span></th><th scope="col" class="n"><span class="hcnt"><span class="dot sq" style="background:var(--major-dot)"></span>Major</span></th><th scope="col" class="n"><span class="hcnt"><span class="dot sq" style="background:var(--minor-dot)"></span>Minor</span></th><th scope="col" class="n">Duration</th><th scope="col" style="text-align:right">Actions</th></tr></thead>
<tbody>${rows.map((r) => {
    const failed = r.counts.critical > 0 || r.counts.major > 0;
    const label = r.state === 'error' ? 'Error' : r.state === 'stopped' ? 'Stopped' : failed ? 'Failed' : 'Passed';
    const cls = r.state === 'error' ? 'st-error' : r.state === 'stopped' ? 'st-stopped' : failed ? 'st-failed' : 'st-passed';
    const pub = r.published || H.pub[r.id] === 'done';
    return `<tr><td class="mono" style="color:var(--muted)">${fmtDT(r.started)}</td>
<td><a class="mono" href="#/run/${encodeURIComponent(r.id)}">${esc(r.url)}</a>${r.ticket ? ` <span class="tag mono" style="margin-left:6px">${esc(r.ticket)}</span>` : ''}</td>
<td><span class="status sm ${cls}">${label}</span></td>
<td class="n">${n(r.counts.critical, 'c-crit')}</td><td class="n">${n(r.counts.major, 'c-major')}</td><td class="n">${n(r.counts.minor, 'c-minor')}</td>
<td class="n" style="color:var(--muted)">${fmtDur(r.duration)}</td>
<td style="text-align:right;width:132px">
<a class="btn btn-quiet btn-icon" href="/runs/${encodeURIComponent(r.id)}/report.html" target="_blank" rel="noopener" aria-label="Open report" title="Open report">${svg(IC.doc)}</a>
<button type="button" class="btn btn-quiet btn-icon" aria-label="Open folder" title="Open folder" data-act="folder" data-v="${esc(r.id)}">${svg(IC.folder)}</button>
<button type="button" class="btn btn-quiet btn-icon${pub ? ' ok' : ''}" aria-label="${pub ? 'Published to integrations' : 'Publish to integrations'}" title="${pub ? 'Published to integrations' : 'Publish to integrations'}" data-act="publish" data-v="${esc(r.id)}" ${H.pub[r.id] === 'busy' ? 'disabled' : ''}>${svg(H.pub[r.id] === 'busy' ? IC.spin : pub ? IC.check : IC.send, H.pub[r.id] === 'busy' ? 'ic spin' : 'ic')}</button>
</td></tr>`;
  }).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--muted)">No runs match.</td></tr>'}</tbody></table></div>
</section></main>`;
}

async function loadHistory() {
  try { S.hist.runs = await api('GET', '/api/runs'); } catch (e) { toast('Could not load runs: ' + e.message); S.hist.runs = []; }
  schedule();
}

/* ================================================================== INTEGRATIONS */
function integStatus(c) {
  const I = S.integ;
  if (c.key === 'workflow') return I.vals.workflow.demo ? ['Demo data', 'd d-setup', 'setup'] : ['Live', 'd d-ok', 'ok'];
  if (!I.enabled[c.key]) return ['Off', 'd d-off', 'off'];
  const res = I.results[c.key];
  const missing = (c.required || []).some((k) => !String(I.vals[c.key][k] || '').trim());
  if (res) return res.ok ? ['Connected', 'd d-ok', 'ok'] : ['Error', 'd d-err', 'err'];
  if (missing) return ['Needs setup', 'd d-setup', 'setup'];
  return ['Not tested', 'd d-setup', 'setup'];
}

/* ------------------------------------------------------------------ Jira: paste a link, sign in with Atlassian */
// Mirrors parse_jira_link() in integrations/atlassian_mcp.py, for the instant preview. The server parses again.
function parseJiraLink(text) {
  let s = (text || '').trim().replace(/^[<"']+|[>"']+$/g, '');
  if (!s) return null;
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  let u;
  try { u = new URL(s); } catch (e) { return { err: "That doesn't look like a Jira link" }; }
  const host = u.hostname.toLowerCase();
  if (!host.includes('.') || /\s/.test(text.trim())) return { err: "That doesn't look like a Jira link" };
  if (host.endsWith('atlassian.com')) return { err: 'Use the link of your Jira site (…atlassian.net), not an atlassian.com page' };
  const q = u.searchParams;
  let m = u.pathname.match(/\/projects\/([A-Za-z][A-Za-z0-9_]*)/);
  let project = m ? m[1].toUpperCase() : (q.get('projectKey') || '').toUpperCase();
  m = u.pathname.match(/\/boards?\/(\d+)/);
  const board = m ? m[1] : (/^\d+$/.test(q.get('rapidView') || '') ? q.get('rapidView') : '');
  m = u.pathname.match(/\/browse\/([A-Za-z][A-Za-z0-9_]*-\d+)/);
  let issue = (m ? m[1] : q.get('selectedIssue') || '').toUpperCase();
  if (!/^[A-Z][A-Z0-9_]*-\d+$/.test(issue)) issue = '';
  if (issue && !project) project = issue.replace(/-\d+$/, '');
  return { site: host, project, board, issue };
}

function viewJiraConnect() {
  const J = S.jira, st = J.st;
  const head = (right) => `<div style="display:flex;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border)">
<span class="mono-tile" style="background:#2F64D6" aria-hidden="true">J</span>
<div style="min-width:0;flex:1"><h2 id="int-jira-connect" style="margin:0;font-size:14px;font-weight:600">Jira</h2><div style="color:var(--muted);font-size:12px">The board you test from: tickets, comments and moves, with your own Atlassian access</div></div>${right}</div>`;
  const err = J.err ? `<div class="callout c-err" role="alert">${svg(IC.err, 'ic', 'style="flex:none;margin-top:1px"')}<span>${esc(J.err)}</span></div>` : '';
  if (!st) return `<section class="card jc" aria-labelledby="int-jira-connect">${head('')}<div class="jc-body"><div class="notice">Loading…</div></div></section>`;
  const c = st.connection;
  if (!st.connected || !c || J.changing) {
    const p = parseJiraLink(J.link);
    const chip = (label, v) => `<span class="jc-chip${v ? '' : ' is-empty'}"><span>${label}</span><b class="mono">${esc(v || 'from the board')}</b></span>`;
    const preview = !p ? `<span style="color:var(--faint)">Example: https://your-site.atlassian.net/jira/software/projects/KEY/boards/1</span>`
      : p.err ? `<span class="c-crit" style="font-size:12px">${esc(p.err)}</span>`
      : `${chip('Site', p.site)}${chip('Project', p.project)}${chip('Board', p.board)}${p.issue ? chip('Ticket', p.issue) : ''}`;
    const ready = p && !p.err;
    return `<section class="card jc" aria-labelledby="int-jira-connect">${head(c ? `<button type="button" class="btn btn-quiet btn-sm" data-act="jiraCancel">Cancel</button>` : '<span class="conn"><span class="d d-off"></span>Not connected</span>')}
<div class="jc-body">
<label class="lbl" for="jira-link" style="margin:0">Paste the link of your Jira board</label>
<div class="jc-row"><input id="jira-link" class="inp mono" type="text" inputmode="url" placeholder="https://your-site.atlassian.net/jira/software/projects/KEY/boards/1" value="${esc(J.link)}" data-in="jiraLink" spellcheck="false" autocomplete="off">
<button type="button" class="btn btn-primary" data-act="jiraConnect" ${ready && !J.busy ? '' : 'disabled'}>${J.busy === 'connect' ? svg(IC.spin, 'ic spin') + 'Opening Atlassian…' : 'Sign in with Atlassian' + svg(IC.arrow, 'ic ic-s')}</button></div>
<div class="jc-chips" aria-live="polite">${preview}</div>
${err}
<p class="jc-foot">You approve access on Atlassian's own page, then come straight back here. No API token to copy. It uses Atlassian's MCP server, so the app sees only what your Jira account can see. The first time on a site, a site admin approves the app once.</p>
</div></section>`;
  }
  const col = J.col || st.column;
  const byStatus = c.columns_from === 'statuses';
  const live = !st.demo && st.column && st.column === col;
  const colChips = c.columns.map((x) => `<button type="button" class="jc-col" role="radio" aria-checked="${x.name === col}" data-act="jiraCol" data-v="${esc(x.name)}"><span>${esc(x.name)}</span>${x.count == null ? '' : `<span class="seg-n">${x.count}</span>`}</button>`).join('');
  const comps = c.components && c.components.length
    ? `Components in ${esc(c.project.key)}: <span class="mono">${esc(c.components.join(', '))}</span>. They set each ticket's FE / BE type (names are set on the Testing board card).`
    : `${esc(c.project.key)} has no components yet, so tickets show as <b>No type</b>. Add Frontend / Backend components in Jira to get FE, BE and FE+BE.`;
  return `<section class="card jc" aria-labelledby="int-jira-connect">${head(`<span class="conn"><span class="d ${st.signedIn ? 'd-ok' : 'd-err'}"></span>${st.signedIn ? 'Connected' : 'Signed out'}</span>`)}
<div class="jc-body">
<dl class="jc-facts">
<div><dt>Site</dt><dd class="mono"><a href="${esc(c.base_url)}" target="_blank" rel="noopener">${esc(c.site)}</a></dd></div>
<div><dt>Signed in as</dt><dd>${esc(c.user.name || c.user.email || c.user.account_id || 'your Atlassian account')}</dd></div>
<div><dt>Project</dt><dd>${esc(c.project.name)} <span class="mono" style="color:var(--muted)">${esc(c.project.key)}</span></dd></div>
<div><dt>Board</dt><dd>${esc(c.board.name)}${c.board.id ? ` <span class="mono" style="color:var(--muted)">#${esc(c.board.id)}</span>` : ''}</dd></div>
</dl>
${st.signedIn ? '' : `<div class="callout c-err" role="alert">${svg(IC.err, 'ic', 'style="flex:none;margin-top:1px"')}<span>Your Atlassian sign-in has ended. Sign in again to keep the board in sync.</span><button type="button" class="btn btn-sm" style="margin-left:auto" data-act="jiraReconnect">Sign in again</button></div>`}
<div><div class="lbl" id="jc-col-l">Which ${byStatus ? 'status' : 'column'} holds the tickets ready for QA?</div>
${c.columns.length ? `<div class="jc-cols" role="radiogroup" aria-labelledby="jc-col-l">${colChips}</div>` : `<div class="notice">${esc(c.project.key)} has no tickets yet, so its statuses can't be read. Create a ticket, then press Refresh.</div>`}
${byStatus && c.columns.length ? `<p class="jc-foot" style="margin-top:8px">Your Atlassian access doesn't include board settings, so these are the project's statuses. On a simple board each status is a column.</p>` : ''}</div>
<div class="jc-row" style="align-items:center">
${live ? `<span class="tres tres-ok">${svg(IC.check, 'ic', 'style="width:14px;height:14px"')}The Testing board shows ${esc(c.board.name)} · ${esc(col)}</span><a class="btn btn-sm" href="#/board" style="margin-left:4px">Open board${svg(IC.arrow, 'ic ic-s')}</a>`
    : `<button type="button" class="btn btn-primary" data-act="jiraUse" ${col && !J.busy ? '' : 'disabled'}>${J.busy === 'use' ? svg(IC.spin, 'ic spin') : ''}${col ? `Show ${esc(col)} on the Testing board` : `Pick a ${byStatus ? 'status' : 'column'} first`}</button>`}
</div>
${err}
<p class="jc-foot">${comps}</p>
<div class="jc-actions"><button type="button" class="btn btn-quiet btn-sm" data-act="jiraRefresh" ${J.busy ? 'disabled' : ''}>${svg(J.busy === 'refresh' ? IC.spin : IC.sync, J.busy === 'refresh' ? 'ic spin' : 'ic')}Refresh columns</button>
<button type="button" class="btn btn-quiet btn-sm" data-act="jiraChange">Use a different board</button>
<button type="button" class="btn btn-quiet btn-sm" style="margin-left:auto" data-act="jiraDisconnect" ${J.busy ? 'disabled' : ''}>Disconnect</button></div>
</div></section>`;
}

async function loadJira() {
  try { S.jira.st = await api('GET', '/api/jira'); S.jira.col = ''; } catch (e) { S.jira.err = 'Could not read the Jira connection: ' + e.message; }
  if (/[?&]jira=connected/.test(location.hash)) { history.replaceState(null, '', '#/integrations'); if (S.jira.st && S.jira.st.connected) toast(`Jira connected · ${S.jira.st.connection.board.name}. Pick the QA column.`); }
  schedule();
}

async function jiraConnect() {
  const J = S.jira; J.busy = 'connect'; J.err = ''; schedule();
  try {
    const r = await api('POST', '/api/jira/connect', { link: J.link });
    if (r.authorize_url) { location.href = r.authorize_url; return; } // Atlassian sends the browser back to /api/jira/oauth/callback
    J.changing = false; await loadJira(); toast(`Jira connected · ${r.connected.board.name}`);
  } catch (e) { J.err = e.message; }
  J.busy = ''; schedule();
}

function viewIntegrations() {
  const I = S.integ;
  if (!I.cards) return `<main class="main"><h1 style="margin:0;font-size:18px;font-weight:600">Integrations</h1><div class="notice">Loading…</div></main>`;
  const sum = { ok: 0, err: 0, off: 0 };
  const cards = I.cards.map((c) => {
    const [label, dot, kind] = integStatus(c);
    if (kind in sum) sum[kind] += 1;
    const on = c.key === 'workflow' || !!I.enabled[c.key];
    const res = I.results[c.key];
    const fields = c.fields.map((f) => {
      const id = `f-${c.key}-${f.k}`, v = I.vals[c.key][f.k];
      const wrap = f.full ? 'full' : '';
      if (f.check) return `<div class="${wrap}"><label class="cb" style="height:32px"><input type="checkbox" ${v ? 'checked' : ''} data-in="integCheck" data-key="${c.key}" data-v="${f.k}">${esc(f.label)}</label></div>`;
      if (f.options) return `<div class="${wrap}"><label class="lbl" style="display:block;margin:0 0 6px" for="${id}">${esc(f.label)}</label><select id="${id}" class="inp" data-in="integVal" data-key="${c.key}" data-v="${f.k}">${f.options.map((o) => `<option value="${esc(o.v)}" ${o.v === v ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></div>`;
      const revealed = !!I.reveal[c.key + '.' + f.k];
      const mono = f.secret || /url/i.test(f.label) || ['bucket', 'prefix', 'id'].includes(f.k);
      return `<div class="${wrap}"><label class="lbl" style="display:block;margin:0 0 6px" for="${id}">${esc(f.label)}</label><div class="${f.secret ? 'secret' : ''}">
<input id="${id}" class="inp${mono ? ' mono' : ''}" type="${f.secret && !revealed ? 'password' : 'text'}" value="${esc(v)}" placeholder="${esc(f.ph || '')}" data-in="integVal" data-key="${c.key}" data-v="${f.k}" spellcheck="false" autocomplete="off">
${f.secret ? `<button type="button" class="reveal" aria-label="${revealed ? 'Hide' : 'Show'} ${esc(f.label)}" aria-pressed="${revealed}" data-act="reveal" data-key="${c.key}" data-v="${f.k}">${svg(revealed ? IC.eyeoff : IC.eye)}</button>` : ''}
</div></div>`;
    }).join('');
    return `<section class="card" aria-labelledby="int-${c.key}" style="display:flex;flex-direction:column;overflow:hidden">
<div style="display:flex;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border)">
<span class="mono-tile" style="background:${c.tint}" aria-hidden="true">${esc(c.mono)}</span>
<div style="min-width:0;flex:1"><h2 id="int-${c.key}" style="margin:0;font-size:14px;font-weight:600">${esc(c.name)}</h2><div style="color:var(--muted);font-size:12px">${esc(c.desc)}</div></div>
<span class="conn"><span class="${dot}"></span>${label}</span>
${c.key === 'workflow' ? '' : `<button type="button" class="swbtn" role="switch" aria-checked="${on}" aria-label="Enable ${esc(c.name)}" data-act="integToggle" data-key="${c.key}"><span class="swi"></span></button>`}
</div>
<div class="fields${on ? '' : ' off'}">${fields}</div>
<div style="margin-top:auto;display:flex;align-items:center;gap:8px;padding:12px 16px;border-top:1px solid var(--border);background:var(--raised)">
<button type="button" class="btn" data-act="integTest" data-key="${c.key}" ${I.testing[c.key] ? 'disabled' : ''}>${svg(I.testing[c.key] ? IC.spin : IC.bolt, I.testing[c.key] ? 'ic spin' : 'ic')}Test connection</button>
${res ? `<div class="tres ${res.ok ? 'tres-ok' : 'tres-err'}" role="status" style="flex:0 1 auto">${svg(res.ok ? IC.check : IC.err, 'ic', 'style="width:14px;height:14px"')}<span title="${esc(res.text)}">${esc(res.text)}</span></div>` : ''}
<button type="button" class="btn ${I.saved[c.key] ? 'btn-done' : 'btn-primary'}" style="margin-left:auto" data-act="integSave" data-key="${c.key}">${I.saved[c.key] ? 'Saved' : 'Save'}</button>
</div></section>`;
  }).join('');
  const js = S.jira.st;
  if (js && js.connected) sum[js.signedIn ? 'ok' : 'err'] += 1;
  return `<main class="main">
<header style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-height:36px">
<div><h1 style="margin:0;font-size:18px;font-weight:600;letter-spacing:-.01em">Integrations</h1><p style="margin:2px 0 0;color:var(--muted)">Where results go after a run with "Publish to integrations" on. Jira and TestRail also drive the board in live mode.</p></div>
<div style="margin-left:auto;display:flex;gap:16px;flex-wrap:wrap"><span class="conn"><span class="d d-ok"></span>${sum.ok} connected</span><span class="conn"><span class="d d-err"></span>${sum.err} error</span><span class="conn"><span class="d d-off"></span>${sum.off} off</span></div>
</header>
${I.mode !== 'live' ? `<div class="notice">${svg(IC.info)}Demo data is on for the Testing board: it uses sample tickets and simulated Jira and TestRail. Connect Jira below and pick a column to test your real tickets. Runs and publishing always use the real settings below.</div>` : ''}
${viewJiraConnect()}
<div class="icard-grid">${cards}</div></main>`;
}

async function loadIntegrations() {
  try {
    const d = await api('GET', '/api/integrations');
    const I = S.integ;
    I.cards = d.cards; I.mode = d.mode;
    d.cards.forEach((c) => {
      I.vals[c.key] = { ...c.values }; I.enabled[c.key] = c.enabled;
      if (c.result) I.results[c.key] = c.result;
    });
  } catch (e) { toast('Could not load integrations: ' + e.message); }
  schedule();
}

async function saveIntegration(key, quiet) {
  const I = S.integ;
  try {
    await api('PUT', `/api/integrations/${key}`, { values: I.vals[key], enabled: key === 'workflow' ? true : !!I.enabled[key] });
    if (!quiet) { I.saved[key] = true; }
    if (key === 'workflow') { I.mode = I.vals.workflow.demo ? 'mock' : 'live'; S.board.data = null; S.board.sel = null; loadBoard(); }
  } catch (e) { toast('Save failed: ' + e.message); }
  schedule();
}

/* ================================================================== events */
const ACTS = {
  theme: (el) => { S.theme = el.dataset.v; store.set('theme', S.theme); },
  dismissToast: () => { S.toast = ''; },
  // board
  sync: async () => {
    S.board.syncing = true; schedule();
    try {
      const r = await api('POST', '/api/sync');
      S.board.data.lastSync = r.lastSync;
      toast(r.new.length ? `Pulled ${r.new.join(', ')} from Jira ${S.board.data.config.column}` : `No new tickets in ${S.board.data.config.column}`);
    } catch (e) { toast(e.message); }
    S.board.syncing = false;
  },
  you: (el) => { S.board.you = el.dataset.v === '1'; },
  ttype: (el) => { S.board.type = el.dataset.v; store.set('boardType', S.board.type); },
  open: (el) => { S.board.sel = el.dataset.key; S.board.actErr = ''; },
  close: () => { S.board.sel = null; S.board.actErr = ''; },
  primary: (el) => primaryAction(el.dataset.key),
  retry: async (el) => {
    const t = S.board.data.tickets.find((x) => x.key === el.dataset.key);
    try { await api('POST', `/api/tickets/${encodeURIComponent(t.key)}/action`, { action: 'retry', stage: t.stage, sub: t.sub }); } catch (e) { S.board.actErr = e.message; }
  },
  openTicket: (el) => { S.board.sel = el.dataset.key; },
  // run
  ck: (el) => { const f = S.run.form; f.checks[el.dataset.v] = !f.checks[el.dataset.v]; store.set('runForm2', f); },
  vp: (el) => { const f = S.run.form; f.viewports[el.dataset.v] = !f.viewports[el.dataset.v]; store.set('runForm2', f); },
  opts: () => { S.run.optsOpen = !S.run.optsOpen; },
  log: () => { S.run.logOpen = !S.run.logOpen; },
  openLog: () => { S.run.logOpen = true; },
  startRun: () => startRun(),
  stopRun: async () => { try { await api('POST', `/api/runs/${encodeURIComponent(S.run.cur.id)}/stop`); } catch (e) { toast(e.message); } },
  newRun: () => { S.run.cur = null; S.run.err = ''; location.hash = '#/run'; },
  sev: (el) => { S.run.sev = el.dataset.v; },
  pick: (el) => { S.run.sel = el.dataset.v; },
  clearFilters: () => { S.run.sev = 'all'; S.run.check = 'all'; S.run.q = ''; },
  zoom: () => { S.run.zoom = true; },
  unzoom: () => { S.run.zoom = false; },
  unzoomBg: (el, ev) => { if (ev.target === el) S.run.zoom = false; },
  createJira: async (el) => {
    const R = S.run; R.jiraBusy = true; schedule();
    try {
      const r = await api('POST', `/api/runs/${encodeURIComponent(R.cur.id)}/findings/${encodeURIComponent(el.dataset.v)}/jira`);
      const f = R.cur.findings.find((x) => x.id === el.dataset.v); if (f) f.jira_key = r.key;
      toast(`Created ${r.key}`);
    } catch (e) { toast(e.message); }
    R.jiraBusy = false;
  },
  copyFinding: async (el) => {
    const f = S.run.cur.findings.find((x) => x.id === el.dataset.v);
    try { await navigator.clipboard.writeText(`[${SEVL[f.sev]}] ${f.title}\n${/^https?:/.test(f.url) ? f.url : S.run.cur.url.replace(/\/$/, '') + f.url}\n\n${f.details}`); toast('Details copied'); } catch (e) { toast('Copy failed'); }
  },
  // history
  site: (el) => { S.hist.site = el.dataset.v; },
  histStatus: (el) => { S.hist.status = el.dataset.v; },
  folder: async (el) => { try { const r = await api('POST', `/api/runs/${encodeURIComponent(el.dataset.v)}/open-folder`); toast('Opened ' + r.path); } catch (e) { toast(e.message); } },
  publish: async (el) => {
    const id = el.dataset.v; S.hist.pub[id] = 'busy'; schedule();
    try {
      const r = await api('POST', `/api/runs/${encodeURIComponent(id)}/publish`);
      const parts = Object.entries(r.result);
      S.hist.pub[id] = parts.length && parts.some(([, v]) => !v.startsWith('error')) ? 'done' : '';
      toast(parts.length ? parts.map(([k, v]) => `${k}: ${v}`).join(' · ') : 'No integration is enabled and set up');
    } catch (e) { S.hist.pub[id] = ''; toast(e.message); }
  },
  // jira connect
  jiraConnect: () => jiraConnect(),
  jiraReconnect: () => {
    const c = S.jira.st.connection;
    S.jira.link = `${c.base_url}/jira/software/projects/${c.project.key}/boards/${c.board.id}`;
    jiraConnect();
  },
  jiraCol: (el) => { S.jira.col = el.dataset.v; },
  jiraUse: async () => {
    const J = S.jira; J.busy = 'use'; J.err = ''; schedule();
    try {
      J.st = await api('POST', '/api/jira/column', { column: J.col || J.st.column, use_on_board: true }); J.col = '';
      S.board.data = null; S.board.sel = null; loadBoard(); S.integ.cards = null; loadIntegrations();
      toast(`The Testing board now shows ${J.st.connection.board.name} · ${J.st.column}. Press Sync now on the board to pull tickets.`);
    } catch (e) { J.err = e.message; }
    J.busy = '';
  },
  jiraRefresh: async () => {
    const J = S.jira; J.busy = 'refresh'; J.err = ''; schedule();
    try { J.st = await api('POST', '/api/jira/refresh'); } catch (e) { J.err = e.message; if (e.status === 401) await loadJira(); }
    J.busy = '';
  },
  jiraChange: () => { S.jira.changing = true; S.jira.err = ''; S.jira.link = ''; },
  jiraCancel: () => { S.jira.changing = false; S.jira.err = ''; },
  jiraDisconnect: async () => {
    const J = S.jira; J.busy = 'disconnect'; schedule();
    try { J.st = await api('POST', '/api/jira/disconnect'); J.link = ''; S.board.data = null; loadBoard(); S.integ.cards = null; loadIntegrations(); toast('Jira disconnected. The board shows demo tickets again.'); } catch (e) { J.err = e.message; }
    J.busy = '';
  },
  // integrations
  reveal: (el) => { const k = el.dataset.key + '.' + el.dataset.v; S.integ.reveal[k] = !S.integ.reveal[k]; },
  integToggle: (el) => { const k = el.dataset.key; S.integ.enabled[k] = !S.integ.enabled[k]; saveIntegration(k, true); },
  integSave: (el) => saveIntegration(el.dataset.key),
  integTest: async (el) => {
    const I = S.integ, k = el.dataset.key; I.testing[k] = true; schedule();
    try { I.results[k] = await api('POST', `/api/integrations/${k}/test`, I.vals[k]); } catch (e) { I.results[k] = { ok: false, text: e.message }; }
    I.testing[k] = false;
  },
};

const INPUTS = {
  boardQ: (el) => { S.board.q = el.value; },
  env: (el) => { S.board.env[el.dataset.key] = el.value; },
  comment: (el) => { S.board.comment[el.dataset.key] = el.value; saveDraft(el.dataset.key, { comment: el.value }); },
  target: (el) => { saveDraft(el.dataset.key, { target: el.value.trim() }); },
  targetSel: (el) => { const t = S.board.data.tickets.find((x) => x.key === el.dataset.key); t.target = el.value; saveDraft(el.dataset.key, { target: el.value }); },
  runUrl: (el) => { S.run.form.url = el.value; store.set('runForm2', S.run.form); },
  runMax: (el) => { S.run.form.max_pages = el.value; store.set('runForm2', S.run.form); },
  runThr: (el) => { S.run.form.threshold = el.value; store.set('runForm2', S.run.form); },
  runTicket: (el) => { S.run.form.ticket = el.value.trim(); store.set('runForm2', S.run.form); },
  runOpt: (el) => { S.run.form[el.dataset.v] = el.checked; store.set('runForm2', S.run.form); },
  runQ: (el) => { S.run.q = el.value; },
  runCheck: (el) => { S.run.check = el.value; },
  histQ: (el) => { S.hist.q = el.value; },
  jiraLink: (el) => { S.jira.link = el.value; S.jira.err = ''; },
  integVal: (el) => { S.integ.vals[el.dataset.key][el.dataset.v] = el.value; S.integ.saved[el.dataset.key] = false; },
  integCheck: (el) => { S.integ.vals[el.dataset.key][el.dataset.v] = el.checked; S.integ.saved[el.dataset.key] = false; },
};

$app.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el || el.disabled) return;
  const fn = ACTS[el.dataset.act];
  if (!fn) return;
  if (el.tagName === 'BUTTON') ev.preventDefault();
  await fn(el, ev);
  schedule();
});
const onInput = (ev) => {
  const el = ev.target.closest('[data-in]');
  if (!el) return;
  INPUTS[el.dataset.in](el);
  // text fields re-render without stealing focus; selects and checkboxes re-render right away
  schedule();
};
$app.addEventListener('input', onInput);
$app.addEventListener('change', (ev) => { if (ev.target.matches('select, input[type=checkbox]')) onInput(ev); });

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter' && ev.target && ev.target.id === 'jira-link') { ev.preventDefault(); const p = parseJiraLink(S.jira.link); if (p && !p.err && !S.jira.busy) jiraConnect(); return; }
  const mod = ev.metaKey || ev.ctrlKey;
  if (mod && ['1', '2', '3', '4'].includes(ev.key)) { ev.preventDefault(); location.hash = '#/' + ROUTES[+ev.key - 1]; }
  if (mod && ev.key === 'Enter' && S.route === 'run' && !(S.run.cur && S.run.cur.state === 'running')) { ev.preventDefault(); startRun(); }
  if (ev.key === 'Escape') {
    if (S.run.zoom) S.run.zoom = false; else if (S.board.sel) { S.board.sel = null; }
    schedule();
  }
});

/* ------------------------------------------------------------------ routing */
function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, query] = h.split('?');
  const [name, arg] = path.split('/');
  S.route = ROUTES.includes(name) ? name : 'board';
  S.routeArg = arg || '';
  if (S.route === 'board' && !S.board.data) loadBoard();
  if (S.route === 'run') {
    if (S.routeArg && (!S.run.cur || S.run.cur.id !== S.routeArg)) loadRun(S.routeArg);
    if (query) {
      const p = new URLSearchParams(query);
      if (p.get('url')) S.run.form.url = p.get('url');
      if (p.has('ticket')) S.run.form.ticket = p.get('ticket') || '';
      store.set('runForm2', S.run.form);
      if (!S.routeArg) S.run.cur = null;
    }
  }
  if (S.route === 'history') loadHistory();
  if (S.route === 'integrations' && !S.integ.cards) loadIntegrations();
  if (S.route === 'integrations') loadJira();
  schedule();
}
window.addEventListener('hashchange', route);

// Tick once a second for the elapsed timer and "synced N min ago".
setInterval(() => {
  if ((S.route === 'run' && S.run.cur && S.run.cur.state === 'running') || S.route === 'board') {
    const a = document.activeElement;
    if (!(a && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && a.type !== 'checkbox')))) schedule();
  }
}, 1000);

loadBoard();
connect();
route();
