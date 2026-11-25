"""
What the Admin page and the User page share: the history store, the settings, the page style, the clean-up that runs
when a page opens, who the visitor is (browser and IP address, for the daily limit and the sign-in guard), and the
queue that lets only a few checks run at the same time.
"""

import contextlib
import re
import secrets
import threading

import streamlit as st

import dashboard as D
import lab_settings as S
import lab_store as H
import lab_text as T
import lab_timing as TM
import lab_ui as UI
import lab_version as V
import lab_warmup as W

MAX_RUNNING = 3                 # checks running at the same time; the others wait in the queue
QUEUE_POLL = 1.0                # seconds between two updates of "N people ahead of you"
BROWSER_COOKIE = "atsl_browser"
THEME_COOKIE = "atsl_theme"     # the visitor's light / dark choice (the sun / moon button)
ADMIN_COOKIE = "atsl_admin"     # the Admin page's "stayed signed in" token (never a password)
QUEUE_TEXT = T.QUEUE_TEXT       # the texts are in lab_text.py


@st.cache_resource(show_spinner=False)
def _store(folder):
    return H.Store(folder)


def store():
    """The history store of this server (the folder: ATSLAB_DATA_DIR, or the data folder next to app.py)."""
    return _store(S.data_dir())


def setting(key):
    return S.get(key, store().saved_settings())


def review_rules():
    """The "Needs review" rules of now (Settings): a score under N (the only default trigger); a Critical issue
    and a missing email or phone are options the team can switch on."""
    saved = store().saved_settings()
    return {"score": S.get("review_score", saved), "critical": S.get("review_critical", saved),
            "contact": S.get("review_contact", saved)}


def start_page(kind="user", extra_css=""):
    """Every page, every run: the key from the secrets, the style (lab_ui: kind "admin" also styles the full report,
    "user" the landing page and the short result), and the clean-ups (old temp files once per session; resume files
    older than `file_days`, at most every few minutes)."""
    TM.reset()                              # this page run's timing count (lab_timing.py)
    W.start()                               # the AI model loads in the background (lab_warmup.py), once per server
    S.apply_api_key()
    parts = (UI.ADMIN, D.REPORT_CSS) if kind == "admin" else (UI.USER,)
    # The report's own colors are light (white cards) because the downloadable PDF and the saved HTML are always
    # printed on white paper. Inside the app the same cards are drawn with the page's own palette (REPORT_SCREEN_CSS),
    # so a report card is the same color as the other cards of the page, in light AND dark mode. No theme detection
    # is needed: the palette already follows the app's theme.
    screen = D.REPORT_SCREEN_CSS if kind == "admin" else ""
    st.markdown(UI.css(*parts, extra=extra_css + screen, choice=theme_choice()), unsafe_allow_html=True)
    if not st.session_state.get("temp_cleaned"):
        D.clean_temp()
        st.session_state["temp_cleaned"] = True
    try:
        store().maybe_cleanup(setting("file_days"))
    except Exception:                       # a clean-up problem never stops a page
        pass


def theme_choice():
    """"light" or "dark" when this visitor pressed the sun / moon button (remembered in a cookie of their browser), else
    None: the app then follows the visitor's own system setting. Read from the cookie once per session."""
    if "atsl_theme" not in st.session_state:
        try:
            known = st.context.cookies.get(THEME_COOKIE)
        except Exception:
            known = None
        st.session_state["atsl_theme"] = known if known in ("light", "dark") else None
    return st.session_state["atsl_theme"]


def _flip_theme(current):
    """The button's action: dark -> light, light -> dark. With no choice yet, the opposite of what the page shows."""
    st.session_state["atsl_theme"] = "light" if current == "dark" else "dark"


def theme_toggle():
    """The sun / moon button, top right of every page. It switches the whole app (cards, ring, inputs) and the choice
    is kept in a cookie for a year. With no choice yet the page shows the app's own theme (the visitor's system
    setting), so the first press goes to the other one."""
    choice = theme_choice()
    showing = choice or UI.theme_kind() or "light"
    with st.container(key="theme-toggle"):
        st.button("", icon=":material/light_mode:" if showing == "dark" else ":material/dark_mode:",
                  key="theme_btn", type="tertiary", on_click=_flip_theme, args=(showing,),
                  help="Switch to light mode" if showing == "dark" else "Switch to dark mode")
    chosen = st.session_state.get("atsl_theme")
    if chosen and st.session_state.get("atsl_theme_cookie") != chosen:        # write the cookie only when it changed
        st.html(f'<script>document.cookie = "{THEME_COOKIE}={chosen}; Max-Age=31536000; Path=/; SameSite=Lax";'
                f'</script>', unsafe_allow_javascript=True)                    # only "light" or "dark", never user input
        st.session_state["atsl_theme_cookie"] = chosen


