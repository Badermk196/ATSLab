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
import lab_ui as UI

MAX_RUNNING = 3                 # checks running at the same time; the others wait in the queue
QUEUE_POLL = 1.0                # seconds between two updates of "N people ahead of you"
BROWSER_COOKIE = "atsl_browser"
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
    """The "Needs review" rules of now (Settings): a score under N, any Critical issue, a missing email or phone."""
    saved = store().saved_settings()
    return {"score": S.get("review_score", saved), "critical": S.get("review_critical", saved),
            "contact": S.get("review_contact", saved)}


def start_page(kind="user", extra_css=""):
    """Every page, every run: the key from the secrets, the style (lab_ui: kind "admin" also styles the full report,
    "user" the landing page and the short result), and the clean-ups (old temp files once per session; resume files
    older than `file_days`, at most every few minutes)."""
    S.apply_api_key()
    parts = (UI.ADMIN, D.REPORT_CSS) if kind == "admin" else (UI.USER,)
    st.markdown(UI.css(*parts, extra=extra_css), unsafe_allow_html=True)
    if not st.session_state.get("temp_cleaned"):
        D.clean_temp()
        st.session_state["temp_cleaned"] = True
    try:
        store().maybe_cleanup(setting("file_days"))
    except Exception:                       # a clean-up problem never stops a page
        pass


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


def set_admin_token(token):
    """Keep this browser signed in: a random token in a cookie for a month (only our own hex token is written)."""
    st.html(f'<script>document.cookie = "{ADMIN_COOKIE}={token}; Max-Age=2592000; Path=/; SameSite=Lax";</script>',
            unsafe_allow_javascript=True)


def clear_admin_token():
    """Forget the sign-in of this browser (Sign out)."""
    st.html(f'<script>document.cookie = "{ADMIN_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax";</script>',
            unsafe_allow_javascript=True)


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
        yield
    finally:
        q.done()
