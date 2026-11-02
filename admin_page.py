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
import io

import streamlit as st

import dashboard as D
import lab_pages as P
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
                    store().log(who, "sign_in", T.LOG_DETAILS["sign_in"])
                    st.rerun()
                st.error(ADMIN_TEXT["locked"] if store().login_wait(guard_keys(name, ip)) > 0 else ADMIN_TEXT["wrong"])


def sign_out():
    for k in ("admin", "result", "open_check", "confirm_delete", "admin_view"):
        st.session_state.pop(k, None)


# ---------------------------------------------------------------------------
# The sidebar
# ---------------------------------------------------------------------------
def nav_css(view, n_review):
    """The open view's item, the red "Needs review" count, and the hidden labels of icon buttons."""
    on = (f".st-key-nav_{view} button {{background: var(--a-pri-soft) !important; border-color: var(--a-pri-line) "
          f"!important;}} .st-key-nav_{view} button p, .st-key-nav_{view} button [data-testid=\"stIconMaterial\"] "
          f"{{color: var(--a-pri-text) !important; font-weight: 600 !important;}}")
    badge = (f'.st-key-nav_review button {{position: relative;}} .st-key-nav_review button::after {{content: "{n_review}"; '
             f"position: absolute; right: 10px; top: 50%; transform: translateY(-50%); min-width: 22px; height: 22px; "
             f"padding: 0 6px; border-radius: 11px; background: var(--a-badge); color: #fff; font-size: .75rem; "
             f"font-weight: 700; display: flex; align-items: center; justify-content: center;}}") if n_review else ""
    hidden = hidden_label(".st-key-sign_out") + hidden_label("[class*='st-key-hopen_']")
    return on + badge + hidden


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
            rec = H.record_of(saved["res"], who, inputs.get("job_title"), saved.get("prev"), bool(inputs.get("client")))
            store().add_check(rec, inputs.get("pdf"))
            r = saved["res"]
            store().log(who, "check", rec["candidate"] or rec["file_name"],
                        T.LOG_DETAILS["check"].format(job=rec["job_title"] or ADMIN_TEXT["general"],
                                                      score=round(r["score"]), label=r["label"]))
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


def check_form(mode):
    """The upload card: resume, target role + job description (with a job), compare with a previous resume."""
    round_ = st.session_state.get("upload_round", 0)
    upload = st.file_uploader(ADMIN_TEXT["resume"], type=D.UPLOAD_TYPES, key=f"upload_{round_}")
    title, text = job_fields(round_) if mode == D.WITH_JOB else ("", "")
    if mode != D.WITH_JOB:
        st.caption(ADMIN_TEXT["general_note"])
    with st.expander(ADMIN_TEXT["compare"], icon=":material/compare_arrows:"):
        st.caption(ADMIN_TEXT["compare_sub"])
        prev = st.file_uploader(ADMIN_TEXT["previous"], type=D.UPLOAD_TYPES, key=f"previous_{round_}")
        client = st.checkbox(D.CLIENT_TEXT["checkbox"], key=f"client_{round_}")
    if st.button(ADMIN_TEXT["run"], type="primary", width="stretch", key="run_check", icon=":material/arrow_forward:",
                 icon_position="right"):
        return {"pdf": upload.getvalue() if upload else b"", "name": upload.name if upload else "",
                "with_job": mode == D.WITH_JOB, "text": text, "job_title": title,
                "prev_pdf": prev.getvalue() if prev is not None else None,
                "prev_name": prev.name if prev is not None else None, "client": client}
    return None


def run(inputs, who):
    D.check_and_store(inputs, P.check_slot)
    if "result" in st.session_state:
        saver(who)(st.session_state["result"])
        st.rerun()


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


def check_view(who):
    head, right = st.columns([3, 1.6], vertical_alignment="center")
    head.markdown(UI.page_title(ADMIN_TEXT["check_title"], ADMIN_TEXT["check_sub"]), unsafe_allow_html=True)
    with right:
        mode = mode_switch()
    saved = D.current_result()
    if saved is None:
        main, side = st.columns([2.3, 1], gap="medium")
        with main:
            with st.container(key="card-check"):
                inputs = check_form(mode)
                if inputs is not None:
                    run(inputs, who)
        with side:
            side_panels()
        return
    a, b = st.columns([3, 1], vertical_alignment="center")
    a.markdown(D.file_chip_html(saved["res"]).replace("margin-left: auto", ""), unsafe_allow_html=True)
    b.button(ADMIN_TEXT["new_check"], type="primary", on_click=D.start_new, key="new_check", width="stretch")
    if (mode == D.WITH_JOB) != bool(saved["with_job"]):
        again_card(mode, saved, who)
    D.render(saved["res"], saved["with_job"], saved["prev"], client=bool((saved.get("inputs") or {}).get("client")))


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
                               round(r["score"] or 0), r.get("label"), "; ".join(r["review_reasons"]),
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
    right.button(ADMIN_TEXT["new_check_short"], icon=":material/add:",
                 type="primary", key="hist_new", on_click=lambda: (go("check"), D.start_new()))
    rows = store().history(rules=P.review_rules())
    n_user = sum(r["checked_by"] == H.USER for r in rows)
    avg = round(sum(r["score"] or 0 for r in rows) / len(rows)) if rows else 0
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
    st.markdown(UI.page_title(ADMIN_TEXT["review_title"], ADMIN_TEXT["review_sub"].format(rules=rules_text(rules))),
                unsafe_allow_html=True)
    st.write("")
    rows = store().needs_review(rules)
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
def admin():
    who = st.session_state.get("admin")
    if who and who not in S.admin_accounts():       # the account was removed: sign in again
        sign_out()
        who = None
    if not who:
        P.start_page("admin", "section[data-testid='stSidebar'] {display: none !important;}")
        login_card()
        return
    view = current_view()
    n_review = len(store().needs_review(P.review_rules()))
    P.start_page("admin", nav_css(view, n_review) + UI.drop_zone(ADMIN_TEXT["drop"], ADMIN_TEXT["browse"],
                                                                 ADMIN_TEXT["drop_hint"]))
    sidebar(who, view)
    {"check": check_view, "history": history_view, "review": review_view, "settings": settings_view,
     "log": log_view}[view](who)
