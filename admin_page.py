"""
The Admin page (for the 1000Jobs team), behind a name and password (admin accounts come from the secrets or the
environment, see lab_settings.py and DEPLOY.md). Design: "1000Jobs ATS Lab Redesign", pages 1-5.

A left sidebar with the views, the "Needs review" count, the signed-in admin, "Sign out" and the version:
  Check a resume   upload, target role + job description, compare with a previous resume (client comparison report),
                   "The report shows" and "Recent checks" on the side; the full report after the check
  History          4 summary cards, label chips, search, filters (job, dates, checked by), the table; open a report,
                   "Export CSV", "Delete record" (asks first; removes the report and the file)
  Needs review     one card per flagged resume: score, label, reasons, notes, the user's name and email when known,
                   "Mark reviewed" (saves who and when)
  Settings         days to keep resume files, the daily check limit, the "Needs review" rules, the user page links,
                   the name-and-email step
  Activity log     who did what and when (checks, reviews, settings, deletions, exports, sign-ins), "Export CSV"
Every text is in lab_text.py, the look in lab_ui.py.
"""

import csv
import datetime as dt
import hashlib
import io
import secrets

import streamlit as st

import dashboard as D
import lab_bugs as BG
import lab_benchmark as B
import lab_node as LN
import lab_pages as P
import lab_second as SO
import lab_settings as S
import lab_store as H
import lab_text as T
import lab_ui as UI

ADMIN_TEXT = T.ADMIN_TEXT
VIEWS = tuple(T.NAV)                     # check, history, review, settings, log
OLD_VIEWS = {label: key for key, (label, _) in T.NAV.items()}    # a view saved by its label (v1.3) still opens
MAX_TRIES, LOCK_SECONDS = 5, 60          # wrong passwords in a row, then a short wait
PAGE_ROWS = 20                           # History rows per page
LOG_ROWS = 300                           # Activity log rows shown (the CSV has all of them)
LABELS = ("Excellent", "Strong", "Good", "Needs work", "At risk", "Not ready")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
HISTORY_COLS = [0.32, 2.4, 1.45, 1.2, 1.7, 1.75, 1.55, 0.42]


def hidden_label(selector):
    """CSS: the button keeps its text for screen readers and tests, but only its icon shows."""
    return selector + " button p {position: absolute; width: 1px; height: 1px; overflow: hidden; " \
        "clip: rect(0 0 0 0); white-space: nowrap;}"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def when(text, sep=", "):
    """'2026-10-29 00:47:12' -> 'Oct 29, 00:47'."""
    try:
        t = dt.datetime.strptime(text[:19], H.TIME_FORMAT)
    except (TypeError, ValueError):
        return text or ""
    return f"{MONTHS[t.month - 1]} {t.day}{sep}{t:%H:%M}"


def day_of(text):
    try:
        return dt.date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


def ago(text):
    """When something was checked, in plain words: 'just now' / '5 min ago' / '2 h ago' / 'Oct 29, 00:47'."""
    try:
        t = dt.datetime.strptime((text or "")[:19], H.TIME_FORMAT)
    except (TypeError, ValueError):
        return text or ""
    secs = (H.now() - t).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    return when(text)


def candidate(r):
    return r.get("candidate") or ADMIN_TEXT["no_name"]


def source_of(r):
    return ADMIN_TEXT["source_user"] if r["checked_by"] == H.USER else r["checked_by"]


def job_of(r):
    return (r.get("job_title") or D.REPORT_TEXT["with_job_plain"]) if r.get("with_job") else ADMIN_TEXT["general"]


def safe_cell(value):
    """A CSV cell that a spreadsheet never runs as a formula ('=...', '+...', '-...', '@...')."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_bytes(header, rows):
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(header)
    for row in rows:
        out.writerow([safe_cell(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")        # the BOM: Excel reads the names in UTF-8


def store():
    return P.store()


def go(view):
    """Open a view from the sidebar (or a 'See all' / 'New check' button)."""
    st.session_state["admin_view"] = view
    for k in ("open_check", "confirm_delete"):
        st.session_state.pop(k, None)


def current_view():
    view = st.session_state.get("admin_view")
    view = OLD_VIEWS.get(view, view)
    if view not in VIEWS:
        view = VIEWS[0]
    st.session_state["admin_view"] = view
    return view


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------
def guard_keys(name, ip):
    """Wrong tries are counted for the typed name and for the IP address, on the server (a reload resets nothing)."""
    return [f"name:{' '.join((name or '').split()).lower()}", f"ip:{ip}"]


def sign_in(name, password, ip="local", store=None):
    """-> the admin's name, or None. After MAX_TRIES wrong tries in a row for a name or from an IP address, the next
    tries for it wait LOCK_SECONDS (even with the right password)."""
    store = store or P.store()
    keys = guard_keys(name, ip)
    if store.login_wait(keys) > 0:
        return None
    who = S.check_login(name, password)
    if who:
        store.login_ok(keys)
        return who
    store.login_failed(keys, MAX_TRIES, LOCK_SECONDS)
    return None


def brand_html():
    return (f'<div class="a-brand"><div class="logo">{T.BRAND}</div><span class="lab">{ADMIN_TEXT["lab"]}</span>'
            f'<span class="badge">{ADMIN_TEXT["admin_badge"]}</span></div>')


def login_card():
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        st.markdown(brand_html(), unsafe_allow_html=True)
        with st.container(key="card-login"):
            st.markdown(f'<div class="a-h3">{ADMIN_TEXT["login_title"]}</div><p class="a-sub">'
                        f'{ADMIN_TEXT["login_sub"]}</p>', unsafe_allow_html=True)
            if not S.admin_accounts():
                st.warning(ADMIN_TEXT["no_accounts"])
                return
            with st.form("admin_login", border=False):
                name = st.text_input(ADMIN_TEXT["name"])
                password = st.text_input(ADMIN_TEXT["password"], type="password")
                go_in = st.form_submit_button(ADMIN_TEXT["sign_in"], type="primary", width="stretch")
            if go_in:
                ip = P.client_ip()
                who = sign_in(name, password, ip)
                if who:
                    st.session_state["admin"] = who
                    remember_me(who)                 # no password again on this browser (Sign out ends it)
                    store().log(who, "sign_in", T.LOG_DETAILS["sign_in"])
                    st.rerun()
                st.error(ADMIN_TEXT["locked"] if store().login_wait(guard_keys(name, ip)) > 0 else ADMIN_TEXT["wrong"])


def remember_me(who):
    """Stay signed in on this browser: a random token (its hash goes to the database), never a password. The cookie
    itself is written by keep_cookie() on the next page draw, not in the run that ends in st.rerun()."""
    token = secrets.token_hex(16)
    store().remember_admin(token, who, S.admin_accounts().get(who))
    st.session_state["admin_token"] = token
    st.session_state.pop("admin_cookie_sent", None)
    return token


def restore_login():
    """-> the admin's name when this browser signed in before and did not sign out, else None."""
    token = st.session_state.get("admin_token") or P.admin_token()
    if not token:
        return None
    who = store().admin_of_token(token, S.admin_accounts())
    if who:
        st.session_state["admin"] = who
        st.session_state["admin_token"] = token
        return who
    st.session_state.pop("admin_token", None)        # an old token (a signed-out one, a changed password): ask again
    P.clear_admin_token()
    return None


def keep_cookie():
    """Write the sign-in cookie (30 days from now) once per session, in a run that is drawn and stays: the first one
    after the sign in, or the first one after the cookie brought the admin back (that renews it)."""
    token = st.session_state.get("admin_token")
    if token and st.session_state.get("admin_cookie_sent") != token:
        P.set_admin_token(token)
        st.session_state["admin_cookie_sent"] = token


def sign_out():
    token = st.session_state.pop("admin_token", None) or P.admin_token()
    if token:
        store().forget_token(token)
        P.clear_admin_token()
    for k in ("admin", "result", "open_check", "confirm_delete", "admin_view", "upload_round", "admin_cookie_sent"):
        st.session_state.pop(k, None)


# ---------------------------------------------------------------------------
# The sidebar
# ---------------------------------------------------------------------------
def nav_badge(key, n):
    """The red count on a menu item (Needs review, Bug audit). Nothing is drawn when the count is zero."""
    if not n:
        return ""
    return (f'.st-key-nav_{key} button {{position: relative;}} .st-key-nav_{key} button::after {{content: "{n}"; '
            f"position: absolute; right: 10px; top: 50%; transform: translateY(-50%); min-width: 22px; height: 22px; "
            f"padding: 0 6px; border-radius: 11px; background: var(--a-badge); color: #fff; font-size: .75rem; "
            f"font-weight: 700; display: flex; align-items: center; justify-content: center;}}")


def nav_css(view, n_review, n_bugs=0):
    """The open view's item, the red "Needs review" count, and the hidden labels of icon buttons."""
    on = (f".st-key-nav_{view} button {{background: var(--a-pri-soft) !important; border-color: var(--a-pri-line) "
          f"!important;}} .st-key-nav_{view} button p, .st-key-nav_{view} button [data-testid=\"stIconMaterial\"] "
          f"{{color: var(--a-pri-text) !important; font-weight: 600 !important;}}")
    badge = nav_badge("review", n_review) + nav_badge("bugs", n_bugs)
    hidden = hidden_label(".st-key-sign_out") + hidden_label("[class*='st-key-hopen_']")
    gap = ".st-key-nav_check {margin-top: 12px;}"      # the first item sits a little away from "WORKSPACE"
    return on + badge + gap + hidden


