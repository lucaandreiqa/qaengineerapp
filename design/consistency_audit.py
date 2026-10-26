"""Layout consistency check: on each screen, report siblings in one row with different heights (lane headers,
cards), side-by-side controls of different heights, and same-class blocks across a row that differ.

Run the app, then: python3 design/consistency_audit.py [routes...]   (QA_URL=http://localhost:8765 by default)
Findings that are by design (cards with more text, a row button next to a switch) can be ignored.
"""
import os, sys, json
from playwright.sync_api import sync_playwright
U=os.environ.get("QA_URL", "http://localhost:8765")
JS = r"""
() => {
  const out = [];
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = (e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '');
  // 1. siblings with the same class sitting in one row, different heights
  for (const p of document.querySelectorAll('.qa *')) {
    const kids = [...p.children].filter(vis);
    if (kids.length < 2) continue;
    const groups = {};
    for (const k of kids) { const c = (typeof k.className === 'string' && k.className.trim().split(/\s+/)[0]) || ''; if (!c) continue; (groups[k.tagName + '.' + c] ||= []).push(k); }
    for (const [g, els] of Object.entries(groups)) {
      if (els.length < 2) continue;
      const rows = {};
      for (const e of els) { const t = Math.round(e.getBoundingClientRect().top / 3); (rows[t] ||= []).push(e); }
      for (const row of Object.values(rows)) {
        if (row.length < 2) continue;
        const hs = row.map((e) => Math.round(e.getBoundingClientRect().height));
        if (Math.max(...hs) - Math.min(...hs) > 2) out.push({ kind: 'row-siblings', what: g, in: name(p).slice(0, 60), heights: hs, text: row.map((e) => (e.innerText || '').trim().slice(0, 24)) });
      }
    }
  }
  // 2. controls side by side with different heights
  const ctrls = [...document.querySelectorAll('.qa button, .qa input:not([type=checkbox]):not([type=radio]), .qa select, .qa a.btn')].filter(vis);
  const byParent = new Map();
  for (const c of ctrls) { const p = c.parentElement; if (!byParent.has(p)) byParent.set(p, []); byParent.get(p).push(c); }
  for (const [p, cs] of byParent) {
    const fl = getComputedStyle(p).display;
    if (!/flex|grid/.test(fl) || cs.length < 2) continue;
    const rows = {};
    for (const e of cs) { const r = e.getBoundingClientRect(); (rows[Math.round((r.top + r.height / 2) / 4)] ||= []).push(e); }
    for (const row of Object.values(rows)) {
      const hs = row.map((e) => Math.round(e.getBoundingClientRect().height));
      if (row.length > 1 && Math.max(...hs) - Math.min(...hs) > 1) out.push({ kind: 'controls', in: name(p).slice(0, 60), heights: hs, text: row.map((e) => name(e).slice(0, 30) + ':' + (e.innerText || e.value || e.placeholder || '').trim().slice(0, 18)) });
    }
  }
  // 3. same class across different parents in one row (lane heads, cards, columns), different heights
  const blocks = [...document.querySelectorAll('.qa *')].filter((e) => typeof e.className === 'string' && e.className.trim() && vis(e) && /block|flex|grid/.test(getComputedStyle(e).display) && e.getBoundingClientRect().width > 90);
  const byCls = {};
  for (const e of blocks) { const c = e.className.trim().split(/\s+/)[0]; const t = Math.round(e.getBoundingClientRect().top / 3); (byCls[c + '@' + t] ||= []).push(e); }
  for (const [k, els] of Object.entries(byCls)) {
    const ps = new Set(els.map((e) => e.parentElement));
    if (els.length < 2 || ps.size < 2) continue;
    const hs = els.map((e) => Math.round(e.getBoundingClientRect().height));
    if (Math.max(...hs) - Math.min(...hs) > 2) out.push({ kind: 'row-across', what: k.split('@')[0], heights: hs, text: els.map((e) => (e.innerText || '').trim().slice(0, 20)) });
  }
  return out;
}
"""
routes = sys.argv[1:] or ["board", "history", "reports", "integrations", "skills?project=SCRUM", "onboarding", "setup/claude", "setup/tracker", "setup/testrail"]
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(U + "/#/login"); pg.wait_for_timeout(800)
    if pg.locator("text=Sign in with Google").count(): pg.click("text=Sign in with Google"); pg.wait_for_timeout(1000)
    for r in routes:
        if r.startswith("pv:"):
            mode, r = r[3:].split(",", 1); pg.goto(U + "/pv/onb/" + mode)
        if r.startswith("click:"):
            sel = r[6:]; pg.click(sel); pg.wait_for_timeout(700)
        else:
            pg.goto(U + "/#/" + r); pg.wait_for_timeout(1400)
        res = pg.evaluate(JS)
        seen = set()
        print("=====", r, len(res))
        for x in res:
            k = json.dumps(x, sort_keys=True)
            if k in seen: continue
            seen.add(k); print(" ", k[:300])
    if "drawer" in sys.argv or not sys.argv[1:]:
        pg.goto(U + "/#/board"); pg.wait_for_timeout(1200); pg.click("text=OPTR-48466"); pg.wait_for_timeout(800)
        res = pg.evaluate(JS); print("===== drawer", len(res))
        for x in res: print(" ", json.dumps(x)[:300])
    b.close()
