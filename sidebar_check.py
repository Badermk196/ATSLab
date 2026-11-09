"""
The sidebar of the Admin page, checked in a real browser (Microsoft Edge, headless, through Playwright).

  py -3.12 sidebar_check.py

It starts the app on a TEMPORARY data folder with a test admin (your own data folder, database, resumes
and settings are never touched, and no AI call is made), then it says for every rule PASS or FAIL, with the
numbers behind it, at 1366 and 1920 wide in light and dark mode, with the menu on "Check a resume" and on
"Needs review":

  R1  "★ ADMIN" is on its own line under "ATS LAB", starting on the same line as "1000Jobs" and "ATS LAB",
      with 4 to 16 px of space above it.
  R2  The open menu item is fully inside the sidebar, with the same padding as the other items, and its
      label never runs under the red count of "Needs review".
  R3  The profile card at the bottom (initial, name, "Admin", sign-out) is fully inside the sidebar,
      starting and ending exactly like the menu items.
  R4  The "«" fold button is visible, sits on the line of "1000Jobs" and overlaps nothing.
  R5  Nothing scrolls sideways: neither the sidebar nor the page.

Screenshots and the numbers: the sidebar_check\\ folder next to this script. The report is Markdown
(sidebar_check.md) on purpose: test_ATSLab_v3 reads every *.txt two folders deep in the project as a job
posting, so a .txt report would look like a broken job description. Exit code 0 = every rule passed.
Needs Playwright: py -3.12 -m pip install playwright
"""

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "sidebar_check"
ADMIN_NAME, ADMIN_PASS = "Sidebar Check", "sidebar-check-only"
SIZES = ((1366, 768, "light"), (1366, 768, "dark"), (1920, 1080, "light"), (1920, 1080, "dark"))
VIEWS = ("check", "review")
GAP_MIN, GAP_MAX = 4.0, 16.0

MEASURE = r"""
() => {
  const rect = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return {x:+b.x.toFixed(1), y:+b.y.toFixed(1), w:+b.width.toFixed(1), h:+b.height.toFixed(1),
            right:+b.right.toFixed(1), bottom:+b.bottom.toFixed(1)}; };
  const cs = (el, p) => el ? getComputedStyle(el)[p] : null;
  const q = (s) => document.querySelector(s);
  const overlap = (a, b) => !!a && !!b && a.x < b.right - 0.5 && b.x < a.right - 0.5
      && a.y < b.bottom - 0.5 && b.y < a.bottom - 0.5;
  const side = q('section[data-testid="stSidebar"]');
  const shell = q('[data-testid="stSidebarUserContent"]');
  const content = q('[data-testid="stSidebarContent"]');
  const sideBox = rect(side);
  const logo = rect(q('.a-brand .logo')), lab = rect(q('.a-brand .lab')), badge = rect(q('.a-brand .badge'));
  const fold = q('[data-testid="stSidebarCollapseButton"]');
  const foldBtn = fold ? (fold.querySelector('button') || fold) : null;
  const foldBox = rect(foldBtn);
  const items = [...document.querySelectorAll('[class*="st-key-nav_"] button')].map(el => {
    const k = (el.closest('[class*="st-key-nav_"]').className.match(/st-key-nav_(\w+)/) || [])[1];
    return {key: k, box: rect(el), label: rect(el.querySelector('p')),
            pad: [cs(el,'paddingTop'), cs(el,'paddingRight'), cs(el,'paddingBottom'), cs(el,'paddingLeft')].join(' '),
            bg: cs(el, 'backgroundColor')};
  });
  const review = items.filter(i => i.key === 'review')[0];
  const card = rect(q('.st-key-side-card')), version = rect(q('.a-ver'));
  const signOut = rect(q('.st-key-sign_out button'));
  return {
    win: {w: window.innerWidth, h: window.innerHeight},
    sidebar: sideBox, shell: rect(shell),
    shellPadLeft: cs(shell, 'paddingLeft'), shellPadRight: cs(shell, 'paddingRight'),
    contentScroll: content ? {scrollW: content.scrollWidth, clientW: content.clientWidth} : null,
    pageScroll: {scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth},
    logo: logo, lab: lab, badge: badge,
    badgeOwnLine: (badge && lab) ? badge.y >= lab.bottom - 0.5 : null,
    badgeGap: (badge && lab) ? +(badge.y - lab.bottom).toFixed(1) : null,
    badgeLeftAligned: (badge && lab && logo) ? (Math.abs(badge.x - lab.x) < 1.5 && Math.abs(badge.x - logo.x) < 1.5) : null,
    items: items, openItems: items.filter(i => i.bg !== 'rgba(0, 0, 0, 0)').map(i => i.key),
    reviewLabelClear: (review && review.label) ? review.label.right <= (review.box.right - 10 - 22) - 1 : null,
    fold: foldBox, foldVisible: !!(foldBtn && cs(foldBtn, 'visibility') === 'visible' && cs(foldBtn, 'opacity') !== '0'),
    foldOnLogoLine: (foldBox && logo) ? (foldBox.y < logo.bottom && foldBox.bottom > logo.y) : null,
    foldInside: (foldBox && sideBox) ? (foldBox.x >= sideBox.x - 0.5 && foldBox.right <= sideBox.right + 0.5) : null,
    foldOverlapsText: overlap(foldBox, logo) || overlap(foldBox, lab) || overlap(foldBox, badge),
    foldOverlapsMenu: items.some(i => overlap(foldBox, i.box)),
    card: card, version: version, signOut: signOut,
    cardInside: (card && sideBox) ? (card.x >= sideBox.x - 0.5 && card.right <= sideBox.right + 0.5
                                     && card.bottom <= sideBox.bottom + 0.5) : null,
    cardLikeMenu: (card && items[0]) ? (Math.abs(card.x - items[0].box.x) < 1.5
                                        && Math.abs(card.right - items[0].box.right) < 1.5) : null,
    versionInside: (version && sideBox) ? version.bottom <= sideBox.bottom + 0.5 : null,
    signOutInsideCard: (signOut && card) ? (signOut.right <= card.right + 0.5 && signOut.x >= card.x - 0.5) : null,
  };
}
"""