def sidebar(who, view):
    with st.sidebar:
        st.markdown(brand_html() + f'<div class="a-ws">{ADMIN_TEXT["workspace"]}</div>', unsafe_allow_html=True)
        for key, (label, icon) in T.NAV.items():
            st.button(label, icon=icon, key=f"nav_{key}", type="tertiary", width="stretch", on_click=go, args=(key,))
        with st.container(key="side-foot"):
            with st.container(key="side-card"):
                a, b = st.columns([5, 1.4], vertical_alignment="center")
                a.markdown(f'<div class="a-foot" title="{UI.esc(ADMIN_TEXT["signed_in"].format(name=who))}">'
                           f'{UI.avatar(who, primary=True)}<div style="min-width:0"><div class="nm">{UI.esc(who)}</div>'
                           f'<div class="rl">{ADMIN_TEXT["role"]}</div></div></div>', unsafe_allow_html=True)
                b.button(ADMIN_TEXT["sign_out"], icon=":material/logout:", key="sign_out", on_click=sign_out,
                         type="tertiary", help=ADMIN_TEXT["sign_out"])
            st.markdown(f'<div class="a-ver">{ADMIN_TEXT["version"].format(version=T.APP_VERSION)}</div>',
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Check a resume
# ---------------------------------------------------------------------------
def saver(who):
    """Saves each new check of the Admin page to the history, and logs it."""
    def save(saved):
        inputs = saved.get("inputs") or {}
        try:
            rec = H.record_of(saved["res"], who, inputs.get("job_title"), saved.get("prev"),
                              bool(inputs.get("client")), saved.get("swap"))
            store().add_check(rec, inputs.get("pdf"))
            r = saved["res"]
            store().log(who, "check", rec["candidate"] or rec["file_name"],
                        T.LOG_DETAILS["check"].format(job=rec["job_title"] or ADMIN_TEXT["general"],
                                                      score=int(float(r["score"] or 0)), label=r["label"]))
            st.toast(ADMIN_TEXT["saved"])
        except Exception as e:                      # the check itself is never lost because of the history
            st.warning(ADMIN_TEXT["not_saved"].format(why=type(e).__name__))
    return save


def keep_mode():
    """The switch never ends with nothing selected (a click on the selected side would clear it)."""
    if st.session_state.get("mode") is None:
        st.session_state["mode"] = st.session_state.get("last_mode", D.WITH_JOB)
    st.session_state["last_mode"] = st.session_state["mode"]


def mode_switch():
    st.session_state.setdefault("mode", D.WITH_JOB)
    if st.session_state["mode"] not in (D.WITH_JOB, D.WITHOUT_JOB):
        st.session_state["mode"] = D.WITH_JOB
    st.segmented_control("Check", (D.WITH_JOB, D.WITHOUT_JOB), key="mode", label_visibility="collapsed",
                         on_change=keep_mode,
                         format_func=lambda m: ADMIN_TEXT["mode_job"] if m == D.WITH_JOB else ADMIN_TEXT["mode_general"])
    return st.session_state["mode"] or D.WITH_JOB


def label_row(label, note):
    return (f'<div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline;line-height:1.5;'
            f'margin:4px 0 0 0"><span style="font-weight:600;font-size:.9rem">{UI.esc(label)}</span>'
            f'<span class="a-muted a-small">{UI.esc(note)}</span></div>')


def job_fields(round_, prefix=""):
    st.markdown(label_row(ADMIN_TEXT["role_label"], ADMIN_TEXT["role_note"]), unsafe_allow_html=True)
    title = st.text_input(ADMIN_TEXT["role_label"], placeholder=ADMIN_TEXT["role_hint"], label_visibility="collapsed",
                          key=f"{prefix}job_title_{round_}")
    st.markdown(label_row(ADMIN_TEXT["jd_label"], ADMIN_TEXT["jd_note"]), unsafe_allow_html=True)
    text = st.text_area(ADMIN_TEXT["jd_label"], height=170, placeholder=ADMIN_TEXT["jd_hint"],
                        label_visibility="collapsed", key=f"{prefix}job_{round_}")
    return title, text


def client_slots(round_):
    """The client comparison report's two files, each in its own clearly named slot, with the Swap button between them.
    -> (the file read as the user's own resume, the file read as the 1000Jobs resume, is it read the other way round?).
    The slots say the order; the Swap button makes the two files read the other way round, and the line under them says
    which file is read as which, so a file in the wrong slot is easy to spot before the report is made."""
    st.caption(ADMIN_TEXT["pair_hint"])
    swapped = bool(st.session_state.get(f"swap_{round_}"))
    left, mid, right = st.columns([1, 0.46, 1], vertical_alignment="center")
    with left:
        original = st.file_uploader(ADMIN_TEXT["slot_original"], type=D.UPLOAD_TYPES, key=f"c_original_{round_}")
        st.caption(ADMIN_TEXT["slot_original_hint"])
    with mid:
        if st.button(ADMIN_TEXT["swap"], key=f"swap_btn_{round_}", width="stretch", icon=":material/swap_horiz:",
                     help=ADMIN_TEXT["swap_help"]):
            st.session_state[f"swap_{round_}"] = not swapped
            st.rerun()
    with right:
        ours = st.file_uploader(ADMIN_TEXT["slot_ours"], type=D.UPLOAD_TYPES, key=f"c_ours_{round_}")
        st.caption(ADMIN_TEXT["slot_ours_hint"])
    user_file, ours_file = (ours, original) if swapped else (original, ours)
    if user_file is not None and ours_file is not None:
        st.markdown(f'<div class="a-note">{UI.esc((ADMIN_TEXT["swap_note"] if swapped else ADMIN_TEXT["roles_read"])
                                                  .format(original=user_file.name, ours=ours_file.name))}</div>',
                    unsafe_allow_html=True)
    else:
        st.caption(ADMIN_TEXT["pair_wait"])
    return user_file, ours_file, swapped


def client_inputs(round_, user_file, ours_file, swapped, mode, title, text):
    """The inputs of the client comparison report, after looking at the two files the way they will be read. A file
    that carries the 1000Jobs layout in the slot of the user's own resume is never passed silently: the two files are
    shown and the team decides (swap them, or go on and build the report)."""
    if user_file is None or ours_file is None:
        st.error(ADMIN_TEXT["need_both"])
        return None
    marks = D.template_marks(user_file.getvalue(), user_file.name)
    if marks:
        st.warning(ADMIN_TEXT["roles_warn"].format(file=user_file.name, marks=", ".join(marks),
                                                  swap=ADMIN_TEXT["swap"], confirm=ADMIN_TEXT["roles_confirm"]))
        a, b = st.columns(2)
        if a.button(ADMIN_TEXT["swap"], key=f"swap_warn_{round_}", width="stretch", icon=":material/swap_horiz:"):
            st.session_state[f"swap_{round_}"] = not swapped
            st.rerun()
        if b.button(ADMIN_TEXT["roles_confirm"], key=f"roles_go_{round_}", type="primary", width="stretch"):
            pass                                   # go on: the report is built with these two files
        else:
            return None
    return {"pdf": ours_file.getvalue(), "name": ours_file.name, "with_job": mode == D.WITH_JOB, "text": text,
            "job_title": title, "prev_pdf": user_file.getvalue(), "prev_name": user_file.name,
            "client": True, "swap": True if swapped else None}


def check_form(mode):
    """The upload card: resume, target role + job description (with a job), and - for the client comparison report -
    the user's own resume and the 1000Jobs resume in their own slots, with a Swap button and a check before the report."""
    round_ = st.session_state.get("upload_round", 0)
    client = bool(st.session_state.get(f"client_{round_}", False))    # set by the checkbox below, on the run before
    upload = None if client else st.file_uploader(ADMIN_TEXT["resume"], type=D.UPLOAD_TYPES, key=f"upload_{round_}")
    title, text = job_fields(round_) if mode == D.WITH_JOB else ("", "")
    if mode != D.WITH_JOB:
        st.caption(ADMIN_TEXT["general_note"])
    user_file = ours_file = prev = None
    swapped = None
    with st.expander(ADMIN_TEXT["compare_client"] if client else ADMIN_TEXT["compare"], icon=":material/compare_arrows:",
                     expanded=client):            # stays open in the client mode: a rerun never hides the two slots
        st.caption(ADMIN_TEXT["compare_client_sub"] if client else ADMIN_TEXT["compare_sub"])
        client = st.checkbox(D.CLIENT_TEXT["checkbox"], key=f"client_{round_}")
        if client:
            user_file, ours_file, swapped = client_slots(round_)
        else:
            prev = st.file_uploader(ADMIN_TEXT["previous"], type=D.UPLOAD_TYPES, key=f"previous_{round_}")
    if st.button(ADMIN_TEXT["run"], type="primary", width="stretch", key="run_check", icon=":material/arrow_forward:",
                 icon_position="right"):
        st.session_state[f"wanted_{round_}"] = True       # the check is wanted: the two files are looked at first
    if not st.session_state.get(f"wanted_{round_}"):
        return None
    if client:
        out = client_inputs(round_, user_file, ours_file, swapped, mode, title, text)
        if out is None:                                   # a file to look at again: nothing checked yet
            return None
        st.session_state.pop(f"wanted_{round_}", None)
        return out
    st.session_state.pop(f"wanted_{round_}", None)
    return {"pdf": upload.getvalue() if upload else b"", "name": upload.name if upload else "",
            "with_job": mode == D.WITH_JOB, "text": text, "job_title": title,
            "prev_pdf": prev.getvalue() if prev is not None else None,
            "prev_name": prev.name if prev is not None else None, "client": client}


def run(inputs, who):
    D.check_and_store(inputs, P.check_slot)
    if "result" in st.session_state:
        saver(who)(st.session_state["result"])
        st.rerun()


def checking_card():
    """While a check runs: one calm card instead of the upload form, so the page never looks half-built."""
    with st.container(key="card-check"):
        st.markdown(f'<div class="a-h3">{UI.esc(ADMIN_TEXT["checking_title"])}</div>'
                    f'<p class="a-sub">{UI.esc(ADMIN_TEXT["checking_sub"])}</p>', unsafe_allow_html=True)


def side_panels():
    with st.container(key="card-shows"):
        items = "".join(f'<li><span class="k">{n}</span><span>{UI.esc(t)}</span></li>'
                        for n, t in enumerate(ADMIN_TEXT["shows"], 1))
        st.markdown(f'<div class="a-h3">{ADMIN_TEXT["shows_title"]}</div><ul class="a-list">{items}</ul>',
                    unsafe_allow_html=True)
    with st.container(key="card-recent"):
        a, b = st.columns([3, 1.4], vertical_alignment="center")
        a.markdown(f'<div class="a-h3">{ADMIN_TEXT["recent"]}</div>', unsafe_allow_html=True)
        b.button(ADMIN_TEXT["see_all"], key="see_all", type="tertiary", on_click=go, args=("history",))
        rows = store().history(limit=3)
        body = "".join(f'<div class="a-recent"><div style="min-width:0"><b>{UI.esc(candidate(r))}</b>'
                       f'<span>{when(r["created_at"], " · ")}</span></div>{UI.pill(r["score"], r["label"])}</div>'
                       for r in rows) or f'<p class="a-sub">{ADMIN_TEXT["no_recent"]}</p>'
        st.markdown(f"<div>{body}</div>", unsafe_allow_html=True)


def again_card(mode, saved, who):
    """The switch was changed after a check: the same resume again in the other mode."""
    with st.container(key="card-again"):
        round_ = st.session_state.get("upload_round", 0)
        if mode == D.WITH_JOB:
            st.caption(ADMIN_TEXT["again_job"])
            title, text = job_fields(round_, "again_")
        else:
            st.caption(ADMIN_TEXT["again_general"])
            title, text = "", ""
        if st.button(ADMIN_TEXT["again"], type="primary", key="check_again"):
            run(dict(saved["inputs"], with_job=mode == D.WITH_JOB, text=text, job_title=title), who)


# ---------------------------------------------------------------------------
# Second opinion (Admin page only): four extra ATS checkers beside the Lab score
# ---------------------------------------------------------------------------
# They read the Lab's own numbers and never change them (lab_second.py). Each card is empty until the team
# presses its button, and all four run on this device: no resume leaves the computer.
SECOND_TEXT = T.SECOND_TEXT
SECOND_SETTINGS = {"matcher": "second_matcher", "checker2": "second_checker2", "engine": "second_engine",
                   "lever": "second_lever"}
SECOND_TONE = {"Agrees": "a-ok", "Higher": "a-info", "Lower": "a-warn"}
LEVER_TONE = {"read": "a-ok", "missed": "a-warn", "unclear": "a-info"}
LEVER_MARK = {"read": "\u2713", "missed": "\u2717", "unclear": "~"}


def unavailable_hint(checker, name, why=""):
    """The "not installed on this server" note. LeverParser needs a pip package; VeriWorkly sets itself up
    (Node 24 from pip, the engine from npm, once) and says what happened when it could not."""
    if checker == "lever":
        return SECOND_TEXT["unavailable_hint_lever"].format(name=name)
    if checker == "engine":
        if why == "installing":
            return SECOND_TEXT["veri_installing"]
        detail = LN.status().get("detail") or ""
        return SECOND_TEXT["veri_failed"].format(
            why=SECOND_TEXT["veri_why"].get(why, why or "unknown"), detail=(": " + detail) if detail else "")
    return SECOND_TEXT["unavailable_hint"].format(name=name)


def second_on(checker):
    """Whether this checker is switched on in Settings."""
    return bool(P.setting(SECOND_SETTINGS[checker]))


