"""
The User page (for job seekers). Design: "1000Jobs ATS Lab Redesign", pages 6 (landing) and 7 (result).

Landing: "ATS resume check", "no account needed", the upload card (an optional job title and job description) and
the privacy note (it says how many days the file is kept: the `file_days` setting).
Result: the Resume Score and label, the parts (Job Match with a job), "can reach about X", an "N issues to solve"
banner, the top 4 issues (each with
its name, its part and one short "why it matters" line), a locked "+N more issues found" line, "Why 1000Jobs" and the
"Get Premium" and "Book a resume session" buttons (links are settings).
Never shown here: how to fix, what the ATS reads, points per issue, the AI review, per-ATS details, keyword lists and
the full report. Every check is saved to the Admin history (checked by "user").
Every text is in lab_text.py, the look in lab_ui.py.
"""

import re

import streamlit as st

import dashboard as D
import lab_pages as P
import lab_store as H
import lab_text as T
import lab_ui as UI

MAX_SHOWN = 4                   # issues shown: the top 4 (the rest are counted in "+N more issues found")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_TEXT = T.USER_TEXT
ARROW = ":material/arrow_forward:"


def shown_issues(cards):
    """The issues to show: the top MAX_SHOWN by what fixing them adds (AI findings are never shown here).
    -> (cards to show, how many more issues were found)."""
    own = [c for c in cards if not c.get("ai")]
    gain = lambda c: c["points"] if c["points"] > 0 else (c.get("points_after") or 0.0)
    shown = sorted((c for c in own if gain(c) > 0), key=lambda c: -gain(c))[:MAX_SHOWN]
    if not shown and own:                           # nothing adds points on its own: the most important one
        shown = own[:1]
    return shown, len(cards) - len(shown)