def rules(m):
    """Every rule of this file, with the numbers behind the answer."""
    pad_left, pad_right = float(m["shellPadLeft"].replace("px", "")), float(m["shellPadRight"].replace("px", ""))
    inside = all(i["box"]["x"] >= m["sidebar"]["x"] + pad_left - 0.5
                 and i["box"]["right"] <= m["sidebar"]["right"] - pad_right + 0.5 for i in m["items"])
    pads = {i["pad"] for i in m["items"]}
    return [
        ("R1 ADMIN badge on its own line, left-aligned, 4-16 px of space",
         bool(m["badgeOwnLine"]) and bool(m["badgeLeftAligned"]) and GAP_MIN <= (m["badgeGap"] or -99) <= GAP_MAX,
         f"space above {m['badgeGap']} px, badge starts at x {m['badge']['x']} (logo x {m['logo']['x']})"),
        ("R2 open menu item fully visible, same padding as the others",
         len(pads) == 1 and inside and len(m["openItems"]) == 1 and bool(m["reviewLabelClear"]),
         f"padding {sorted(pads)}, inside {inside}, open {m['openItems']}, "
         f"review label ends at {m['items'] and [i for i in m['items'] if i['key'] == 'review'][0]['label']['right']}"),
        ("R3 profile card fully inside, like the menu items, sign-out inside it",
         bool(m["cardInside"]) and bool(m["cardLikeMenu"]) and bool(m["signOutInsideCard"]) and bool(m["versionInside"]),
         f"card x {m['card']['x']}-{m['card']['right']} (menu x {m['items'][0]['box']['x']}-"
         f"{m['items'][0]['box']['right']}), inside {m['cardInside']}"),
        ("R4 fold button visible, on the 1000Jobs line, overlapping nothing",
         bool(m["foldVisible"]) and bool(m["foldOnLogoLine"]) and bool(m["foldInside"])
         and not m["foldOverlapsText"] and not m["foldOverlapsMenu"],
         f"visible {m['foldVisible']}, box x {m['fold']['x']}-{m['fold']['right']} y {m['fold']['y']}-"
         f"{m['fold']['bottom']}, logo line y {m['logo']['y']}-{m['logo']['bottom']}"),
        ("R5 nothing scrolls sideways",
         bool(m["contentScroll"]) and m["contentScroll"]["scrollW"] <= m["contentScroll"]["clientW"] + 1
         and m["pageScroll"]["scrollW"] <= m["pageScroll"]["clientW"] + 1,
         f"sidebar {m['contentScroll']}, page {m['pageScroll']}"),
    ]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_data():
    """A small temporary data folder: three checks, one of them needs review (the red count shows)."""
    import lab_store as H
    folder = tempfile.mkdtemp(prefix="atslab_sidebar_check_")
    store = H.Store(folder)
    rows = (("2026-11-01 09:00:00", "user", "Sana Malik", 82, "Strong", []),
            ("2026-11-01 11:30:00", "user", "Omar Haddad", 48, "At risk", ["Score under 55"]),
            ("2026-11-02 08:15:00", ADMIN_NAME, "Lina Farouk", 71, "Good", []))
    con = store.db()
    try:
        with con:
            for at, who, name, score, label, reasons in rows:
                con.execute("INSERT INTO checks (created_at, checked_by, candidate, file_name, with_job, job_title,"
                            " score, label, parts, issues, review_reasons, review_facts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (at, who, name, name.replace(" ", "_") + ".pdf", 1, "Operations Manager", score, label,
                             "{}", json.dumps([{"name": "Job dates missing", "severity": "Important", "points": 6.0}]),
                             json.dumps(reasons),
                             json.dumps({"score": score, "critical": [], "no_email": False, "no_phone": False})))
    finally:
        con.close()
    return folder