def second_key(saved, checker):
    """A key for one resume + job + checker: from the resume's bytes and the job text, so a different file or a
    different job description never reuses an answer (a general check and a check with a job differ too)."""
    inputs = saved.get("inputs") or {}
    seed = (inputs.get("pdf") or b"") + b"\n" + (inputs.get("text") or "").encode("utf-8")
    return f"so_{checker}_{hashlib.md5(seed).hexdigest()[:10]}"


def second_run(saved, checker, job_text, key):
    """Run one checker now (the team pressed the button) and keep its answer for this resume."""
    with st.spinner(SECOND_TEXT["checking"]):
        out = SO.run(checker, saved.get("res") or {}, job_text,
                     {"matcher": second_on("matcher"), "checker2": second_on("checker2"),
                      "engine": second_on("engine"), "lever": second_on("lever")})
        out = SO.finish(checker, saved.get("res") or {}, out)
        out["checked_at"] = H.now().strftime(H.TIME_FORMAT)
    st.session_state[key] = out
    st.rerun()


def second_answer(saved, checker, job_text, key):
    """The stored answer of one checker, running it when the team just pressed the button. None = not checked yet."""
    answer = st.session_state.get(key)
    if answer is None:
        return None
    if answer.get("state") == SO.CHECKING:          # the button was pressed on the run before this one
        second_run(saved, checker, job_text, key)   # (draws the spinner, keeps the answer, redraws)
    return answer


def read_line(checker, answer):
    """What this card actually read, in one line, so its number is never a mystery."""
    if checker == "matcher":
        if answer.get("source") == "role":          # a general check: the skills of the resume's own role
            return SECOND_TEXT["read_role"].format(role=answer.get("role") or "")
        if answer.get("source") == "skills":        # a general check with no role either: the resume's own skills
            return SECOND_TEXT["read_skills"]
        return SECOND_TEXT["read_job"]
    if checker == "engine":
        return SECOND_TEXT["read_engine"].format(version=SO.E.VERSION)
    if checker == "lever":
        return SECOND_TEXT["read_lever"].format(version=SO.V.VERSION)
    checks = answer.get("checks") or []
    passed = sum(1 for c in checks if c.get("passed"))
    return SECOND_TEXT["read_checks"].format(passed=passed, total=len(checks)) if checks else ""