def version_line():
    """The small grey line at the bottom of the Admin page: which commit and date this server runs."""
    st.markdown(f'<div class="a-version">{UI.esc(V.line())}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Who the visitor is (counted on the server: a page reload never resets a count)
# ---------------------------------------------------------------------------
IP_RE = re.compile(r"^[0-9a-fA-F:.]{2,45}$")


def client_ip():
    """The visitor's IP address. Behind a proxy (Docker behind nginx, a cloud host) it is the LAST address of
    X-Forwarded-For: the one the proxy itself saw (the visitor can write the first ones). On this computer: "local"."""
    try:
        forwarded = st.context.headers.get("X-Forwarded-For")
        forwarded = forwarded.split(",")[-1].strip() if isinstance(forwarded, str) else ""
        ip = forwarded or st.context.ip_address
    except Exception:
        ip = None
    return ip if isinstance(ip, str) and IP_RE.match(ip) else "local"


def browser_id():
    """A random id kept in a cookie of this browser for a year (made on the first visit). The page keeps it in the
    session too, so the first visit is counted before the cookie comes back."""
    if "atsl_browser" not in st.session_state:
        try:
            known = st.context.cookies.get(BROWSER_COOKIE)
        except Exception:
            known = None
        ok = isinstance(known, str) and re.fullmatch(r"[0-9a-f]{32}", known)
        st.session_state["atsl_browser"] = known if ok else secrets.token_hex(16)
    bid = st.session_state["atsl_browser"]
    if not st.session_state.get("atsl_cookie_set"):
        st.html(f'<script>document.cookie = "{BROWSER_COOKIE}={bid}; Max-Age=31536000; Path=/; SameSite=Lax";'
                f'</script>', unsafe_allow_javascript=True)       # only our own random hex id, never user input
        st.session_state["atsl_cookie_set"] = True
    return bid


def admin_token():
    """The "stayed signed in" token of this browser, or None. The cookie holds a random token only: the password is
    never stored, and "Sign out" (or 30 days without a visit) ends it."""
    try:
        known = st.context.cookies.get(ADMIN_COOKIE)
    except Exception:
        known = None
    return known if isinstance(known, str) and re.fullmatch(r"[0-9a-f]{32}", known) else None


ADMIN_COOKIE_DAYS = 30


def _cookie_js(value, max_age):
    """The one line of script that writes (or, with max_age 0, deletes) the sign-in cookie. `value` is only ever our
    own random hex token or empty. "Secure" is added on https, so the cookie never travels over plain http."""
    return (f'<script>document.cookie = "{ADMIN_COOKIE}={value}; Max-Age={max_age}; Path=/; SameSite=Lax" + '
            f'(location.protocol === "https:" ? "; Secure" : "");</script>')


def set_admin_token(token):
    """Keep this browser signed in: a random token in a cookie for 30 days (only our own hex token is written)."""
    st.html(_cookie_js(token, ADMIN_COOKIE_DAYS * 86400), unsafe_allow_javascript=True)


def clear_admin_token():
    """Forget the sign-in of this browser (Sign out)."""
    st.html(_cookie_js("", 0), unsafe_allow_javascript=True)


def visitor_keys():
    """The keys a User page check is counted under: this browser and this IP address."""
    return [f"browser:{browser_id()}", f"ip:{client_ip()}"]


# ---------------------------------------------------------------------------
# The queue: at most MAX_RUNNING checks at the same time, the others wait their turn (first come, first served)
# ---------------------------------------------------------------------------
class CheckQueue:
    def __init__(self, slots=MAX_RUNNING):
        self.slots = slots
        self.running = 0
        self.waiting = []                   # tickets, in arrival order
        self._next = 0
        self._cond = threading.Condition()

    def join(self):
        with self._cond:
            self._next += 1
            self.waiting.append(self._next)
            return self._next

    def ahead(self, ticket):
        """People waiting before this ticket (0: next)."""
        with self._cond:
            return self.waiting.index(ticket) if ticket in self.waiting else 0

    def try_start(self, ticket):
        """Start when a slot is free and nobody who came earlier is still waiting for one."""
        with self._cond:
            free = self.slots - self.running
            if ticket in self.waiting and self.waiting.index(ticket) < free:
                self.waiting.remove(ticket)
                self.running += 1
                return True
            return False

    def wait(self, seconds):
        with self._cond:
            self._cond.wait(seconds)

    def leave(self, ticket):
        """A visitor who left while waiting gives up the place."""
        with self._cond:
            if ticket in self.waiting:
                self.waiting.remove(ticket)
                self._cond.notify_all()

    def done(self):
        with self._cond:
            self.running = max(0, self.running - 1)
            self._cond.notify_all()


@st.cache_resource(show_spinner=False)
def check_queue():
    """The one queue of this server (every page, every visitor)."""
    return CheckQueue()


def queue_text(n):
    return QUEUE_TEXT["next"] if n == 0 else QUEUE_TEXT["ahead"].format(n=n, people="person" if n == 1 else "people")


@contextlib.contextmanager
def check_slot(queue=None):
    """Run the block when it is this visitor's turn; until then show "N people ahead of you"."""
    q = queue or check_queue()
    ticket = q.join()
    box = st.empty()
    try:
        while not q.try_start(ticket):
            box.info(queue_text(q.ahead(ticket)))
            q.wait(QUEUE_POLL)
    except BaseException:                   # the visitor left or the page was rerun while waiting
        q.leave(ticket)
        box.empty()
        raise
    box.empty()
    try:
        W.wait()                            # the model is still loading in the background: wait for it, never load twice
        yield
    finally:
        q.done()