def wait_for_app(port, seconds=120):
    import urllib.request
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run:  py -3.12 -m pip install playwright")
        return 2
    sys.path.insert(0, str(HERE))
    data = test_data()
    port = free_port()
    env = dict(os.environ)
    env.update({"ATSLAB_DATA_DIR": data, "ATSLAB_ADMINS": json.dumps({ADMIN_NAME: ADMIN_PASS}),
                "ATSLAB_AI_REVIEW": "0", "PYTHONIOENCODING": "utf-8"})
    env.pop("OPENROUTER_API_KEY", None)                 # no AI call can happen in this check
    OUT.mkdir(exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(HERE / "app.py"),
                               "--server.port", str(port), "--server.address", "127.0.0.1",
                               "--server.headless", "true", "--server.fileWatcherType", "none",
                               "--browser.gatherUsageStats", "false"],
                              cwd=str(HERE), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    failed, checks, lines, saved = 0, 0, [], {}
    try:
        if not wait_for_app(port):
            print("The app did not start. Try again, or start it once by hand to see the error.")
            return 2
        with sync_playwright() as pw:
            browser = None
            for channel in ("msedge", "chrome", None):
                try:
                    browser = pw.chromium.launch(channel=channel, headless=True) if channel \
                        else pw.chromium.launch(headless=True)
                    break
                except Exception:
                    browser = None
            if browser is None:
                print("No Edge or Chrome found for the check. Open the Admin page by hand and look at the sidebar.")
                return 2
            ctx = browser.new_context(viewport={"width": 1366, "height": 768})
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{port}/admin", wait_until="load")
            page.wait_for_selector("input[type='password']", timeout=60000)
            fields = page.locator("input[type='text'], input[type='password']")
            fields.nth(0).fill(ADMIN_NAME)
            fields.nth(1).fill(ADMIN_PASS)
            page.locator("button:has-text('Sign in')").first.click()
            page.wait_for_selector('section[data-testid="stSidebar"]', timeout=60000)
            page.wait_for_timeout(3000)
            for view in VIEWS:
                if view != "check":
                    page.locator(f".st-key-nav_{view} button").first.click(timeout=15000)
                    page.wait_for_timeout(4000)
                for width, height, theme in SIZES:
                    page.set_viewport_size({"width": width, "height": height})
                    page.emulate_media(color_scheme=theme)
                    page.wait_for_timeout(1500)
                    key = f"{width}x{height}_{theme}_{view}"
                    m = page.evaluate(MEASURE)
                    saved[key] = m
                    page.screenshot(path=str(OUT / f"{key}.png"))
                    page.screenshot(path=str(OUT / f"{key}_sidebar.png"),
                                    clip={"x": 0, "y": 0, "width": 248, "height": min(height, 220)})
                    lines.append(f"===== {width} x {height}, {theme} mode, menu on \"{view}\"")
                    for name, ok, detail in rules(m):
                        checks += 1
                        failed += 0 if ok else 1
                        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}\n            {detail}")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except Exception:
            server.kill()
        shutil.rmtree(data, ignore_errors=True)
    text = "\n".join(lines) + f"\n\n{checks} rule checks, {failed} failed\n"
    print(text)
    (OUT / "sidebar_check.md").write_text(text, encoding="utf-8")
    (OUT / "sidebar_check.json").write_text(json.dumps(saved, indent=1), encoding="utf-8")
    print(f"Screenshots and the numbers: {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