def second_card(saved, checker, job_text):
    """One card: the checker's number, its label, the difference from the Lab's number, and its own button."""
    info = SO.CHECKERS[checker]
    name, key = info["name"], second_key(saved, checker)
    answer = second_answer(saved, checker, job_text, key)
    with st.container(key=f"card-so-{checker}"):
        st.markdown(f'<div class="so-name">{UI.esc(name)}</div>'
                    f'<div class="so-sub2">{UI.esc(info["sub"])}</div>', unsafe_allow_html=True)
        if not second_on(checker):
            st.markdown(f'<div class="so-state">{UI.esc(SECOND_TEXT["off"])}</div>'
                        f'<div class="so-note">{UI.esc(SECOND_TEXT["off_hint"].format(name=name))}</div>',
                        unsafe_allow_html=True)
            return
        if answer is None:                          # nothing checked yet: the card only offers its button
            st.markdown(f'<div class="so-state">{UI.esc(SECOND_TEXT["empty"])}</div>', unsafe_allow_html=True)
            if st.button(SECOND_TEXT["run"].format(name=name), key=f"so_run_{checker}_{key}", width="stretch"):
                st.session_state[key] = {"state": SO.CHECKING}
                st.rerun()
            return
        state = answer.get("state")
        if state in (SO.CHECKING, SO.NEEDS_JOB, SO.FAILED, SO.UNAVAILABLE):
            no_text = answer.get("why") == "no_text"
            setting_up = checker == "engine" and answer.get("why") == "installing"
            st.markdown(f'<div class="so-state">{UI.esc(SECOND_TEXT["veri_setting_up"] if setting_up else SECOND_TEXT[state])}</div>'
                        + (f'<div class="so-note">{UI.esc(SECOND_TEXT["no_text_hint"].format(name=name))}</div>'
                           if no_text else
                           f'<div class="so-note">{UI.esc(SECOND_TEXT["needs_job_hint"].format(name=name))}</div>'
                           if state == SO.NEEDS_JOB else
                           f'<div class="so-note">{UI.esc(unavailable_hint(checker, name, answer.get("why") or ""))}</div>'
                           if state == SO.UNAVAILABLE else
                           f'<div class="so-note">{UI.esc(SECOND_TEXT["failed_hint"])}</div>'
                           if state == SO.FAILED else ""), unsafe_allow_html=True)
            if state != SO.CHECKING and st.button(SECOND_TEXT["again"], key=f"so_again_{checker}_{key}",
                                                  width="stretch"):
                st.session_state[key] = {"state": SO.CHECKING}
                st.rerun()
            return
        general = answer.get("source") in ("role", "skills")   # a general check: no Job match to compare with
        compares = SO.compares_of(checker, answer)    # VeriWorkly with a job: its Job match vs the Lab's Job match
        if compares == "none":                    # a parse score is not an ATS score: nothing to compare with
            ref = SECOND_TEXT["no_score_reference"]
        elif general and compares == "job_match":
            ref = SECOND_TEXT["no_reference"]
        else:
            ref = SECOND_TEXT["vs_job" if compares == "job_match" else "vs_score"].format(
                n=answer.get("reference"))
        tag = (f'<span class="a-tag {SECOND_TONE.get(answer.get("word"), "a-grey")}">'
               f'{UI.esc(answer.get("difference") or "")}</span>') if answer.get("word") else ""
        st.markdown(
            f'<div class="so-top"><div><span class="so-big">{UI.esc(answer.get("score"))}</span>'
            f'<span class="so-of">/100</span><div class="so-lab">'
            f'{UI.esc(answer.get("label") or SO.label_for(answer.get("score")))}</div></div>'
            f'<div>{tag}<div class="so-lab" style="text-align:right">{UI.esc(ref)}</div></div></div>',
            unsafe_allow_html=True)
        st.markdown(f'<div class="so-note">{UI.esc(read_line(checker, answer))}</div>', unsafe_allow_html=True)
        if checker == "engine":                     # the open-source checker: its job match and failed checks
            job_match = answer.get("job_match")
            failed = len(answer.get("checks") or [])
            total = answer.get("n_total") or 0
            extra = []
            if answer.get("readiness") is not None:         # the big number is its Job match: say its readiness too
                extra.append(SECOND_TEXT["engine_readiness"].format(n=answer["readiness"]))
            elif job_match is not None:
                extra.append(SECOND_TEXT["engine_job_match"].format(n=job_match))
            if total:
                extra.append(SECOND_TEXT["engine_checks"].format(failed=failed, total=total))
            if extra:
                st.markdown(f'<div class="so-note">{UI.esc(" · ".join(extra))}</div>', unsafe_allow_html=True)
            if answer.get("missing"):
                st.markdown(f'<div class="so-note">'
                            f'{UI.esc(SECOND_TEXT["engine_missing"].format(list=", ".join(answer["missing"])))}'
                            f'</div>', unsafe_allow_html=True)
        elif checker == "matcher":                  # the keyword match, and what a keyword ATS would miss
            pct = answer.get("pct") or 0
            with_job = answer.get("source", "job") == "job"
            st.markdown(f'<div class="so-kw"><b>{UI.esc(SECOND_TEXT["keywords" if with_job else "skills"])}</b>'
                        f'<span>{UI.esc(SECOND_TEXT["keywords_line" if with_job else "skills_line"].format(
                            n=answer.get("n_matched"), total=answer.get("total"), pct=pct))}'
                        f'</span></div><div class="so-bar"><i style="width:{max(2, min(100, pct))}%"></i></div>',
                        unsafe_allow_html=True)
            if not answer.get("agree") and answer.get("missing"):
                text = SECOND_TEXT["missing" if with_job else "missing_skills"]
                st.markdown(f'<div class="so-note">'
                            f'{UI.esc(text.format(list=", ".join(SO.top_missing(answer))))}</div>',
                            unsafe_allow_html=True)
        elif checker == "lever":                    # the open-source parser: what it read, field by field
            fields = answer.get("fields") or []
            tags = "".join(
                f'<span class="a-tag {LEVER_TONE.get(f["state"], "a-grey")}" title="'
                f'{UI.esc(SECOND_TEXT["lever_tag"].get(f["state"], ""))}">'
                f'{UI.esc(LEVER_MARK.get(f["state"], ""))} {UI.esc(f["label"])}</span>' for f in fields)
            if tags:
                st.markdown(f'<div class="so-note" style="display:flex;flex-wrap:wrap;gap:6px">{tags}</div>',
                            unsafe_allow_html=True)
            shown = [f for f in fields if f["key"] in ("name", "email", "phone", "linkedin") and f["value"]]
            if shown:
                line = " \u00b7 ".join(f["label"] + ": " + f["value"] for f in shown)
                st.markdown('<div class="so-note">' + UI.esc(line) + '</div>', unsafe_allow_html=True)
            if answer.get("jobs"):
                jobs = " | ".join(" - ".join(p for p in (j["title"], j["company"], j["dates"]) if p)
                                  for j in answer["jobs"][:3])
                st.markdown(f'<div class="so-note">{UI.esc(SECOND_TEXT["lever_jobs"].format(list=jobs))}</div>',
                            unsafe_allow_html=True)
            if answer.get("education"):
                edu = " | ".join(" - ".join(p for p in (e["degree"], e["institution"], e["year"]) if p)
                                 for e in answer["education"][:2])
                st.markdown(f'<div class="so-note">{UI.esc(SECOND_TEXT["lever_education"].format(list=edu))}</div>',
                            unsafe_allow_html=True)
            st.markdown(f'<div class="so-note">'
                        f'{UI.esc(SECOND_TEXT["lever_skills"].format(n=answer.get("n_skills") or 0))}</div>',
                        unsafe_allow_html=True)
            if answer.get("missed"):
                st.markdown(f'<div class="so-note">'
                            f'{UI.esc(SECOND_TEXT["lever_missed"].format(list=", ".join(answer["missed"])))}'
                            f'</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="so-note">{UI.esc(SECOND_TEXT["lever_all_read"])}</div>',
                            unsafe_allow_html=True)
            if answer.get("unclear"):
                st.markdown(f'<div class="so-note">'
                            f'{UI.esc(SECOND_TEXT["lever_unclear"].format(list=", ".join(answer["unclear"])))}'
                            f'</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="so-note">{UI.esc(SECOND_TEXT["lever_note"])}</div>', unsafe_allow_html=True)
        else:                                       # ATS Checker 2: say which of its own checks failed
            weak = [c["name"] for c in (answer.get("checks") or []) if not c.get("passed")]
            if weak:
                st.markdown(f'<div class="so-note">{UI.esc(SECOND_TEXT["weakest"].format(list=", ".join(weak[:4])))}'
                            f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="so-when">{UI.esc(SECOND_TEXT["checked"].format(
            when=ago(answer.get("checked_at"))))}</div>', unsafe_allow_html=True)
        if st.button(SECOND_TEXT["again"], key=f"so_again_{checker}_{key}", width="stretch"):   # its own full-width row
            st.session_state[key] = {"state": SO.CHECKING}
            st.rerun()


def second_opinion(saved):
    """The whole section: its title, the three cards, the benchmark and the note that it never changes
    the Lab score."""
    job_text = (saved.get("inputs") or {}).get("text") or ""
    order = SO.visible_order(second_on("lever"), second_on("checker2"))   # VeriWorkly + Resume Matcher; the rest if on
    answers = {c: st.session_state.get(second_key(saved, c)) for c in order}
    head = SO.headline(answers)
    st.markdown(
        f'<div class="so-head"><div><span class="so-title"><span class="so-num">2</span>'
        f'{UI.esc(SECOND_TEXT["title"])}</span><span class="so-sub">{UI.esc(SECOND_TEXT["sub"].format(n=len(order)))}</span></div>'
        + (f'<div class="so-head-right{" grey" if not head.startswith("Both") else ""}">{UI.esc(head)}</div>'
           if head else "") + "</div>", unsafe_allow_html=True)
    cols = st.columns(len(order), gap="medium")
    for col, checker in zip(cols, order):
        with col:
            second_card(saved, checker, job_text)
    benchmark(saved, answers)
    st.markdown(f'<div class="so-section-note">{UI.esc(SECOND_TEXT["note"])}</div>', unsafe_allow_html=True)


def benchmark(saved, answers):
    """The same resume, the three checkers side by side. Read-only: the Lab's own row is the score the
    report already shows, and nothing here changes it."""
    res = saved.get("res") or {}
    rows = [(SECOND_TEXT["bench_lab"], round(res.get("score") or 0), SO.label_for(res.get("score")),
             SECOND_TEXT["bench_lab_note"])]
    for checker in SO.visible_order(second_on("lever"), second_on("checker2")):
        answer = answers.get(checker) or {}
        if answer.get("state") != SO.DONE or answer.get("score") is None:
            continue
        info = SO.CHECKERS[checker]
        ref = answer.get("reference")
        against = (f"{answer.get('difference')}" if answer.get("word") else
                   (f"vs {ref}" if ref is not None else "no comparison"))
        rows.append((info["name"], round(answer.get("score")),
                     SO.label_for(answer.get("score")), against))
    if len(rows) < 2:                     # nothing to compare yet: no empty table
        return
    st.markdown(f'<div class="so-bench-head"><b>{UI.esc(SECOND_TEXT["bench_title"])}</b>'
                f'<span>{UI.esc(SECOND_TEXT["bench_sub"])}</span></div>', unsafe_allow_html=True)
    cols = SECOND_TEXT["bench_cols"]
    head = "".join(f"<th>{UI.esc(c)}</th>" for c in cols[:4])
    body = "".join("<tr>" + "".join(f"<td>{UI.esc(str(v))}</td>" for v in row[:4]) + "</tr>" for row in rows)
    st.markdown(
        '<table class="so-bench" style="width:100%;border-collapse:collapse;font-size:0.86rem;margin:4px 0 2px">'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>',
        unsafe_allow_html=True)


def training_hooks(who):
    """Returns (trainer, training): the team's X on an issue card saves WHY the issue was set aside
    (the Lab's teaching signal), and the log is read back for the table and the CSV on the report."""
    def trainer(r, card, reason, note, evidence):
        store().add_training(who, r.get("_uid") or "", r.get("cv") or "", r.get("target") or "",
                             r.get("score"), card, reason, note, evidence)
        store().log(who, "training", card.get("name") or "",
                    T.LOG_DETAILS["training"].format(reason=D.TRAIN_REASONS.get(reason, reason)))

    def training():
        return store().training()

    return trainer, training


def check_view(who):
    train, training = training_hooks(who)
    head, right = st.columns([3, 1.6], vertical_alignment="center")
    head.markdown(UI.page_title(ADMIN_TEXT["check_title"], ADMIN_TEXT["check_sub"]), unsafe_allow_html=True)
    with right:
        mode = mode_switch()
    saved = D.current_result()
    if saved is None:
        pending = st.session_state.get("pending_check")       # the "Run check" press: a calm page, then the check
        main, side = st.columns([2.3, 1], gap="medium")        # the same shape as the form: nothing moves on screen
        if pending is not None:
            with main:
                checking_card()
            with side:
                side_panels()             # the two side cards stay where they are while the check works
            if not st.session_state.pop("pending_ready", False):
                st.session_state["pending_ready"] = True       # one quick run with the calm card on screen only:
                st.rerun()                                     # the check then starts with no form left behind it
            st.session_state.pop("pending_check", None)
            run(pending, who)
            return
        with main:
            with st.container(key="card-check"):
                inputs = check_form(mode)
                if inputs is not None:
                    st.session_state["pending_check"] = inputs    # the next run draws the clean card and checks
                    st.session_state.pop("pending_ready", None)    # ... after one run that shows only that card
                    st.rerun()
        with side:
            side_panels()
        return
    a, b = st.columns([3, 1], vertical_alignment="center")
    a.markdown(D.file_chip_html(saved["res"]).replace("margin-left: auto", ""), unsafe_allow_html=True)
    b.button(ADMIN_TEXT["new_check"], type="primary", on_click=D.start_new, key="new_check", width="stretch")
    if (mode == D.WITH_JOB) != bool(saved["with_job"]):
        again_card(mode, saved, who)
    D.render(saved["res"], saved["with_job"], saved["prev"],
             client=bool((saved.get("inputs") or {}).get("client")), swapped=saved.get("swap"),
             after_score=lambda: second_opinion(saved),       # the second opinion, under the Lab score
             set_aside=True,                                  # team only: X sets an issue aside and the score changes
             trainer=train, training=training)                # ... and teaches the Lab WHY (the teaching log)
    report_bug_control(saved, who)      # the team can report a wrong result: a screenshot and one sentence


# ---------------------------------------------------------------------------
# Benchmark: the user's original resume against the 1000Jobs resume for 1 to 5 jobs
# ---------------------------------------------------------------------------
BT = T.BENCH_TEXT


def bench_form(who):
    """The inputs: the user's name, the original resume, and for each job its title, description and 1000Jobs resume.
    -> the inputs for lab_benchmark.start when "Run benchmark" was pressed and everything is there, else None."""
    round_ = st.session_state.get("bench_round", 0)
    with st.container(key="card-bench-form"):
        name = st.text_input(BT["name"], placeholder=BT["name_hint"], key=f"bm_name_{round_}")
        original = st.file_uploader(BT["original"], type=["pdf"], key=f"bm_orig_{round_}")
        n = st.segmented_control(BT["jobs_count"], list(range(1, B.MAX_JOBS + 1)), default=1, key=f"bm_n_{round_}",
                                 selection_mode="single") or 1
    jobs = []
    for i in range(1, n + 1):
        with st.container(key=f"card-bench-job-{i}"):
            st.markdown(f'<div class="a-h3">{UI.esc(BT["job_n"].format(n=i))}</div>', unsafe_allow_html=True)
            title = st.text_input(BT["job_title"], placeholder=BT["job_title_hint"], key=f"bm_title_{round_}_{i}")
            text = st.text_area(BT["job_text"], placeholder=BT["job_text_hint"], height=150,
                                key=f"bm_text_{round_}_{i}")
            pdf = st.file_uploader(BT["job_resume"], type=["pdf"], key=f"bm_pdf_{round_}_{i}")
            jobs.append((title, text, pdf))
    if not st.button(BT["run"], type="primary", width="stretch", key="bm_run", icon=":material/arrow_forward:",
                     icon_position="right"):
        return None
    problems = []
    if original is None:
        problems.append(BT["need_original"])
    for i, (title, text, pdf) in enumerate(jobs, start=1):
        for what, value in (("title", title.strip()), ("text", text.strip()), ("pdf", pdf)):
            if not value:
                problems.append(BT["need_job"].format(n=i, what=BT["what"][what]))
    if problems:
        for problem in problems:
            st.error(problem)
        return None
    files = [original] + [pdf for _t, _x, pdf in jobs]
    for file in files:
        if not file.getvalue().lstrip()[:5] == b"%PDF-":
            st.error(BT["pdf_only"].format(name=file.name))
            return None
    return {"name": " ".join(name.split()) or B.guess_name(original.getvalue(), original.name),
            "original": (original.getvalue(), original.name),
            "jobs": [{"title": " ".join(t.split()), "text": x.strip(), "pdf": pdf.getvalue(), "filename": pdf.name}
                     for t, x, pdf in jobs]}


@st.fragment(run_every=2)
def bench_progress(run_id):
    """The progress message of a running benchmark (it looks again every 2 seconds; nothing else on the page moves)."""
    info = B.progress(run_id)
    if info is None or info["state"] != "running":
        st.rerun()                                   # finished (or lost): the whole page draws the result
        return
    total = max(1, info["total"])
    st.progress(min(1.0, info["done"] / total), text=BT["progress"].format(done=info["done"], total=total,
                                                                            message=info["message"]))


def bench_downloads(data, key):
    a, b, _ = st.columns([1.3, 1.3, 2])
    a.download_button(BT["download_png"], B.png_bytes(data), file_name=B.file_stem(data) + ".png", mime="image/png",
                      icon=":material/image:", key=f"bm_png_{key}", width="stretch")
    b.download_button(BT["download_pdf"], B.pdf_bytes(data), file_name=B.file_stem(data) + ".pdf",
                      mime="application/pdf", icon=":material/picture_as_pdf:", key=f"bm_pdf_{key}",
                      width="stretch", type="primary")


def bench_result(data, key, saved_note=""):
    """The tables of a finished benchmark, with the downloads."""
    n = len(data.get("jobs") or [])
    with st.container(key=f"card-bench-result-{key}"):
        st.markdown(f'<div class="a-h3">{UI.esc(BT["result_title"].format(name=data.get("name") or ""))}</div>'
                    f'<p class="a-sub">{UI.esc(BT["result_sub"].format(n=n, s=T.plural(n)))}</p>',
                    unsafe_allow_html=True)
        bench_downloads(data, key)
        st.markdown(B.all_tables_html(data), unsafe_allow_html=True)
        st.markdown(f'<div class="bm-note">{UI.esc(BT["legend"])}</div>'
                    + (f'<div class="bm-note">{UI.esc(saved_note)}</div>' if saved_note else ""), unsafe_allow_html=True)


def bench_start(inputs, who):
    store_ = store()

    def save(data):
        cid = store_.add_benchmark(data, who)
        orig, new = B.overall(data)
        n = len(data["jobs"])
        store_.log(who, "benchmark", data.get("name") or "",
                   T.LOG_DETAILS["benchmark"].format(jobs=n, s=T.plural(n), orig="-" if orig is None else f"{orig}%",
                                                     new="-" if new is None else f"{new}%"))
        return cid

    st.session_state["bench_run"] = B.start(inputs, who, save)


def bench_new():
    st.session_state.pop("bench_run", None)
    st.session_state["bench_round"] = st.session_state.get("bench_round", 0) + 1


def benchmark_view(who):
    st.markdown(UI.page_title(BT["title"], BT["sub"]), unsafe_allow_html=True)
    run_id = st.session_state.get("bench_run")
    info = B.progress(run_id) if run_id else None
    if run_id and info is None:
        st.session_state.pop("bench_run", None)       # the server restarted: nothing to show
    if info is None:
        inputs = bench_form(who)
        if inputs is not None:
            bench_start(inputs, who)
            st.rerun()
        return
    if info["state"] == "running":
        with st.container(key="card-bench-running"):
            st.markdown(f'<div class="a-h3">{UI.esc(BT["running_title"])}</div><p class="a-sub">'
                        f'{UI.esc(BT["running_sub"])}</p>', unsafe_allow_html=True)
            bench_progress(run_id)
        return
    st.button(BT["again"], icon=":material/add:", type="primary", key="bm_new", on_click=bench_new)
    if info["state"] == "error":
        with st.container(key="card-bench-error"):
            st.markdown(f'<div class="a-h3">{UI.esc(BT["error_title"])}</div>', unsafe_allow_html=True)
            st.error(info["error"])
        return
    bench_result(info["data"], run_id, BT["saved"] if info.get("history_id") else BT["not_saved"])


def benchmark_page(rec, cid, who):
    """History: a saved benchmark on its own (the tables are drawn again from the saved data). report_page has already
    drawn the "Back to the list" button."""
    data = (rec.get("parts") or {}).get("benchmark") or {}
    with st.container(key="card-open"):
        a, b = st.columns([3, 1.1], vertical_alignment="center")
        a.markdown(f'<div class="a-who">{UI.tag(BT["history_tag"], "info")}<div style="min-width:0">'
                   f'<div class="a-name">{UI.esc(candidate(rec))}</div><div class="a-meta"><span>'
                   f'{UI.esc(rec["file_name"])}</span><span>{when(rec["created_at"])}</span><span>'
                   f'{UI.esc(source_of(rec))}</span><span>{UI.esc(job_of(rec))}</span></div></div></div>',
                   unsafe_allow_html=True)
        b.button(ADMIN_TEXT["delete"], icon=":material/delete:", key="open_delete", width="stretch",
                 on_click=lambda: st.session_state.update(confirm_delete=[cid]))
        confirm_box(who)
    if data.get("jobs"):
        bench_result(data, f"h{cid}")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def filter_rows(rows, q="", label=None, job=None, dates=(), by=None):
    """The rows that match: search (candidate, file, job title, who checked it), a label, with / without job, a date
    range (from, to: both days included) and who checked it ("user" = the User page)."""
    q = (q or "").lower().strip()
    out = []
    for r in rows:
        if q and not any(q in (r.get(k) or "").lower() for k in ("candidate", "file_name", "job_title", "checked_by")):
            continue
        if label and label != ADMIN_TEXT["all"] and r.get("label") != label:
            continue
        if job == "with" and not r.get("with_job") or job == "without" and r.get("with_job"):
            continue
        day = day_of(r.get("created_at"))
        if dates and day and (day < dates[0] or (len(dates) > 1 and day > dates[-1])):
            continue
        if by and r.get("checked_by") != by:
            continue
        out.append(r)
    return out


def history_csv(rows):
    header = ["Date", "Candidate", "File", "Checked by", "Job", "Job title", "Score", "Label", "Needs review",
              "Reviewed by", "Reviewed at", "Review note", "Lead name", "Lead email"]
    return csv_bytes(header, [[r["created_at"], r.get("candidate"), r.get("file_name"), source_of(r),
                               "With job" if r.get("with_job") else "Without job", r.get("job_title"),
                               int(float(r["score"] or 0)), r.get("label"), "; ".join(r["review_reasons"]),
                               r.get("reviewed_by"), r.get("reviewed_at"), r.get("review_note"), r.get("lead_name"),
                               r.get("lead_email")] for r in rows])


def log_export(who, what, n):
    store().log(who, "export", T.LOG_DETAILS[f"export_{what}"],
                T.LOG_DETAILS["export"].format(what=T.LOG_DETAILS[f"export_{what}"], n=n, s=T.plural(n)))


def delete_records(ids, who):
    """Delete these checks for good (row, report and file), each one logged."""
    done = 0
    for cid in ids:
        row = store().delete_check(cid)
        if row is not None:
            done += 1
            store().log(who, "delete", candidate(row), T.LOG_DETAILS["delete"])
        st.session_state.pop(f"sel_{cid}", None)
    for k in ("confirm_delete", "open_check"):
        st.session_state.pop(k, None)
    st.session_state["deleted_note"] = ADMIN_TEXT["deleted"].format(n=done, s=T.plural(done))


def confirm_box(who):
    ids = st.session_state.get("confirm_delete") or []
    if not ids:
        return
    n = len(ids)
    with st.container(key="card-confirm"):
        st.markdown(f'<div class="a-h3">{ADMIN_TEXT["confirm_title"].format(n=n, s=T.plural(n))}</div>'
                    f'<p class="a-sub">{ADMIN_TEXT["confirm_text"].format(s=T.plural(n))}</p>', unsafe_allow_html=True)
        a, b, _ = st.columns([1.3, 1, 3])
        a.button(ADMIN_TEXT["confirm_yes"], type="primary", key="confirm_yes", on_click=delete_records, args=(ids, who))
        b.button(ADMIN_TEXT["cancel"], key="confirm_no", on_click=lambda: st.session_state.pop("confirm_delete", None))


def clear_history(who):
    """A fresh History and Needs review: every check goes, with its report and its kept resume file. The settings and
    the Activity log stay, and the clearing itself is written to the log."""
    gone = store().clear_checks()
    store().log(who, "delete", ADMIN_TEXT["clear_history"],
                T.LOG_DETAILS["clear_history"].format(checks=gone["checks"], files=gone["files"]))
    st.session_state["deleted_note"] = ADMIN_TEXT["clear_history_done"].format(checks=gone["checks"],
                                                                              files=gone["files"])
    for k in ("open_check", "confirm_delete", "hist_page"):
        st.session_state.pop(k, None)
    st.rerun()                                   # the list, the cards and the filters all start fresh


def clear_activity(who):
    """A fresh Activity log (the clearing itself is the first line of the new one)."""
    n = store().clear_log()
    store().log(who, "delete", ADMIN_TEXT["clear_log"], T.LOG_DETAILS["clear_log"].format(n=n))
    st.session_state["log_note"] = ADMIN_TEXT["clear_log_done"].format(n=n)
    st.rerun()


def mark_all_reviewed(who):
    """Every flagged resume leaves the list, marked with who did it. The reports stay in History."""
    rows = store().needs_review(P.review_rules())
    for r in rows:
        store().mark_reviewed(r["id"], who, "")
    store().log(who, "review", ADMIN_TEXT["clear_review"],
                T.LOG_DETAILS["review_bulk"].format(n=len(rows), s=T.plural(len(rows))))
    st.session_state["review_note"] = ADMIN_TEXT["clear_review_done"].format(n=len(rows), who=who)
    st.rerun()


def clear_button(key, label, icon=":material/delete_sweep:"):
    """The "Clear" button of a list: it only asks (the confirm card does the clearing, never one click)."""
    if st.button(label, key=f"clear_{key}", icon=icon, type="tertiary", width="stretch"):
        st.session_state[f"clear_ask_{key}"] = True
        st.rerun()


def clear_confirm(key, question, confirm_label, do):
    """The question a "Clear" button asks, full width: `do()` clears the list (and redraws the page)."""
    if not st.session_state.get(f"clear_ask_{key}"):
        return
    with st.container(key=f"card-clear-{key}"):
        st.markdown(f'<div class="a-h3">{UI.esc(question)}</div>', unsafe_allow_html=True)
        a, b, _ = st.columns([1.6, 1, 3], vertical_alignment="center")
        a.button(confirm_label, type="primary", key=f"clear_yes_{key}", width="stretch",
                 on_click=lambda: (st.session_state.pop(f"clear_ask_{key}", None), do()))
        b.button(ADMIN_TEXT["cancel"], key=f"clear_no_{key}", width="stretch",
                 on_click=lambda: st.session_state.pop(f"clear_ask_{key}", None))


def review_cell(r):
    if r.get("reviewed_by"):
        return UI.tag(ADMIN_TEXT["tag_reviewed"].format(who=r["reviewed_by"]), "ok")
    if r["review_reasons"]:
        return UI.tag(ADMIN_TEXT["tag_review"], "warn", "&#9432; ")
    return '<span class="a-muted">—</span>'


def select_page(ids):
    on = st.session_state.get("sel_all", False)
    for cid in ids:
        st.session_state[f"sel_{cid}"] = on


def history_table(rows, page_rows):
    head = st.container(key="hist_head").columns(HISTORY_COLS, vertical_alignment="center")
    head[0].checkbox("Select all", key="sel_all", label_visibility="collapsed", on_change=select_page,
                     args=([r["id"] for r in page_rows],))
    for col, name in zip(head[1:7], ("col_candidate", "col_date", "col_source", "col_job", "col_score", "col_review")):
        col.markdown(f'<span class="a-th">{ADMIN_TEXT[name]}</span>', unsafe_allow_html=True)
    for r in page_rows:
        with st.container(key=f"hrow_{r['id']}"):
            c = st.columns(HISTORY_COLS, vertical_alignment="center")
            c[0].checkbox("Select", key=f"sel_{r['id']}", label_visibility="collapsed")
            c[1].markdown(UI.who(candidate(r)), unsafe_allow_html=True)
            c[2].markdown(f'<div class="a-cell">{when(r["created_at"])}</div>', unsafe_allow_html=True)
            c[3].markdown(UI.tag(source_of(r), "grey" if r["checked_by"] == H.USER else "pri"), unsafe_allow_html=True)
            c[4].markdown(f'<div class="a-cell">{UI.esc(job_of(r))}</div>', unsafe_allow_html=True)
            if r["label"] == H.BENCHMARK:           # a benchmark: the tag and "original % -> 1000Jobs %"
                orig, new = B.overall((r.get("parts") or {}).get("benchmark") or {})
                change = B.signed(None if orig is None or new is None else new - orig)   # "+7%": the change, short
                c[5].markdown(f'<div class="a-who">{UI.tag(BT["history_tag"], "info")}<span class="a-cell" title="'
                              f'{UI.esc(BT["history_col"].format(orig=orig, new=new))}">{UI.esc(change)}</span></div>',
                              unsafe_allow_html=True)
            else:
                c[5].markdown(f'<div class="a-who">{UI.pill(r["score"], r["label"])}<span class="a-cell">'
                              f'{UI.esc(r["label"])}</span></div>', unsafe_allow_html=True)
            c[6].markdown(review_cell(r), unsafe_allow_html=True)
            c[7].button(ADMIN_TEXT["open"], icon=":material/chevron_right:", key=f"hopen_{r['id']}", type="tertiary",
                        on_click=lambda cid=r["id"]: st.session_state.update(open_check=cid), help=ADMIN_TEXT["open"])


def history_view(who):
    if st.session_state.get("open_check"):
        return report_page(st.session_state["open_check"], who)
    head, right = st.columns([3, 1], vertical_alignment="center")
    head.markdown(UI.page_title(ADMIN_TEXT["history_title"], ADMIN_TEXT["history_sub"]), unsafe_allow_html=True)
    with right:
        st.button(ADMIN_TEXT["new_check_short"], icon=":material/add:", type="primary", key="hist_new",
                  on_click=lambda: (go("check"), D.start_new()), width="stretch")
    rows = store().history(rules=P.review_rules())
    if rows:
        a, _b = st.columns([1, 4])
        with a:
            clear_button("history", ADMIN_TEXT["clear_history"])
        clear_confirm("history", ADMIN_TEXT["clear_history_ask"], ADMIN_TEXT["clear_history_yes"],
                      lambda: clear_history(who))
    n_user = sum(r["checked_by"] == H.USER for r in rows)
    scored = [r for r in rows if r["label"] != H.BENCHMARK]            # a benchmark is not a resume score
    avg = round(sum(r["score"] or 0 for r in scored) / len(scored)) if scored else 0   # a whole number already
    n_review = sum(bool(r["review_reasons"]) and not r["reviewed_by"] for r in rows)
    st.markdown(UI.stat_cards([(ADMIN_TEXT["stat_checks"], len(rows), ""), (ADMIN_TEXT["stat_avg"], avg, ""),
                               (ADMIN_TEXT["stat_user"], n_user, ""), (ADMIN_TEXT["stat_review"], n_review, "warn")]),
                unsafe_allow_html=True)
    if st.session_state.get("deleted_note"):
        st.success(st.session_state.pop("deleted_note"))
    with st.container(key="card-hist"):
        if not rows:
            st.markdown(UI.empty("&#128203;", ADMIN_TEXT["no_history"]), unsafe_allow_html=True)
            return
        a, b = st.columns([1.5, 2], vertical_alignment="center")
        q = a.text_input(ADMIN_TEXT["search"], placeholder=ADMIN_TEXT["search"], label_visibility="collapsed",
                         key="hist_search", icon=":material/search:")
        with b:
            present = [x for x in LABELS if any(r["label"] == x for r in rows)]
            label = st.pills("Label", (ADMIN_TEXT["all"],) + tuple(present), key="hist_label",
                             label_visibility="collapsed", default=ADMIN_TEXT["all"])
        admins = sorted({r["checked_by"] for r in rows if r["checked_by"] != H.USER})
        f1, f2, f3, f4, f5 = st.columns([1.3, 1.5, 1.3, 1.05, 1.25], vertical_alignment="bottom")
        job = f1.selectbox(ADMIN_TEXT["f_job"], ("all", "with", "without"), key="hist_job",
                           format_func=lambda v: ADMIN_TEXT[{"all": "f_job_all", "with": "f_job_with",
                                                             "without": "f_job_without"}[v]])
        dates = f2.date_input(ADMIN_TEXT["f_dates"], value=(), key="hist_dates", format="YYYY-MM-DD")
        by = f3.selectbox(ADMIN_TEXT["f_by"], [None, H.USER] + admins, key="hist_by",
                          format_func=lambda v: ADMIN_TEXT["f_by_all"] if v is None else
                          ADMIN_TEXT["f_by_user"] if v == H.USER else v)
        shown = filter_rows(rows, q, label, job, tuple(dates or ()), by)
        selected = [r["id"] for r in shown if st.session_state.get(f"sel_{r['id']}")]
        export = [r for r in shown if r["id"] in selected] or shown
        f4.download_button(ADMIN_TEXT["export"], history_csv(export), icon=":material/download:",
                           file_name=f"1000Jobs ATS Lab history {dt.date.today()}.csv", mime="text/csv",
                           key="hist_export", on_click=log_export, args=(who, "history", len(export)),
                           width="stretch")
        f5.button(ADMIN_TEXT["delete_selected"].format(n=len(selected)), icon=":material/delete:", key="hist_delete",
                  disabled=not selected, width="stretch",
                  on_click=lambda ids=tuple(selected): st.session_state.update(confirm_delete=list(ids)))
        confirm_box(who)
        if not shown:
            st.markdown(UI.empty("&#128269;", ADMIN_TEXT["no_match"]), unsafe_allow_html=True)
            return
        pages = (len(shown) - 1) // PAGE_ROWS + 1
        page = min(st.session_state.get("hist_page", 1), pages)
        history_table(shown, shown[(page - 1) * PAGE_ROWS:page * PAGE_ROWS])
        p1, p2, p3, p4 = st.columns([3, 1.2, 1, 1], vertical_alignment="center")
        p1.caption(ADMIN_TEXT["shown"].format(n=len(shown), total=len(rows)) + " · " +
                   ADMIN_TEXT["page"].format(n=page, pages=pages))
        p3.button(ADMIN_TEXT["prev_page"], key="hist_prev", disabled=page <= 1,
                  on_click=lambda: st.session_state.update(hist_page=page - 1))
        p4.button(ADMIN_TEXT["next_page"], key="hist_next", disabled=page >= pages,
                  on_click=lambda: st.session_state.update(hist_page=page + 1))


def report_actions(rec, cid):
    """Download the report PDF, the comparison PDF and the resume file (when still kept)."""
    cache = st.session_state.setdefault("pdf_cache", {})
    name = rec["candidate"] or rec["file_name"]
    cols = st.columns(3)
    data, _ = D.pdf_of(rec["report_doc"], cache)
    if data:
        cols[0].download_button(D.REPORT_TEXT["download"], data, file_name=f"1000Jobs ATS Lab - {name} - "
                                f"{rec['created_at'][:10]}.pdf", mime="application/pdf", key=f"pdf_{cid}",
                                type="primary", width="stretch")
    else:
        cols[0].download_button(D.REPORT_TEXT["download_html"], rec["report_doc"].encode("utf-8"), width="stretch",
                                file_name=f"1000Jobs ATS Lab - {name}.html", mime="text/html", key=f"html_{cid}")
    if rec.get("comparison_doc"):
        cdata, _ = D.pdf_of(rec["comparison_doc"], cache)
        if cdata:
            cols[1].download_button(ADMIN_TEXT["download_cmp"], cdata, mime="application/pdf", key=f"cmp_{cid}",
                                    width="stretch",
                                    file_name=f"1000Jobs ATS Lab - {name} - Comparison - {rec['created_at'][:10]}.pdf")
    pdf = store().file_of(cid)
    if pdf:
        cols[2].download_button(ADMIN_TEXT["download_file"], pdf, file_name=rec["file_name"] or "resume.pdf",
                                mime="application/pdf", key=f"file_{cid}", width="stretch")
    else:
        cols[2].caption(ADMIN_TEXT["file_gone"].format(days=P.setting("file_days")) if rec["file_deleted_at"]
                        else ADMIN_TEXT["file_none"])
    if rec.get("lead_email"):
        st.caption(ADMIN_TEXT["contact"].format(name=rec["lead_name"], email=rec["lead_email"]))


def show_report(cid):
    """A past report as it was made, with its downloads (Needs review opens it under the card)."""
    rec = store().get(cid)
    if rec is None:
        return
    report_actions(rec, cid)
    D.html_block(rec["report_body"].removeprefix('<div class="rp">').removesuffix("</div>"))


def report_page(cid, who):
    """History: one past report on its own, with "Back to the list" and "Delete record"."""
    st.button(ADMIN_TEXT["back"], icon=":material/arrow_back:", type="tertiary", key="hist_back",
              on_click=lambda: st.session_state.pop("open_check", None))
    rec = store().get(cid)
    if rec is None:
        st.session_state.pop("open_check", None)
        return st.info(ADMIN_TEXT["no_match"])
    if rec.get("label") == H.BENCHMARK:
        return benchmark_page(rec, cid, who)
    rec["review_reasons"] = H.reasons_for(H.facts_of(rec), P.review_rules())
    with st.container(key="card-open"):
        a, b = st.columns([3, 1.1], vertical_alignment="center")
        a.markdown(f'<div class="a-who">{UI.ring(rec["score"], rec["label"], 84, 7)}<div style="min-width:0">'
                   f'<div class="a-name">{UI.esc(candidate(rec))}</div><div class="a-meta"><span>'
                   f'{UI.esc(rec["file_name"])}</span><span>{when(rec["created_at"])}</span><span>'
                   f'{UI.esc(source_of(rec))}</span><span>{UI.esc(job_of(rec))}</span></div>'
                   + (f'<div class="a-flag">{review_cell(rec)}</div>' if rec["review_reasons"] or rec["reviewed_by"] else "")
                   + '</div></div>', unsafe_allow_html=True)
        b.button(ADMIN_TEXT["delete"], icon=":material/delete:", key="open_delete", width="stretch",
                 on_click=lambda: st.session_state.update(confirm_delete=[cid]))
        confirm_box(who)
        report_actions(rec, cid)
    D.html_block(rec["report_body"].removeprefix('<div class="rp">').removesuffix("</div>"))


# ---------------------------------------------------------------------------
# Needs review
# ---------------------------------------------------------------------------
def rules_text(rules):
    parts = [T.REVIEW_TEXT["rule_score"].format(n=rules["score"])]
    if rules["critical"]:
        parts.append(T.REVIEW_TEXT["rule_critical"])
    if rules["contact"]:
        parts.append(T.REVIEW_TEXT["rule_contact"])
    return ", ".join(parts[:-1]) + (" or " if len(parts) > 1 else "") + parts[-1]


def reason_tags(reasons):
    """One tag per reason, and one per Critical issue ("Template is hard for ATS to read", ...), as in the design."""
    lead = T.REVIEW_TEXT["critical"].split("{")[0]
    out = []
    for x in reasons:
        out += x[len(lead):].split("; ") if x.startswith(lead) else [x]
    return out


def mark_reviewed(r, who):
    note = st.session_state.get(f"note_{r['id']}", "")
    store().mark_reviewed(r["id"], who, note)
    store().log(who, "review", candidate(r), T.LOG_DETAILS["review"].format(note=" ".join(note.split()))
                if note.strip() else T.LOG_DETAILS["review_no_note"])
    if st.session_state.get("open_check") == r["id"]:
        st.session_state.pop("open_check", None)


def review_card(r, who):
    with st.container(key=f"card-rev_{r['id']}"):
        ring, info, act = st.columns([0.95, 3.3, 1.45], vertical_alignment="top")
        ring.markdown(UI.ring(r["score"], r["label"], 104, 9), unsafe_allow_html=True)
        tags = "".join(UI.tag(x, "bad" if x.startswith(T.REVIEW_TEXT["score"].split("{")[0]) else "warn")
                       for x in reason_tags(r["review_reasons"]))
        src = ADMIN_TEXT["from_user"] if r["checked_by"] == H.USER else ADMIN_TEXT["by_admin"].format(who=r["checked_by"])
        lead = (f'<div class="a-meta" style="margin-top:8px"><span>&#128100; '
                f'{UI.esc(ADMIN_TEXT["lead"].format(name=r["lead_name"] or "", email=r["lead_email"]))}</span></div>'
                if r.get("lead_email") else "")
        info.markdown(f'<div class="a-name">{UI.esc(candidate(r))}</div><div class="a-meta"><span>'
                      f'{UI.esc(r["file_name"])}</span><span>{when(r["created_at"])}</span><span>{UI.esc(src)}</span>'
                      f'</div>{lead}<div class="a-caps" style="margin-top:14px">{ADMIN_TEXT["why_flagged"]}</div>'
                      f'<div class="a-flag">{tags}</div>', unsafe_allow_html=True)
        info.write("")
        info.text_area(ADMIN_TEXT["note"], key=f"note_{r['id']}", placeholder=ADMIN_TEXT["note_hint"], height=80)
        opened = st.session_state.get("open_check") == r["id"]
        act.button(ADMIN_TEXT["open"], icon=":material/open_in_new:", key=f"open_{r['id']}", width="stretch",
                   on_click=lambda: st.session_state.update(open_check=None if opened else r["id"]))
        act.button(ADMIN_TEXT["reviewed"], icon=":material/check:", key=f"rev_{r['id']}", type="primary",
                   width="stretch", on_click=mark_reviewed, args=(r, who))
    if opened:
        show_report(r["id"])


def review_view(who):
    rules = P.review_rules()
    rows = store().needs_review(rules)
    head, right = st.columns([3, 1], vertical_alignment="center")
    head.markdown(UI.page_title(ADMIN_TEXT["review_title"],
                                ADMIN_TEXT["review_sub"].format(rules=rules_text(rules))), unsafe_allow_html=True)
    if rows:
        with right:
            clear_button("review", ADMIN_TEXT["clear_review"], icon=":material/done_all:")
        clear_confirm("review", ADMIN_TEXT["clear_review_ask"].format(n=len(rows)),
                      ADMIN_TEXT["clear_review_yes"], lambda: mark_all_reviewed(who))
    if st.session_state.get("review_note"):
        st.success(st.session_state.pop("review_note"))
    if not rows:
        with st.container(key="card-noreview"):
            st.markdown(UI.empty("&#10003;", ADMIN_TEXT["no_review"], ADMIN_TEXT["no_review_sub"]),
                        unsafe_allow_html=True)
        return
    for r in rows:
        review_card(r, who)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def shown_value(key, value):
    kind = S.SETTINGS[key][0]
    if kind is bool:
        return "on" if value else "off"
    if key == "file_days":
        return T.DAYS.format(n=value)
    return str(value)


def setting_row(key, widget, saved):
    """One setting: its title and description on the left, its control on the right."""
    title, sub = T.SETTINGS_TEXT[key]
    a, b = st.columns([3, 1.25], vertical_alignment="center")
    a.markdown(f'<div class="a-set"><div class="t">{UI.esc(title)}</div>'
               + (f'<div class="s">{UI.esc(sub)}</div>' if sub else "") + "</div>", unsafe_allow_html=True)
    now = S.get(key, saved)
    with b:
        if widget == "number":
            low, high = S.LIMITS[key]
            return st.number_input(title, min_value=low, max_value=high, value=now, step=1, key=f"set_{key}",
                                   label_visibility="collapsed")
        return st.toggle(title, value=now, key=f"set_{key}", label_visibility="collapsed")


def save_settings(values, saved, who):
    """Save the changed values (each one logged). -> (changed names, errors)."""
    changed, errors = [], []
    for key, value in values.items():
        old = S.get(key, saved)
        try:
            new = S.parse(key, value)
        except (TypeError, ValueError) as e:
            errors.append(f"{T.SETTINGS_TEXT[key][0]}: {e}")
            continue
        if new != old:
            store().save_setting(key, new, who)
            store().log(who, "settings", T.SETTINGS_TEXT[key][0], T.LOG_DETAILS["settings"].format(
                name=T.SETTINGS_TEXT[key][0], old=shown_value(key, old), new=shown_value(key, new)).split(": ", 1)[1])
            changed.append(key)
    return changed, errors


def reset_settings(who):
    saved = store().saved_settings()
    for key in saved:
        store().clear_setting(key)
    if saved:
        store().log(who, "settings", ADMIN_TEXT["settings_title"], T.LOG_DETAILS["settings_reset"])
    for key in S.SETTINGS:                      # the controls show the server values again
        st.session_state.pop(f"set_{key}", None)


def settings_view(who):
    saved = store().saved_settings()
    with st.container(key="settings-wrap"):
        st.markdown(UI.page_title(ADMIN_TEXT["settings_title"], ADMIN_TEXT["settings_sub"]), unsafe_allow_html=True)
        st.write("")
        with st.form("admin_settings", border=False):
            values = {}
            with st.container(key="card-set-files"):
                values["file_days"] = setting_row("file_days", "number", saved)
            with st.container(key="card-set-daily"):
                values["daily_checks"] = setting_row("daily_checks", "number", saved)
            with st.container(key="card-set-rules"):
                st.markdown(f'<div class="a-h3">{ADMIN_TEXT["rules_title"]}</div><p class="a-sub">'
                            f'{ADMIN_TEXT["rules_sub"]}</p>', unsafe_allow_html=True)
                values["review_score"] = setting_row("review_score", "number", saved)
                values["review_critical"] = setting_row("review_critical", "toggle", saved)
                values["review_contact"] = setting_row("review_contact", "toggle", saved)
            with st.container(key="card-set-second"):
                st.markdown(f'<div class="a-h3">{ADMIN_TEXT["second_title"]}</div><p class="a-sub">'
                            f'{ADMIN_TEXT["second_sub"]}</p>', unsafe_allow_html=True)
                values["second_matcher"] = setting_row("second_matcher", "toggle", saved)
                values["second_checker2"] = setting_row("second_checker2", "toggle", saved)
                values["second_engine"] = setting_row("second_engine", "toggle", saved)
                values["second_lever"] = setting_row("second_lever", "toggle", saved)
            with st.container(key="card-set-bugs"):
                st.markdown(f'<div class="a-h3">{ADMIN_TEXT["bugs_title"]}</div><p class="a-sub">'
                            f'{ADMIN_TEXT["bugs_sub"]}</p>', unsafe_allow_html=True)
                values["bug_image_days"] = setting_row("bug_image_days", "number", saved)
            with st.container(key="card-set-links"):
                st.markdown(f'<div class="a-h3">{ADMIN_TEXT["links_title"]}</div><p class="a-sub">'
                            f'{ADMIN_TEXT["links_sub"]}</p>', unsafe_allow_html=True)
                for key in ("premium_url", "booking_url", "site_url"):
                    values[key] = st.text_input(T.SETTINGS_TEXT[key][0], value=S.get(key, saved), key=f"set_{key}")
            with st.container(key="card-set-leads"):
                values["collect_leads"] = setting_row("collect_leads", "toggle", saved)
            with st.expander(ADMIN_TEXT["server_title"]):
                facts = {"admins": len(S.admin_accounts()), "key": ADMIN_TEXT["yes" if S.apply_api_key() else "no"],
                         "folder": store().folder, "checks": len(store().history()), "version": T.APP_VERSION}
                st.markdown('<ul class="a-server">' + "".join(f"<li>{UI.esc(line.format(**facts))}</li>"
                                                              for line in ADMIN_TEXT["server"]) + "</ul>",
                            unsafe_allow_html=True)
            a, _, b = st.columns([1.5, 1, 1.3])
            reset = a.form_submit_button(ADMIN_TEXT["reset"], width="stretch")
            save = b.form_submit_button(ADMIN_TEXT["save"], type="primary", width="stretch")
        if save:
            changed, errors = save_settings(values, saved, who)
            for e in errors:
                st.error(e)
            if not errors:
                st.success(ADMIN_TEXT["settings_saved"] if changed else ADMIN_TEXT["nothing_changed"])
        if reset:
            reset_settings(who)
            st.success(ADMIN_TEXT["settings_reset"])
            st.rerun()


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------
LOG_TONE = {"check": "pri", "review": "ok", "settings": "grey", "delete": "bad", "export": "warn", "sign_in": "grey"}
LOG_CHIPS = ("check", "review", "settings", "delete")


def filter_log(rows, q="", kind=None, dates=()):
    q = (q or "").lower().strip()
    out = []
    for r in rows:
        if kind and r["kind"] != kind:
            continue
        action = T.LOG_KINDS.get(r["kind"], ("", r["kind"]))[1]
        if q and not any(q in (x or "").lower() for x in (r["admin"], r["target"], r["details"], action)):
            continue
        day = day_of(r["at"])
        if dates and day and (day < dates[0] or (len(dates) > 1 and day > dates[-1])):
            continue
        out.append(r)
    return out


def log_csv(rows):
    return csv_bytes(["When", "Admin", "Action", "Target", "Details"],
                     [[r["at"], r["admin"], T.LOG_KINDS.get(r["kind"], ("", r["kind"]))[1], r["target"], r["details"]]
                      for r in rows])


def log_table(rows):
    body = "".join(
        f'<tr><td><div class="d">{UI.esc(r["at"][11:16])}</div><div class="s">{when(r["at"]).split(",")[0]}</div></td>'
        f'<td>{UI.who(r["admin"], primary=True, bold=False)}</td>'
        f'<td>{UI.tag(T.LOG_KINDS.get(r["kind"], ("", r["kind"]))[1], LOG_TONE.get(r["kind"], "grey"))}</td>'
        f'<td><div class="d">{UI.esc(r["target"])}</div><div class="s">{UI.esc(r["details"]) or "—"}</div></td></tr>'
        for r in rows)
    head = "".join(f'<th class="a-th">{ADMIN_TEXT[k]}</th>' for k in ("col_when", "col_admin", "col_action",
                                                                         "col_details"))
    return f'<div class="a-table-wrap"><table class="a-table"><tr>{head}</tr>{body}</table></div>'


def log_view(who):
    rows = store().activity()
    head, right = st.columns([3, 1], vertical_alignment="center")
    head.markdown(UI.page_title(ADMIN_TEXT["log_title"], ADMIN_TEXT["log_sub"]), unsafe_allow_html=True)
    today = dt.date.today()
    count = lambda kind: sum(r["kind"] == kind for r in rows)
    st.markdown(UI.stat_cards([(ADMIN_TEXT["stat_today"], sum(day_of(r["at"]) == today for r in rows), "edge pri"),
                               (ADMIN_TEXT["stat_reviewed"], count("review"), "edge ok"),
                               (ADMIN_TEXT["stat_settings"], count("settings"), "edge grey"),
                               (ADMIN_TEXT["stat_deleted"], count("delete"), "edge bad")]), unsafe_allow_html=True)
    with st.container(key="card-log"):
        if not rows:
            right.download_button(ADMIN_TEXT["export"], log_csv([]), icon=":material/download:", disabled=True,
                                  file_name="activity.csv", key="log_export", width="stretch")
            st.markdown(UI.empty("&#128221;", ADMIN_TEXT["no_log"]), unsafe_allow_html=True)
            return
        a, b, c = st.columns([1.5, 1.35, 2.15], vertical_alignment="center")
        q = a.text_input(ADMIN_TEXT["log_search"], placeholder=ADMIN_TEXT["log_search"], label_visibility="collapsed",
                         key="log_search", icon=":material/search:")
        dates = b.date_input(ADMIN_TEXT["f_dates"], value=(), key="log_dates", format="YYYY-MM-DD",
                             label_visibility="collapsed")
        with c:
            kind = st.pills("Action", ("all",) + LOG_CHIPS, key="log_kind", label_visibility="collapsed",
                            format_func=lambda k: ADMIN_TEXT["all"] if k == "all" else T.LOG_KINDS[k][0], default="all")
        if st.session_state.get("log_note"):
            st.success(st.session_state.pop("log_note"))
        left, _r = st.columns([1, 4])
        with left:
            clear_button("log", ADMIN_TEXT["clear_log"])
        clear_confirm("log", ADMIN_TEXT["clear_log_ask"], ADMIN_TEXT["clear_log_yes"],
                      lambda: clear_activity(who))
        shown = filter_log(rows, q, None if kind in (None, "all") else kind, tuple(dates or ()))
        right.download_button(ADMIN_TEXT["export"], log_csv(shown), icon=":material/download:", key="log_export",
                              file_name=f"1000Jobs ATS Lab activity {today}.csv", mime="text/csv", width="stretch",
                              on_click=log_export, args=(who, "log", len(shown)))
        if not shown:
            st.markdown(UI.empty("&#128269;", ADMIN_TEXT["no_log_match"]), unsafe_allow_html=True)
            return
        st.markdown(log_table(shown[:LOG_ROWS]), unsafe_allow_html=True)
        if len(shown) > LOG_ROWS:
            st.caption(ADMIN_TEXT["shown"].format(n=LOG_ROWS, total=len(shown)).replace("checks", "actions"))


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def show_image(data):
    """One screenshot as wide as its card, on this version of Streamlit."""
    try:
        st.image(data, use_container_width=True)
    except TypeError:                       # an older or newer Streamlit: the plain call always works
        st.image(data)


# ---------------------------------------------------------------------------
# Bug reports (Admin only): "Report a bug" on a report, and the Bug audit page
# ---------------------------------------------------------------------------
# The screenshot, the sentence and the Lab's own result text go to the AI (never the resume itself).
# Nothing here can change the ATS Lab score: the AI only writes text for the team to read, and a fix may
# affect a score only after the team records every step of the checklist and the reference test passes.
BUG_STEP_COLUMNS = BG.STEP_COLUMNS          # a step name -> its column, defined once in lab_bugs.py


def bug_save(res, who, words, image, mime):
    """Save one bug report and ask the AI about it. -> the new bug id."""
    with st.spinner(T.BUG_TEXT["sending"]):
        ai = BG.ask_ai(image, mime, words, BG.result_text(res))
    bid = store().add_bug({"who": who, "kind": "bug", "description": words,
                           "check_id": str(res.get("_uid") or ""), "cv": res.get("cv") or "",
                           "target": res.get("target") or "", "score": res.get("score"),
                           "report": BG.result_text(res), "ai_model": ai.get("model") or "",
                           "ai_explanation": ai.get("explanation") or "", "ai_fix": ai.get("fix") or "",
                           "ai_error": ai.get("error") or ai.get("why") or ""},
                          screenshot=image, mime=mime)
    store().log(who, "bug", f"#{bid}", (words or "")[:120])
    if ai.get("error"):
        st.warning(T.BUG_TEXT["ai_failed"].format(why=ai.get("why") or ai.get("error")))
    return bid


def report_bug_control(saved, who):
    """The "Report a bug" box under a report: a screenshot and one sentence."""
    res = (saved or {}).get("res") or {}
    tag = str(res.get("_uid") or res.get("cv") or "report")
    with st.expander(T.BUG_TEXT["report_open"]):
        st.markdown(f'<p class="a-sub">{UI.esc(T.BUG_TEXT["report_hint"])}</p>', unsafe_allow_html=True)
        shot = st.file_uploader(T.BUG_TEXT["screenshot"], type=["png", "jpg", "jpeg", "webp"], key=f"bug_shot_{tag}")
        words = st.text_input(T.BUG_TEXT["sentence"], key=f"bug_words_{tag}")
        if st.button(T.BUG_TEXT["send"], key=f"bug_send_{tag}", type="primary"):
            image = shot.getvalue() if shot is not None else b""
            if not (words or "").strip():
                st.warning(T.BUG_TEXT["need_words"])
                return
            ok, why = BG.allowed_image(getattr(shot, "type", ""), len(image))
            if not ok:
                st.warning({"type": T.BUG_TEXT["wrong_type"], "empty": T.BUG_TEXT["need_image"],
                            "big": T.BUG_TEXT["too_big"].format(mb=round(len(image) / 1048576, 1),
                                                                max=BG.MAX_IMAGE_MB)}[why])
                return
            bid = bug_save(res, who, words, image, getattr(shot, "type", ""))
            if bid:
                st.success(T.BUG_TEXT["saved"].format(n=bid))


def bug_decide(bug, state, who, note=""):
    """Approve / reject / mark fixed, and write it in the Activity log."""
    store().set_bug_state(bug["id"], state, who, note)
    store().log(who, "bug", f'#{bug["id"]}', T.BUG_TEXT["state_" + state])
    st.rerun()


def bug_step(bug, step, who):
    """Record one step of the fix checklist (the fix, the golden set, the reference test)."""
    store().set_bug_step(bug["id"], step)
    store().log(who, "bug", f'#{bug["id"]}', dict(BG.FIX_STEPS)[step])
    st.rerun()


def bug_ask_again(bug, who):
    """Ask the AI again about a bug it could not answer before (the screenshot is still stored)."""
    image, mime = store().bug_image(bug["id"])
    if not image:
        st.warning(T.BUG_TEXT["image_gone"])
        return
    with st.spinner(T.BUG_TEXT["sending"]):
        ai = BG.ask_ai(image, mime, bug.get("description") or "", bug.get("report") or "")
    store().set_bug_ai(bug["id"], ai)
    store().log(who, "bug", f'#{bug["id"]}', "Asked the AI again")
    st.rerun()


def bug_grid(bugs):
    """The screenshots of the bugs on screen: press Open to see one full size."""
    with_image = [b for b in bugs if b.get("has_image")]
    if not with_image:
        return
    st.markdown(f'<div class="a-h3">{UI.esc(T.BUG_TEXT["grid_title"])}</div>'
                f'<p class="a-sub">{UI.esc(T.BUG_TEXT["grid_sub"])}</p>', unsafe_allow_html=True)
    cols = st.columns(4, gap="small")
    for i, bug in enumerate(with_image[:8]):
        with cols[i % 4]:
            image, _ = store().bug_image(bug["id"])
            if image:
                show_image(image)
            if st.button(f'{T.BUG_TEXT["open"]} #{bug["id"]}', key=f'bug_open_{bug["id"]}', width="stretch"):
                st.session_state["bug_open"] = bug["id"]
                st.rerun()
    opened = st.session_state.get("bug_open")
    if opened:
        image, _ = store().bug_image(opened)
        if image:
            st.markdown(f'<div class="a-h3">#{UI.esc(opened)}</div>', unsafe_allow_html=True)
            show_image(image)
        if st.button(T.BUG_TEXT["close"], key="bug_close"):
            st.session_state.pop("bug_open", None)
            st.rerun()


def bug_card(bug, who, days):
    """One bug: what happened, what the AI says, the decision, and the fix checklist."""
    bid = bug["id"]
    state = BG.state_of(bug)
    title = f'#{bid} · {T.BUG_TEXT["state_" + state]} · {bug.get("cv") or ""}'
    with st.expander(title):
        facts = [(T.BUG_TEXT["reporter"], bug.get("who")), (T.BUG_TEXT["when"], when(bug.get("created_at"))),
                 (T.BUG_TEXT["resume"], bug.get("cv")), (T.BUG_TEXT["score"], bug.get("score"))]
        st.markdown('<div class="a-sub">' + " · ".join(f"{UI.esc(k)}: {UI.esc(v)}" for k, v in facts
                                                       if v not in (None, "")) + "</div>", unsafe_allow_html=True)
        st.markdown(f'<div class="a-h3">{UI.esc(T.BUG_TEXT["description"])}</div>'
                    f'<p class="a-sub">{UI.esc(bug.get("description") or "")}</p>', unsafe_allow_html=True)
        image, _ = store().bug_image(bid) if bug.get("has_image") else (None, "")
        if image:
            show_image(image)
            st.caption(T.BUG_TEXT["image_kept"].format(date=BG.keep_until(bug, days) or "")
                       if state in BG.CLOSED else T.BUG_TEXT["image_open"])
        else:
            st.caption(T.BUG_TEXT["image_gone"])
        st.markdown(f'<div class="a-h3">{UI.esc(T.BUG_TEXT["ai_title"])}</div>', unsafe_allow_html=True)
        if bug.get("ai_explanation") or bug.get("ai_fix"):
            st.markdown(f'<p class="a-sub"><b>{UI.esc(T.BUG_TEXT["ai_explanation"])}:</b> '
                        f'{UI.esc(bug.get("ai_explanation") or "")}<br>'
                        f'<b>{UI.esc(T.BUG_TEXT["ai_fix"])}:</b> {UI.esc(bug.get("ai_fix") or "")}</p>',
                        unsafe_allow_html=True)
        elif bug.get("ai_error"):
            st.markdown(f'<p class="a-sub">{UI.esc(T.BUG_TEXT["ai_failed"].format(why=bug.get("ai_error")))}</p>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<p class="a-sub">{UI.esc(T.BUG_TEXT["ai_none"])}</p>', unsafe_allow_html=True)
        if bug.get("has_image") and st.button(T.BUG_TEXT["ask_again"], key=f"bug_ai_{bid}"):
            bug_ask_again(bug, who)
        st.markdown(f'<details><summary>{UI.esc(T.BUG_TEXT["result"])}</summary>'
                    f'<pre style="white-space:pre-wrap;font-size:.8rem">{UI.esc(bug.get("report") or "")}</pre>'
                    f'</details>', unsafe_allow_html=True)
        note = st.text_input(T.BUG_TEXT["note"], key=f"bug_note_{bid}")
        a, b, c = st.columns(3)
        if a.button(T.BUG_TEXT["approve"], key=f"bug_yes_{bid}", width="stretch"):
            bug_decide(bug, BG.APPROVED, who, note)
        if b.button(T.BUG_TEXT["reject"], key=f"bug_no_{bid}", width="stretch"):
            bug_decide(bug, BG.REJECTED, who, note)
        if c.button(T.BUG_TEXT["mark_fixed"], key=f"bug_fixed_{bid}", width="stretch"):
            bug_decide(bug, BG.FIXED, who, note)
        st.markdown(f'<div class="a-h3">{UI.esc(T.BUG_TEXT["steps_title"])}</div>'
                    f'<p class="a-sub">{UI.esc(T.BUG_TEXT["steps_sub"])}</p>', unsafe_allow_html=True)
        for step, label in BG.FIX_STEPS:
            done = bool(bug.get(BUG_STEP_COLUMNS[step]))
            cols = st.columns([3, 1], vertical_alignment="center")
            cols[0].markdown(f'<div class="a-sub">{"&#10003;" if done else "&#9675;"} {UI.esc(label)} - '
                             f'{UI.esc(T.BUG_TEXT["step_done"] if done else T.BUG_TEXT["step_todo"])}</div>',
                             unsafe_allow_html=True)
            if not done and cols[1].button(T.BUG_TEXT["step_button"], key=f"bug_step_{step}_{bid}",
                                           width="stretch"):
                bug_step(bug, step, who)
        if BG.ready_for_score(bug):
            st.success(T.BUG_TEXT["ready"])


def bugs_view(who):
    """Bug audit (Admin only): the screenshots, every detail, and the decisions."""
    days = P.setting("bug_image_days")
    store().cleanup_bug_images(days)                 # the screenshot rule, applied whenever the page opens
    rows = store().bugs()
    counts = BG.summary(rows)
    head, right = st.columns([3, 1.4], vertical_alignment="center")
    head.markdown(UI.page_title(T.BUG_TEXT["title"], T.BUG_TEXT["sub"]), unsafe_allow_html=True)
    right.markdown(f'<div class="a-sub" style="text-align:right">'
                   f'{UI.esc(T.BUG_TEXT["count"].format(n=counts[BG.NEW]))}</div>', unsafe_allow_html=True)
    if not rows:
        st.markdown(UI.empty("&#128027;", T.BUG_TEXT["none"]), unsafe_allow_html=True)
        return
    f1, f2 = st.columns([2.4, 1.6], vertical_alignment="center")
    labels = [T.BUG_TEXT["all"]] + [T.BUG_TEXT[s] for s in BG.STATES]
    picked = f1.segmented_control(T.BUG_TEXT["filters"], labels, default=T.BUG_TEXT["all"], key="bug_filter",
                                  label_visibility="collapsed")
    q = f2.text_input(T.BUG_TEXT["search"], key="bug_search", label_visibility="collapsed",
                      placeholder=T.BUG_TEXT["search"])
    state = None if picked in (None, T.BUG_TEXT["all"]) else next((s for s in BG.STATES
                                                                  if T.BUG_TEXT[s] == picked), None)
    shown = BG.find(rows, state, q)
    if not shown:
        st.markdown(UI.empty("&#128269;", T.BUG_TEXT["empty"]), unsafe_allow_html=True)
        return
    bug_grid(shown)
    for bug in shown:
        bug_card(bug, who, days)



def admin():
    admin_body()
    P.theme_toggle()                                    # the sun / moon button (fixed top right): drawn last


def admin_body():
    who = st.session_state.get("admin") or restore_login()    # a browser that signed in before stays signed in
    if who and who not in S.admin_accounts():       # the account was removed: sign in again
        sign_out()
        who = None
    if not who:
        P.start_page("admin", "section[data-testid='stSidebar'] {display: none !important;}")
        login_card()
        P.version_line()
        return
    keep_cookie()
    view = current_view()
    n_review = len(store().needs_review(P.review_rules()))
    n_bugs = store().new_bugs()                      # the number beside "Bug audit"
    P.start_page("admin", nav_css(view, n_review, n_bugs) + UI.drop_zone(ADMIN_TEXT["drop"], ADMIN_TEXT["browse"],
                                                                 ADMIN_TEXT["drop_hint"]))
    sidebar(who, view)
    {"check": check_view, "benchmark": benchmark_view, "history": history_view, "review": review_view, "settings": settings_view,
     "log": log_view, "bugs": bugs_view}[view](who)
    P.version_line()