def short_why(c):
    """One short 'why it matters' line: the first sentence of the issue's plain explanation."""
    text = " ".join((c.get("why") or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return m.group(1) if m else text


def privacy():
    return USER_TEXT["privacy"].format(days=P.setting("file_days"))


# ---------------------------------------------------------------------------
# The result (HTML)
# ---------------------------------------------------------------------------
def parts_html(r):
    rows = "".join(f'<div class="u-part"><div class="row"><span class="n">{D.PART_NAMES[p]}</span>'
                   f'<span class="v">{D.fmt(v)}</span></div><div class="bar"><i style="width:{max(2, v):.0f}%;'
                   f'background:var(--a-{UI.bar_tone(v)}-solid)"></i></div>'
                   f'<div class="s">{USER_TEXT["part_sub"].get(p, "")}</div></div>'
                   for p, v in ((p, r["parts"][p]) for p in D.PART_NAMES if p in r["parts"]))
    return f'<div class="u-parts"><div class="a-caps">{USER_TEXT["parts"]}</div>{rows}</div>'


def score_card_html(r, cards):
    s = D.report_summary(r, cards)
    tone = UI.tone_of(r["label"])
    reach = USER_TEXT["reach"].format(after=D.fmt_score(s["after"])) if s["n_fix"] and s["after"] > s["now"] \
        else USER_TEXT["reach_none"]
    job = (f'<div class="job">{USER_TEXT["checked_job"].format(target=UI.esc(r["target"]))}</div>'
           if r["mode"] == "job" else "")
    return (f'<div class="u-score"><div class="left">{UI.ring(r["score"], r["label"], 150, 13, USER_TEXT["out_of"], 46)}'
            f'<div style="min-width:0"><span class="a-tag a-{tone}">{UI.esc(r["label"])}</span>'
            f'<div class="head">{UI.esc(USER_TEXT["headline"].get(r["label"], ""))}</div>'
            f'<div class="sub">{reach}</div>{job}</div></div>{parts_html(r)}</div>')


def issues_html(cards, premium_url="#"):
    if not cards:
        return f'<div class="u-h2">{USER_TEXT["top"]}</div><p class="u-h2sub">{USER_TEXT["none"]}</p>'
    shown, more = shown_issues(cards)
    own = [c for c in cards if not c.get("ai")]
    count = (f'<div class="u-count">{USER_TEXT["issues_to_solve"].format(n=len(own), s=T.plural(len(own)))}</div>'
             if own else "")
    rows = "".join(f'<div class="u-issue"><span class="k">{n}</span><div style="min-width:0"><div class="t">'
                   f'{UI.esc(c["name"])}{UI.tag(D.PART_NAMES.get(D.card_part(c), ""), UI.PART_TONE.get(D.card_part(c), "grey"))}'
                   f'</div><div class="w">{UI.esc(short_why(c))}</div></div></div>' for n, c in enumerate(shown, 1))
    lock = (f'<div class="u-lock"><div class="ghost"><div style="width:62%"></div><div style="width:88%"></div>'
            f'<div style="width:45%"></div><div style="width:70%"></div></div><div class="over"><div class="ic">'
            f'&#128274;</div><b>{USER_TEXT["more"].format(n=more, s=T.plural(more))}</b><a href="{UI.esc(premium_url)}" '
            f'target="_blank" rel="noopener">{USER_TEXT["more_link"]}</a></div></div>') if more > 0 else ""
    return (f'<div class="u-h2">{USER_TEXT["top"]}</div><p class="u-h2sub">{USER_TEXT["top_sub"]}</p>'
            f'{count}{rows}{lock}')


def result_html(r, cards=None, premium_url="#"):
    """The score card and the top issues, as HTML ("Why 1000Jobs" and its buttons are drawn under it: cta_html)."""
    cards = D.issue_cards(r) if cards is None else cards
    return score_card_html(r, cards) + issues_html(cards, premium_url)


def cta_html():
    why = "".join(f'<div class="wl"><i>&#10003;</i><span>{UI.esc(t)}</span></div>' for t in D.IMPROVE_TEXT["why"])
    return f'<div class="u-cta"><div class="h2" role="heading" aria-level="2">{USER_TEXT["cta_title"]}</div>{why}</div>'


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def brand_html():
    return (f'<div class="u-brand"><span class="logo">{T.BRAND}</span>'
            f'<span class="badge">{USER_TEXT["app_badge"]}</span></div>')


def new_check():
    for k in ("u_result", "u_check_id", "u_lead_done"):
        st.session_state.pop(k, None)
    st.session_state["u_round"] = st.session_state.get("u_round", 0) + 1


def top_bar(has_result):
    with st.container(key="topbar"):
        brand, right = st.columns([3, 2], vertical_alignment="center")
        brand.markdown(brand_html(), unsafe_allow_html=True)
        if has_result:
            right.button(USER_TEXT["new"], icon=":material/refresh:", on_click=new_check, key="u_new")
        else:
            right.link_button(USER_TEXT["go_site"], P.setting("site_url"), type="primary", key="u_site", icon=ARROW,
                              icon_position="right")


def hero_html():
    ticks = "".join(f"<li><i>&#10003;</i>{UI.esc(t)}</li>" for t in USER_TEXT["ticks"])
    return (f'<div class="u-hero"><span class="pill">{USER_TEXT["hero_pill"]}</span><div class="h1" role="heading" '
            f'aria-level="1">{USER_TEXT["hero_1"]} <span class="hl">{USER_TEXT["hero_2"]}</span></div>'
            f'<p>{USER_TEXT["hero_sub"]}</p><ul class="u-ticks">{ticks}</ul></div>')


def steps_html():
    return '<div class="u-steps">' + "".join(
        f'<div class="u-step"><div class="k">{k}</div><div class="t">{UI.esc(t)}</div><div class="s">{UI.esc(s)}</div>'
        f'</div>' for k, t, s in USER_TEXT["steps"]) + "</div>"


def upload_card():
    """The upload card. -> the inputs when "Check my resume" is pressed, else None."""
    n = st.session_state.get("u_round", 0)
    st.markdown(f'<div class="a-h3">{USER_TEXT["upload_title"]}</div>', unsafe_allow_html=True)
    upload = st.file_uploader(USER_TEXT["uploader"], type=D.UPLOAD_TYPES, key=f"u_upload_{n}",
                              label_visibility="collapsed")
    with st.expander(USER_TEXT["job"]):
        title = st.text_input(USER_TEXT["job_title"], placeholder=USER_TEXT["job_title_hint"], key=f"u_title_{n}")
        text = st.text_area(USER_TEXT["job_text"], height=160, placeholder=USER_TEXT["job_text_hint"],
                            key=f"u_job_{n}")
    clicked = st.button(USER_TEXT["check"], type="primary", width="stretch", key="u_check", icon=ARROW,
                        icon_position="right")
    st.markdown(f'<div class="u-privacy">&#128274; {UI.esc(privacy())}</div>', unsafe_allow_html=True)
    if clicked:
        return {"pdf": upload.getvalue() if upload else b"", "name": upload.name if upload else "",
                "title": " ".join((title or "").split()), "text": (text or "").strip()}
    return None


def landing():
    hero, card = st.columns([1.08, 1], gap="large")
    hero.markdown(hero_html(), unsafe_allow_html=True)
    with card:
        with st.container(key="card-upload"):
            inputs = upload_card()
            if inputs is not None:
                check(inputs)                       # messages, the queue and the spinner show inside the card
    st.markdown(steps_html(), unsafe_allow_html=True)


def check(inputs):
    """Check the resume, save it to the history (checked by "user"). Errors are said in plain words.
    Each person has `daily_checks` checks a day (counted on the server for this browser and this IP address; a check
    that ends with a message instead of a score is given back), and waits in the queue when the server is busy."""
    if inputs["title"] and not inputs["text"]:
        return st.error(USER_TEXT["need_text"])
    if inputs["text"] and not inputs["title"]:
        return st.error(USER_TEXT["need_title"])
    if not inputs["pdf"] and not inputs["name"]:
        return st.error(D.CHECK_TEXT["no_file"])
    keys, limit = P.visitor_keys(), P.setting("daily_checks")
    if not P.store().reserve_check(keys, limit):
        st.error(USER_TEXT["limit"].format(n=limit))
        return premium_buttons()
    with_job = bool(inputs["text"])
    r = None
    try:
        with P.check_slot(), st.spinner(USER_TEXT["checking"]):
            r = D.run_check(inputs["pdf"], inputs["name"], with_job, inputs["text"], job_title=inputs["title"] or None)
    except D.CheckError as e:
        msg = str(e)
        if "API key" in msg or "Keyword extraction failed" in msg or "AI service is busy" in msg:
            msg = USER_TEXT["job_failed"]
        return st.error(msg)
    except Exception:
        return st.error(USER_TEXT["failed"])
    finally:
        if r is None:                       # no score (a message, an error, or the visitor left the queue)
            P.store().release_check(keys)
    st.session_state["u_result"] = r
    try:
        st.session_state["u_check_id"] = P.store().add_check(H.record_of(r, H.USER, inputs["title"]), inputs["pdf"])
    except Exception:                           # the history must never stop the user from seeing the result
        st.session_state["u_check_id"] = None
    st.rerun()


def lead_form():
    """Name and email before the result (only when the "collect_leads" setting is on)."""
    _, mid, _ = st.columns([1, 1.6, 1])
    with mid, st.container(key="card-lead"):
        st.markdown(f'<div class="a-h3">{USER_TEXT["lead_title"]}</div><p class="a-sub">{USER_TEXT["lead_sub"]}</p>',
                    unsafe_allow_html=True)
        with st.form("u_lead", border=False):
            name = st.text_input(USER_TEXT["lead_name"])
            email = st.text_input(USER_TEXT["lead_email"])
            go = st.form_submit_button(USER_TEXT["lead_go"], type="primary", width="stretch")
        st.markdown(f'<div class="u-privacy">&#128274; {UI.esc(privacy())}</div>', unsafe_allow_html=True)
        if go:
            name, email = " ".join(name.split()), email.strip()
            if not name or not EMAIL_RE.match(email):
                st.error(USER_TEXT["lead_bad"])
                return
            if st.session_state.get("u_check_id"):
                P.store().set_lead(st.session_state["u_check_id"], name, email)
            st.session_state["u_lead_done"] = True
            st.rerun()


def premium_buttons(prefix="lim", stacked=False):
    a, b = (st.container(), st.container()) if stacked else st.columns(2)
    a.link_button(USER_TEXT["premium"], P.setting("premium_url"), type="primary", width="stretch",
                  key=f"{prefix}_premium", icon=ARROW, icon_position="right")
    b.link_button(USER_TEXT["session"], P.setting("booking_url"), width="stretch", key=f"{prefix}_session")


def show_result(r):
    st.markdown(result_html(r, premium_url=P.setting("premium_url")), unsafe_allow_html=True)
    with st.container(key="cta"):
        text, buttons = st.columns([1.6, 1], gap="large", vertical_alignment="center")
        text.markdown(cta_html(), unsafe_allow_html=True)
        with buttons:
            premium_buttons("cta", stacked=True)
    st.markdown(f'<div class="u-foot">{UI.esc(privacy())}</div>', unsafe_allow_html=True)


def user():
    P.start_page("user", UI.drop_zone(USER_TEXT["drop"], USER_TEXT["browse"], USER_TEXT["drop_hint"],
                                      USER_TEXT["job_add"]))
    try:
        page()
    finally:
        P.browser_id()                                 # the browser's id cookie is set on the first visit


def page():
    r = st.session_state.get("u_result")
    if r is not None and not D.is_current(r):          # made by an older scoring: check again
        new_check()
        r = None
    top_bar(r is not None)
    if r is None:
        return landing()
    if P.setting("collect_leads") and not st.session_state.get("u_lead_done"):
        return lead_form()
    show_result(r)
