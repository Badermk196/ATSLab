"""
Settings and secrets for the ATS Lab app (app.py: the Admin page and the User page).

Nothing here is written in the code: every secret and setting comes from
  1. an environment variable (wins), or
  2. Streamlit secrets (.streamlit/secrets.toml on a server, or the "Secrets" box on Streamlit Cloud), or
  3. for settings only: the value an admin saved on the Settings view (kept in the database), or the default below.
The order for settings is: saved by an admin > environment > secrets > default.

Secrets:
  OPENROUTER_API_KEY   the AI key (never shown, never saved by the app)
  admins               admin accounts, name -> password. In secrets.toml:  [admins]  bader = "..."
                       As an environment variable: ATSLAB_ADMINS='{"bader": "...", "sara": "..."}'
  ATSLAB_DATA_DIR      where the database and the kept resume files go (default: the "data" folder next to app.py)
"""

import hmac
import json
import os
import re

import lab_text as T

HERE = os.path.dirname(os.path.abspath(__file__))

# key -> (type, default, label shown on the Settings view). Environment / secrets name: ATSLAB_<KEY in capitals>.
# The labels and descriptions are in lab_text.SETTINGS_TEXT (every text of the app in one place).
_TYPES = {
    "file_days": (int, 30),
    "daily_checks": (int, 3),
    "review_score": (int, 55),          # "Needs review": a score under this ...
    "review_critical": (bool, True),    # ... a Critical issue ...
    "review_contact": (bool, True),     # ... no email or no phone
    "premium_url": (str, "https://1000jobs.club"),
    "booking_url": (str, "https://1000jobs.club"),
    "site_url": (str, "https://1000jobs.club"),
    "collect_leads": (bool, False),
    "second_matcher": (bool, True),     # the Admin page's "Second opinion" cards ...
    "second_checker2": (bool, True),    # ... run only when the team presses their button
}
SETTINGS = {k: (kind, default, T.SETTINGS_TEXT[k][0]) for k, (kind, default) in _TYPES.items()}
LIMITS = {"file_days": (1, 3650), "daily_checks": (1, 1000), "review_score": (1, 100)}   # int settings: min, max


def _secrets():
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        return {}


def secret(name, default=None):
    """An environment variable, else a Streamlit secret (top level), else `default`. Never logged."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        value = _secrets().get(name)
    except Exception:                      # no secrets.toml at all
        value = None
    return default if value in (None, "") else value


def apply_api_key():
    """The OpenRouter key from the secrets, made visible to the Lab (it reads the environment). True when a key is set."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        key = secret("OPENROUTER_API_KEY")
        if key:
            os.environ["OPENROUTER_API_KEY"] = str(key)
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def data_dir():
    path = secret("ATSLAB_DATA_DIR") or os.path.join(HERE, "data")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Admin accounts
# ---------------------------------------------------------------------------
def admin_accounts():
    """{name: password} from ATSLAB_ADMINS (JSON, or "name:password;name:password") or the [admins] table of the
    secrets. Empty when none is set: then nobody can open the Admin page."""
    raw = os.environ.get("ATSLAB_ADMINS")
    if raw:
        try:
            accounts = json.loads(raw)
        except ValueError:
            accounts = dict(p.split(":", 1) for p in raw.split(";") if ":" in p)
    else:
        try:
            accounts = dict(_secrets().get("admins") or {})
        except Exception:
            accounts = {}
    return {str(k).strip(): str(v) for k, v in accounts.items() if str(k).strip() and str(v)}


def check_login(name, password):
    """The admin's name as written in the accounts when name and password are right, else None."""
    name, password = (name or "").strip(), password or ""
    found = None
    for who, pw in admin_accounts().items():
        same = hmac.compare_digest(pw.encode("utf-8"), password.encode("utf-8"))   # always compared: same time
        if who.lower() == name.lower() and same and password:
            found = who
    return found


# ---------------------------------------------------------------------------
# Settings (an admin can change them on the Settings view)
# ---------------------------------------------------------------------------
def parse(key, value):
    kind = SETTINGS[key][0]
    if kind is bool:
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    if kind is int:
        n = int(str(value).strip())
        low, high = LIMITS.get(key, (1, 10 ** 6))
        if not low <= n <= high:
            raise ValueError(f"must be {low} to {high}")
        return n
    text = str(value).strip()
    if key.endswith("_url") and not re.match(r"https?://[^\s<>\"']+$", text):
        raise ValueError("a link must start with http:// or https://")     # never 'javascript:' on the user page
    return text


def get(key, saved=None):
    """A setting: the value an admin saved (`saved`, from the database), else ATSLAB_<KEY>, else the default."""
    kind, default, _ = SETTINGS[key]
    for value in ((saved or {}).get(key), secret("ATSLAB_" + key.upper())):
        if value not in (None, ""):
            try:
                return parse(key, value)
            except (TypeError, ValueError):
                pass                                   # a wrong value never breaks the app: the next source is used
    return default


def source(key, saved=None):
    """Where the setting comes from, for the Settings view."""
    if (saved or {}).get(key) not in (None, ""):
        return "saved here"
    if secret("ATSLAB_" + key.upper()) not in (None, ""):
        return "server setting"
    return "default"
