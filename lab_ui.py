"""
The look of the app (Admin page and User page), from the design "1000Jobs ATS Lab Redesign" (7 pages): one palette,
the same cards, rounded corners, spacing, buttons and colors everywhere, light and dark mode.

- CSS: the palette is a set of CSS variables (--a-...), with a dark version. The version is chosen from the app's own
  theme (Streamlit's setting, st.context.theme), and the system's dark mode is only the fallback when it cannot be read
  (.streamlit/config.toml has a [theme.light] and a [theme.dark]).
- Streamlit parts are styled by their keys: a container whose key starts with "card" is a card, "nav_<view>" is a
  sidebar item, "topbar" is the white bar of the User page, and so on.
- HTML helpers (esc, pill, tag, avatar, ring, stat cards ...) build the small pieces every page uses.
No Streamlit call here (the pages inject CSS with st.markdown), so it can be tested directly.
"""

import html
import re

FONT_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap"
FONT = '"Inter", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif'

# label -> tone (the color of its pill and of its score ring)
LABEL_TONE = {"Excellent": "ok", "Strong": "ok", "Good": "info", "Needs work": "warn", "At risk": "org",
              "Not ready": "bad"}
PART_TONE = {"readability": "pri", "content": "warn", "structure": "info", "job_match": "ok"}
RING_COLOR = {"ok": "var(--a-ok-solid)", "info": "var(--a-info-solid)", "warn": "var(--a-warn-solid)",
              "org": "var(--a-org-solid)", "bad": "var(--a-bad-solid)", "pri": "var(--a-pri)"}

PALETTE = """
:root {
  --a-bg: #f5f6fa; --a-card: #ffffff; --a-line: #e6e8ef; --a-line-2: #eef0f5; --a-hover: #f8f9fc;
  --a-text: #111827; --a-text-2: #374151; --a-muted: #6b7280; --a-faint: #9ca3af;
  --a-pri: #4f46e5; --a-pri-2: #4338ca; --a-pri-soft: #eef2ff; --a-pri-line: #c7d2fe; --a-pri-text: #4338ca;
  --a-on-pri: #ffffff;
  --a-ok-bg: #dcfce7; --a-ok: #166534; --a-ok-line: #bbf7d0; --a-ok-solid: #16a34a;
  --a-info-bg: #e0f2fe; --a-info: #075985; --a-info-line: #bae6fd; --a-info-solid: #0284c7;
  --a-warn-bg: #fef3c7; --a-warn: #92400e; --a-warn-line: #fde68a; --a-warn-solid: #f59e0b; --a-warn-tint: #fffbeb;
  --a-org-bg: #ffedd5; --a-org: #9a3412; --a-org-line: #fed7aa; --a-org-solid: #ea580c;
  --a-bad-bg: #fee2e2; --a-bad: #991b1b; --a-bad-line: #fecaca; --a-bad-solid: #dc2626; --a-badge: #ef4444;
  --a-grey-bg: #f3f4f6; --a-grey: #374151;
  --a-cta: #312e81; --a-cta-text: #ffffff; --a-cta-sub: #e0e7ff;
  --a-shadow: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06);
  --a-shadow-pri: 0 8px 20px -6px rgba(79,70,229,.45);
}
@media (prefers-color-scheme: dark) {
  :root {
    --a-bg: #0b1020; --a-card: #131a2b; --a-line: #263049; --a-line-2: #1d2539; --a-hover: #182036;
    --a-text: #e5e7eb; --a-text-2: #cbd5e1; --a-muted: #9ca3af; --a-faint: #6b7280;
    --a-pri: #6366f1; --a-pri-2: #818cf8; --a-pri-soft: rgba(99,102,241,.16); --a-pri-line: rgba(129,140,248,.45);
    --a-pri-text: #a5b4fc; --a-on-pri: #ffffff;
    --a-ok-bg: rgba(34,197,94,.16); --a-ok: #86efac; --a-ok-line: rgba(34,197,94,.35); --a-ok-solid: #22c55e;
    --a-info-bg: rgba(14,165,233,.16); --a-info: #7dd3fc; --a-info-line: rgba(14,165,233,.35); --a-info-solid: #38bdf8;
    --a-warn-bg: rgba(245,158,11,.16); --a-warn: #fcd34d; --a-warn-line: rgba(245,158,11,.4); --a-warn-solid: #fbbf24;
    --a-warn-tint: rgba(245,158,11,.08);
    --a-org-bg: rgba(234,88,12,.18); --a-org: #fdba74; --a-org-line: rgba(234,88,12,.4); --a-org-solid: #fb923c;
    --a-bad-bg: rgba(239,68,68,.16); --a-bad: #fca5a5; --a-bad-line: rgba(239,68,68,.4); --a-bad-solid: #f87171;
    --a-badge: #ef4444; --a-grey-bg: #1f2937; --a-grey: #d1d5db;
    --a-cta: #1e1b4b; --a-cta-text: #ffffff; --a-cta-sub: #c7d2fe;
    --a-shadow: 0 1px 2px rgba(0,0,0,.3); --a-shadow-pri: 0 8px 20px -6px rgba(99,102,241,.5);
  }
}
"""

# The same two palettes, read back from PALETTE so the values live in one place only: the light one and the dark one.
_VAR = re.compile(r"--a-[a-z0-9-]+\s*:[^;]+;")
_LIGHT_PART, _DARK_PART = PALETTE.split("@media (prefers-color-scheme: dark)")
LIGHT_VARS = "".join(_VAR.findall(_LIGHT_PART))
DARK_VARS = "".join(_VAR.findall(_DARK_PART))


def theme_kind():
    """The app's own theme: "light" or "dark", read from Streamlit's setting (the visitor's choice in the app menu).
    None when it cannot be read (outside a running app), so the system's own dark mode is used, as before."""
    try:
        import streamlit as st
        kind = getattr(st.context.theme, "type", None)
    except Exception:
        return None
    return kind if kind in ("light", "dark") else None


def theme_css():
    """The palette that matches the app's own theme. The system's dark mode is not enough: a visitor can set the app
    to dark while the computer stays light, and the cards then came out white on a dark page. Empty when the theme
    cannot be read, so PALETTE's own rule stays in charge."""
    kind = theme_kind()
    if kind == "dark":
        return "\n:root {" + DARK_VARS + "}"
    if kind == "light":
        return "\n:root {" + LIGHT_VARS + "}"
    return ""

BASE = """
/* The page must never jump sideways: while a view is short there is no scroll bar, and a long list makes one appear
   and take ~10px of width, so the whole page moved. The room for it is kept on the one element that really scrolls
   (stMain), which is why the content keeps exactly the same width on every view. Only that element: any other
   container would take its own 10px and the page would just be narrower. The sidebar has its own rule below. */
[data-testid="stMain"] {scrollbar-gutter: stable;}
.stApp {background: var(--a-bg); color: var(--a-text);}
.stApp, .stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea, .stApp li, .stApp h1, .stApp h2,
.stApp h3, .stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] {font-family: FONT;}
.stApp [data-testid="stElementContainer"]:has(> div > div > style),
.stApp [data-testid="stElementContainer"]:has(style:only-child) {display: none;}
.stApp [data-testid="stElementContainer"]:has(iframe[title="st.html"]),
.stApp [data-testid="stElementContainer"]:has([data-testid="stHtml"]:empty) {display: none;}
[data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"] {display: none !important;}
/* the "Made with Streamlit" badge and the footer bar: the app carries its own brand */
[data-testid="stAppFooter"], footer {display: none !important;}
header[data-testid="stHeader"] {background: transparent; pointer-events: none;}
[data-testid="stExpandSidebarButton"] {pointer-events: auto; background: var(--a-card); border: 1px solid var(--a-line);
  border-radius: 10px; box-shadow: var(--a-shadow);}
.block-container, [data-testid="stMainBlockContainer"] {padding-top: 40px !important; padding-bottom: 64px;
  padding-left: 48px; padding-right: 48px; max-width: 1240px;}
.stApp a {color: var(--a-pri);}
.stApp hr {border-color: var(--a-line);}

/* labels, inputs */
.stApp [data-testid="stWidgetLabel"] p {font-size: .9rem; font-weight: 600; color: var(--a-text);}
.stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"], .stApp [data-baseweb="select"] > div {
  border-radius: 10px !important; border-color: var(--a-line) !important; background: var(--a-card) !important;}
.stApp [data-baseweb="input"]:focus-within, .stApp [data-baseweb="textarea"]:focus-within {
  border-color: var(--a-pri) !important; box-shadow: 0 0 0 3px var(--a-pri-soft);}
.stApp input, .stApp textarea {color: var(--a-text) !important;}
.stApp input::placeholder, .stApp textarea::placeholder {color: var(--a-faint) !important; opacity: 1;}

/* buttons */
.stApp [data-testid="stBaseButton-primary"], .stApp [data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--a-pri); border: 1px solid var(--a-pri); color: var(--a-on-pri); border-radius: 12px;
  font-weight: 600; min-height: 44px; box-shadow: var(--a-shadow-pri);}
.stApp [data-testid="stBaseButton-primary"]:hover, .stApp [data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: var(--a-pri-2); border-color: var(--a-pri-2); color: var(--a-on-pri);}
.stApp [data-testid="stBaseButton-primary"] p, .stApp [data-testid="stBaseButton-primaryFormSubmit"] p {
  font-weight: 600; font-size: .95rem;}
.stApp [data-testid="stBaseButton-secondary"], .stApp [data-testid="stBaseButton-secondaryFormSubmit"],
.stApp [data-testid="stDownloadButton"] button, .stApp [data-testid="stLinkButton"] a {
  border-radius: 12px; border: 1px solid var(--a-line); background: var(--a-card); color: var(--a-text);
  font-weight: 600; min-height: 42px; box-shadow: var(--a-shadow);}
.stApp [data-testid="stBaseButton-secondary"]:hover, .stApp [data-testid="stDownloadButton"] button:hover,
.stApp [data-testid="stLinkButton"] a:hover, .stApp [data-testid="stBaseButton-secondaryFormSubmit"]:hover {
  border-color: var(--a-pri-line); color: var(--a-pri-text); background: var(--a-card);}
.stApp [data-testid="stLinkButton"] a[kind="primary"], .stApp [data-testid="stLinkButton"] a[data-testid="stBaseLinkButton-primary"] {
  background: var(--a-pri); color: var(--a-on-pri); border-color: var(--a-pri); box-shadow: var(--a-shadow-pri);}
.stApp [data-testid="stBaseButton-tertiary"] {color: var(--a-pri); font-weight: 600;}
.stApp [data-testid="stBaseButton-tertiary"]:hover {color: var(--a-pri-2);}

/* cards: every container whose key starts with "card" */
.stApp [class*="st-key-card"] {background: var(--a-card) !important; border: 1px solid var(--a-line) !important;
  border-radius: 16px; padding: 22px 24px; box-shadow: var(--a-shadow);}
/* the boxes inside a card keep the card's color, never Streamlit's own white panel */
.stApp [class*="st-key-card"] > div, .stApp [class*="st-key-card"] [data-testid="stVerticalBlockBorderWrapper"] {
  background: transparent; border-color: var(--a-line);}
.stApp [class*="st-key-card"] h3, .a-h3 {font-size: 1.12rem; font-weight: 700; margin: 0; padding: 0;
  color: var(--a-text); letter-spacing: -.2px;}
.a-sub {color: var(--a-muted); font-size: .9rem; margin: 2px 0 0 0;}
.a-note {color: var(--a-text-2); background: var(--a-pri-soft); border: 1px solid var(--a-pri-line);
  border-radius: 10px; padding: 8px 11px; font-size: .86rem; margin: 12px 0 0 0; word-break: break-word;}

/* page titles */
.a-title {font-size: 2.15rem; font-weight: 800; letter-spacing: -.8px; color: var(--a-text); margin: 0;
  line-height: 1.15;}
.a-title-sub {color: var(--a-muted); font-size: 1rem; margin: 6px 0 22px 0;}

/* the file uploader as the design's drop zone */
.stApp [data-testid="stFileUploaderDropzone"] {display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 10px; padding: 26px 16px; border: 1.5px dashed var(--a-pri-line);
  background: var(--a-pri-soft); border-radius: 14px; cursor: pointer; min-height: 168px;}
.stApp [data-testid="stFileUploaderDropzone"]:hover {border-color: var(--a-pri);}
.stApp [data-testid="stFileUploaderDropzone"] > span button {width: 48px; height: 48px; min-height: 48px;
  padding: 0; border-radius: 12px; border: none; background: var(--a-card); box-shadow: var(--a-shadow);
  color: var(--a-pri);}
.stApp [data-testid="stFileUploaderDropzone"] > span button [data-testid="stMarkdownContainer"] {display: none;}
.stApp [data-testid="stFileUploaderDropzone"] > span button [data-testid="stIconMaterial"] {font-size: 24px;
  color: var(--a-pri); margin: 0;}
.stApp [data-testid="stFileUploaderDropzoneInstructions"],
.stApp [data-testid="stFileUploaderDropzoneInstructions"] > div {display: block !important; text-align: center;
  margin: 0;}
.stApp [data-testid="stFileUploaderDropzoneInstructions"] > div > span {display: none;}
.stApp [data-testid="stFileUploaderDropzoneInstructions"] > div::before {content: var(--a-drop-main);
  font-weight: 600; color: var(--a-text); font-size: .98rem;}
.stApp [data-testid="stFileUploaderDropzoneInstructions"] > div::after {content: var(--a-drop-link);
  font-weight: 600; color: var(--a-pri); font-size: .98rem;}
.stApp [data-testid="stFileUploaderDropzoneInstructions"]::after {content: var(--a-drop-hint); display: block;
  color: var(--a-muted); font-size: .82rem; margin-top: 6px;}
.stApp [data-testid="stFileUploaderFile"] {background: var(--a-card); border: 1px solid var(--a-line);
  border-radius: 10px; padding: 6px 10px;}

/* expander: a quiet row with a border */
.stApp [data-testid="stExpander"] details {border: 1px solid var(--a-line); border-radius: 12px;
  background: var(--a-card);}
.stApp [data-testid="stExpander"] summary {padding: 12px 16px;}
.stApp [data-testid="stExpander"] summary p {font-weight: 600; font-size: .92rem; color: var(--a-text);}
.stApp [data-testid="stExpander"] summary > span {width: 100%;}

/* segmented control (the With / General switch) and chips */
.stApp [data-testid="stButtonGroup"] [data-baseweb="button-group"] {gap: 8px; flex-wrap: wrap;}
.stApp [data-testid="stBaseButton-segmented_control"], .stApp [data-testid="stBaseButton-segmented_controlActive"] {
  border: none; background: transparent; border-radius: 10px !important; min-height: 38px; padding: 6px 16px;
  color: var(--a-muted);}
.stApp [data-testid="stBaseButton-segmented_controlActive"] {background: var(--a-card); color: var(--a-text);
  box-shadow: var(--a-shadow);}
.stApp [data-testid="stBaseButton-segmented_control"] p, .stApp [data-testid="stBaseButton-segmented_controlActive"] p {
  font-weight: 600; font-size: .9rem;}
.st-key-mode [data-baseweb="button-group"] {background: var(--a-line-2); border-radius: 14px; padding: 4px; gap: 2px;
  flex-wrap: nowrap;}
.stApp [data-testid="stBaseButton-pills"], .stApp [data-testid="stBaseButton-pillsActive"] {border-radius: 999px;
  border: 1px solid var(--a-line); background: var(--a-card); color: var(--a-text); min-height: 36px;
  padding: 4px 16px;}
.stApp [data-testid="stBaseButton-pillsActive"] {background: var(--a-pri); border-color: var(--a-pri);
  color: var(--a-on-pri);}
.stApp [data-testid="stBaseButton-pills"] p, .stApp [data-testid="stBaseButton-pillsActive"] p {font-weight: 600;
  font-size: .88rem;}

/* small pieces made in HTML */
.a-pill {display: inline-flex; align-items: center; justify-content: center; min-width: 40px; height: 30px;
  padding: 0 9px; border-radius: 9px; font-weight: 700; font-size: .9rem; border: 1px solid transparent;}
.a-tag {display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 8px; font-weight: 600;
  font-size: .8rem; line-height: 1.5; white-space: nowrap; border: 1px solid transparent;}
.a-ok {background: var(--a-ok-bg); color: var(--a-ok);} .a-info {background: var(--a-info-bg); color: var(--a-info);}
.a-warn {background: var(--a-warn-bg); color: var(--a-warn);} .a-org {background: var(--a-org-bg); color: var(--a-org);}
.a-bad {background: var(--a-bad-bg); color: var(--a-bad);} .a-grey {background: var(--a-grey-bg); color: var(--a-grey);}
.a-pri {background: var(--a-pri-soft); color: var(--a-pri-text);}
.a-avatar {display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px;
  border-radius: 50%; background: var(--a-grey-bg); color: var(--a-text); font-weight: 700; font-size: .78rem;
  flex: 0 0 auto;}
.a-avatar.pri {background: var(--a-pri-soft); color: var(--a-pri-text);}
.a-who {display: flex; align-items: center; gap: 12px; min-width: 0;}
.a-who b {font-weight: 600; color: var(--a-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.a-muted {color: var(--a-muted);} .a-small {font-size: .82rem;}
.a-caps {font-size: .72rem; font-weight: 700; letter-spacing: .08em; color: var(--a-muted); text-transform: uppercase;}

/* stat cards */
.a-stats {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 6px 0 20px 0;}
.a-stat {background: var(--a-card); border: 1px solid var(--a-line); border-radius: 16px; padding: 18px 20px;
  box-shadow: var(--a-shadow); min-width: 0;}
.a-stat .t {color: var(--a-muted); font-size: .9rem; font-weight: 500;}
.a-stat .v {font-size: 2rem; font-weight: 800; color: var(--a-text); letter-spacing: -.5px; margin-top: 4px;}
.a-stat.warn {background: var(--a-warn-tint); border-color: var(--a-warn-line);} .a-stat.warn .t {color: var(--a-warn);}
.a-stat.edge {border-left-width: 4px;}
.a-stat.edge.pri {border-left-color: var(--a-pri);} .a-stat.edge.ok {border-left-color: var(--a-ok-solid);}
.a-stat.edge.grey {border-left-color: var(--a-muted);} .a-stat.edge.bad {border-left-color: var(--a-bad-solid);}

/* tables made of Streamlit rows (History) */
.a-th {font-size: .72rem; font-weight: 700; letter-spacing: .08em; color: var(--a-muted); text-transform: uppercase;}
[class*="st-key-hrow_"] {border-top: 1px solid var(--a-line-2); padding: 6px 0;}
[class*="st-key-hrow_"]:hover {background: var(--a-hover);}
[class*="st-key-hrow_"] [data-testid="stMarkdownContainer"] p {margin: 0;}
[class*="st-key-hrow_"] [data-testid="stCheckbox"], .st-key-hist_head [data-testid="stCheckbox"] {margin: 0;
  min-height: 0;}
[class*="st-key-hrow_"] [data-testid="stCheckbox"] label, .st-key-hist_head [data-testid="stCheckbox"] label {
  min-height: 0; margin: 0; padding: 0;}
[class*="st-key-hopen_"] button {min-height: 32px; padding: 2px 6px;}
.a-cell {color: var(--a-text-2); font-size: .92rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}

/* tables made in HTML (Activity log) */
.a-table-wrap {overflow-x: auto;}
.stApp .a-table {width: 100%; border-collapse: collapse; min-width: 640px; border: none; margin: 0;}
.stApp .a-table tr {border: none; background: transparent;}
.stApp .a-table th {text-align: left; padding: 12px 18px; border: none; border-bottom: 1px solid var(--a-line);
  background: transparent;}
.stApp .a-table td {padding: 14px 18px; border: none; border-bottom: 1px solid var(--a-line-2); vertical-align: middle;
  color: var(--a-text); font-size: .92rem; background: transparent;}
.stApp .a-table tr:last-child td {border-bottom: none;}
.a-table td .d {font-weight: 600;} .a-table td .s {color: var(--a-muted); font-size: .82rem; margin-top: 2px;}

/* the score ring */
.a-ring {position: relative; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;}
.a-ring .in {position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; line-height: 1.05;}
.a-ring .n {font-weight: 800; color: var(--a-text); letter-spacing: -1px;}
.a-ring .l {font-size: .72rem; font-weight: 600; margin-top: 2px;}
.a-ring .o {color: var(--a-muted); font-size: .78rem; margin-top: 3px;}

/* empty states */
.a-empty {text-align: center; padding: 48px 20px;}
.a-empty .ic {width: 56px; height: 56px; margin: 0 auto 14px auto; border-radius: 16px; display: flex;
  align-items: center; justify-content: center; font-size: 26px; background: var(--a-pri-soft); color: var(--a-pri);}
.a-empty .t {font-weight: 700; font-size: 1.1rem; color: var(--a-text);}
.a-empty .s {color: var(--a-muted); margin-top: 4px;}

/* alerts in the palette */
.stApp [data-testid="stAlert"] {border-radius: 12px;}

/* the full report (dashboard.py) stays a white document, also in dark mode */
.stApp .rp {color: #0f172a;}
.stApp .rp h2 {color: var(--a-text);}
.stApp .rp .sub {color: var(--a-muted);}

@media (max-width: 1100px) {
  .a-stats {grid-template-columns: repeat(2, minmax(0, 1fr));}
}
@media (max-width: 640px) {
  .block-container, [data-testid="stMainBlockContainer"] {padding-left: 16px !important;
    padding-right: 16px !important; padding-top: 20px !important;}
  .a-title {font-size: 1.7rem;}
  .stApp [class*="st-key-card"] {padding: 18px 16px;}
  .a-stats {gap: 10px;}
  .a-stat {padding: 14px 14px;} .a-stat .v {font-size: 1.6rem;}
}
""".replace("FONT", FONT)

# ---------------------------------------------------------------------------
# The Admin page: sidebar and the views
# ---------------------------------------------------------------------------
ADMIN = """
/* The sidebar: SIDE_PAD on both sides of everything (the menu, the brand, the profile card). Streamlit keeps room for a
   scroll bar on BOTH sides of its scroll area (scrollbar-gutter), as wide as the browser's scroll bars: that made the
   left edge differ between browsers. Here it is off, and the sidebar never scrolls sideways. */
section[data-testid="stSidebar"] {width: 248px !important; min-width: 248px !important; max-width: 248px !important;
  background: var(--a-card); border-right: 1px solid var(--a-line); box-sizing: border-box;
  overflow-x: hidden !important;}
section[data-testid="stSidebar"] > div:first-child {background: var(--a-card);}
[data-testid="stSidebarContent"] {display: flex; flex-direction: column; height: 100%; padding: 0 !important;
  overflow-x: hidden !important; scrollbar-gutter: auto !important; box-sizing: border-box; position: relative;}
/* The header holds only the fold button: it must never sit on the brand, so it takes no clicks itself. */
[data-testid="stSidebarHeader"] {position: absolute; top: 0; right: 0; height: 0; min-height: 0; padding: 0;
  margin: 0; z-index: 4; pointer-events: none;}
/* The fold button, always visible, on the line of "1000Jobs": the brand starts 20px down, its first line is 34px high,
   and .a-brand keeps 44px free on the right for this button (32px + 12px free). It overlaps nothing. */
[data-testid="stSidebarCollapseButton"] {position: absolute; top: 23px; right: 14px; z-index: 4; margin: 0;
  pointer-events: auto; visibility: visible !important; opacity: 1 !important; width: 32px; height: 28px;}
[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"] button:hover
  {visibility: visible !important; opacity: 1 !important; pointer-events: auto;}
[data-testid="stSidebarUserContent"] {padding: 20px 16px 18px 16px !important; margin: 0 !important; width: 100%;
  box-sizing: border-box; flex: 1 1 auto; display: flex; flex-direction: column; min-width: 0;}
[data-testid="stSidebarUserContent"] * {box-sizing: border-box; max-width: 100%;}
[data-testid="stSidebarUserContent"] > div {flex: 1 1 auto; display: flex; flex-direction: column;}
[data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {flex: 1 1 auto; gap: 4px;}
[data-testid="stSidebarUserContent"] [data-testid="stLayoutWrapper"]:has(.st-key-side-foot),
.st-key-side-foot {margin-top: auto !important;}
section[data-testid="stSidebar"] [class*="st-key-nav_"], section[data-testid="stSidebar"] [class*="st-key-nav_"]
  [data-testid="stButton"] {width: 100% !important;}
/* The brand: "1000Jobs", "ATS LAB", then the "★ ADMIN" badge, each on its own line, all starting on the same line
   as the menu items' text (10px in), with 4px and 8px of space between them. The 44px on the right is the room of
   the fold button, so the badge and the words can never run under it. */
.a-brand {padding: 0 44px 16px 10px; border-bottom: 1px solid var(--a-line); margin-bottom: 14px;}
.a-brand .logo {font-weight: 800; font-size: 1.6rem; color: var(--a-pri); letter-spacing: -1px; line-height: 34px;}
.a-brand .lab {display: block; font-size: .72rem; font-weight: 700; letter-spacing: .08em; color: var(--a-muted);
  margin-top: 4px;}
.a-brand .badge {display: block; width: max-content; font-size: .72rem; font-weight: 700; color: var(--a-pri-text);
  background: var(--a-pri-soft); border: 1px solid var(--a-pri-line); border-radius: 7px; padding: 1px 7px;
  margin-top: 8px;}
.a-ws {font-size: .72rem; font-weight: 700; letter-spacing: .08em; color: var(--a-muted); padding: 4px 10px 8px 10px;}
/* The menu: every item (open or not, hovered or not) keeps the same box and the same 8px 10px padding, so the open
   item is never wider, never shifted and never clipped. */
section[data-testid="stSidebar"] [class*="st-key-nav_"] button {width: 100% !important; justify-content: flex-start;
  padding: 8px 10px !important; min-height: 40px; border-radius: 10px; border: 1px solid transparent;
  color: var(--a-text-2); background: transparent; box-shadow: none; margin: 0; box-sizing: border-box;
  overflow: hidden;}
section[data-testid="stSidebar"] [class*="st-key-nav_"] button > div,
section[data-testid="stSidebar"] [class*="st-key-nav_"] button span[data-has-shortcut] {justify-content: flex-start
  !important; width: 100%;}
section[data-testid="stSidebar"] [class*="st-key-nav_"] button p {font-weight: 500; font-size: .95rem;
  white-space: nowrap;}
section[data-testid="stSidebar"] [class*="st-key-nav_"] button [data-testid="stIconMaterial"] {font-size: 20px;
  color: var(--a-muted); margin-right: 6px;}
section[data-testid="stSidebar"] [class*="st-key-nav_"] button:hover {background: var(--a-hover); color: var(--a-text);}
/* The bottom of the sidebar: the profile card (initial, name, "Admin", sign-out) starts and ends exactly like the
   menu items and can never leave the sidebar, whatever the name is. */
.st-key-side-foot {width: 100% !important; max-width: 100% !important;}
.a-foot {display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 auto;}
.st-key-side-card {border: 1px solid var(--a-line); border-radius: 14px; padding: 10px 6px 10px 10px;
  background: var(--a-card); width: 100% !important; max-width: 100% !important; margin: 0 !important;
  box-sizing: border-box; overflow: hidden;}
.a-foot .nm {font-weight: 600; color: var(--a-text); font-size: .92rem; line-height: 1.2; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;}
.a-foot .rl {color: var(--a-muted); font-size: .8rem;}
.a-ver {color: var(--a-faint); font-size: .75rem; padding: 8px 10px 0 10px; max-width: 100%;}
.st-key-side-card [data-testid="stHorizontalBlock"] {align-items: center; gap: 4px; flex-wrap: nowrap;}
.st-key-side-card [data-testid="stColumn"] {min-width: 0 !important;}
.st-key-side-card [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {align-items: flex-end;}
.st-key-sign_out button {min-height: 34px; padding: 4px 8px; border: none; box-shadow: none; background: transparent;
  color: var(--a-muted);}

/* the side panels of "Check a resume" */
.a-list {margin: 12px 0 0 0; padding: 0; list-style: none;}
.a-list li {display: flex; gap: 12px; align-items: flex-start; margin: 0 0 12px 0; color: var(--a-text-2);
  font-size: .92rem;}
.a-list .k {flex: 0 0 auto; width: 24px; height: 24px; border-radius: 7px; background: var(--a-pri-soft);
  color: var(--a-pri-text); font-weight: 700; font-size: .78rem; display: flex; align-items: center;
  justify-content: center;}
.a-recent {display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 0;
  border-top: 1px solid var(--a-line-2);}
.a-recent:first-child {border-top: none;}
.a-recent b {display: block; font-weight: 600; color: var(--a-text); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;}
.a-recent span {color: var(--a-muted); font-size: .82rem;}

/* the checked file next to the report (dashboard.file_chip_html) */
.atsl-chip {display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--a-line); border-radius: 10px;
  padding: 6px 12px; font-size: .86rem; color: var(--a-text); background: var(--a-card); max-width: 100%;}
.atsl-chip svg {flex: 0 0 auto;}
.atsl-chip .nm {overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; font-weight: 600;}
.atsl-chip .sz {color: var(--a-muted); white-space: nowrap; flex: 0 0 auto;}

/* Needs review cards */
.a-flag {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;}
.a-meta {display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--a-muted); font-size: .88rem; margin-top: 2px;}
.a-name {font-size: 1.3rem; font-weight: 700; color: var(--a-text); letter-spacing: -.3px;}

/* Settings: a narrower column, one card per setting group */
.st-key-settings-wrap {max-width: 760px; margin: 0 auto;}
[class*="st-key-card-set"] [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {
  align-items: flex-end;}
[class*="st-key-card-set"] [data-testid="stElementContainer"]:has([data-testid="stNumberInput"]) {
  width: 168px !important; max-width: 100%;}
.st-key-card-set-rules [data-testid="stHorizontalBlock"] {margin-top: 6px;}
.a-set .t {font-weight: 700; font-size: 1.02rem; color: var(--a-text);}
.a-set .s {color: var(--a-muted); font-size: .88rem; margin-top: 2px;}
.a-server {margin: 6px 0 0 0; padding-left: 18px; color: var(--a-text-2); font-size: .9rem;}
.a-server li {overflow-wrap: anywhere;}
.a-server code {font-size: .82rem;}

/* Second opinion (Admin page only): two extra ATS checkers under the Lab score. They are smaller than the
   score card and read the Lab's own numbers; they never change them. */
.so-head {display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  margin: 26px 0 12px 0;}
.so-title {font-size: 1.06rem; font-weight: 700; color: var(--a-text); letter-spacing: -.2px;}
.so-num {display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px;
  border-radius: 6px; background: var(--a-pri-soft); color: var(--a-pri-text); font-size: .72rem; font-weight: 700;
  margin-right: 8px; vertical-align: 1px;}
.so-sub {color: var(--a-muted); font-size: .85rem; font-weight: 500; margin-left: 8px;}
.so-head-right {color: var(--a-ok); font-size: .85rem; font-weight: 600;}
.so-head-right.grey {color: var(--a-muted);}
.so-card {min-width: 0;}
.so-name {font-size: .96rem; font-weight: 700; color: var(--a-text);}
.so-name .so-dot {color: var(--a-muted); font-weight: 600; margin-left: 6px; font-size: .8rem;}
.so-sub2 {color: var(--a-muted); font-size: .8rem; margin-top: 1px;}
.so-top {display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; margin-top: 10px;}
.so-big {font-size: 2rem; font-weight: 800; color: var(--a-text); letter-spacing: -.6px; line-height: 1;}
.so-of {color: var(--a-muted); font-size: .72rem; margin-left: 4px;}
.so-lab {color: var(--a-muted); font-size: .78rem;}
.so-state {color: var(--a-text-2); font-size: .9rem; font-weight: 600; margin-top: 10px;}
.so-note {color: var(--a-muted); font-size: .8rem; margin-top: 4px;}
.so-bar {height: 6px; border-radius: 999px; background: var(--a-line-2); overflow: hidden; margin: 8px 0 4px 0;}
.so-bar i {display: block; height: 100%; background: var(--a-pri);}
.so-kw {display: flex; align-items: baseline; justify-content: space-between; gap: 8px; color: var(--a-muted);
  font-size: .8rem;}
.so-kw b {color: var(--a-text-2); font-weight: 600;}
.so-foot {display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 10px;}
.so-when {color: var(--a-muted); font-size: .76rem;}
.so-section-note {color: var(--a-muted); font-size: .82rem; margin: 12px 0 4px 0;}
.st-key-card-so-matcher, .st-key-card-so-checker2 {padding: 18px 20px;}

@media (max-width: 640px) {
  .block-container, [data-testid="stMainBlockContainer"] {padding-top: 60px !important;}
  .stApp .a-table {min-width: 0;}
  .stApp .a-table, .stApp .a-table tbody, .stApp .a-table tr {display: block;}
  .stApp .a-table tr:first-child {display: none;}
  .stApp .a-table tr {border-bottom: 1px solid var(--a-line-2); padding: 10px 0;}
  .stApp .a-table tr:last-child {border-bottom: none;}
  .stApp .a-table td {display: inline-block; border: none; padding: 4px 10px 4px 0; vertical-align: middle;}
  .stApp .a-table td:last-child {display: block; padding-top: 6px;}
  .a-name {font-size: 1.12rem;}
  .st-key-hist_head {display: none;}
  [class*="st-key-hrow_"] [data-testid="stHorizontalBlock"] {flex-wrap: wrap !important; gap: 4px 12px !important;
    align-items: center;}
  [class*="st-key-hrow_"] [data-testid="stColumn"] {width: auto !important; min-width: 0 !important;
    flex: 0 1 auto !important;}
  [class*="st-key-hrow_"] [data-testid="stColumn"]:nth-child(2) {flex: 1 1 70% !important;}
  [class*="st-key-hrow_"] [data-testid="stColumn"]:last-child {margin-left: auto;}
  [class*="st-key-hrow_"] {padding: 10px 0;}
  .rp .score {justify-content: center;}
  .rp .sbody, .rp .part, .rp .imp > .card {flex-basis: 100%;}
  .rp .card {padding: 16px 14px;}
}
"""

# ---------------------------------------------------------------------------
# The User page: landing page and result
# ---------------------------------------------------------------------------
USER = """
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {
  display: none !important;}
.block-container, [data-testid="stMainBlockContainer"] {max-width: 1128px; padding-top: 0 !important;}
.st-key-topbar {background: var(--a-card); padding: 14px 0; margin-bottom: 44px;
  box-shadow: 0 0 0 100vmax var(--a-card), 0 1px 0 100vmax var(--a-line); clip-path: inset(0 -100vmax -1px -100vmax);}
.st-key-topbar [data-testid="stHorizontalBlock"] {flex-wrap: nowrap; align-items: center; gap: 12px;}
.st-key-topbar [data-testid="stColumn"] {min-width: 0 !important;}
.st-key-topbar [data-testid="stColumn"]:first-child {flex: 0 0 auto !important; width: auto !important;}
.st-key-topbar [data-testid="stColumn"]:last-child {flex: 1 1 auto !important; width: auto !important;}
.st-key-topbar [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {align-items: flex-end;}
.st-key-topbar [data-testid="stColumn"]:last-child [data-testid="stElementContainer"] {width: auto !important;}
.st-key-topbar [data-testid="stLinkButton"] a, .st-key-topbar button {white-space: nowrap;}
.u-brand {display: flex; align-items: center; gap: 10px; min-width: 0;}
.u-brand .logo {font-weight: 800; font-size: 1.45rem; color: var(--a-pri); letter-spacing: -1px;}
.u-brand .badge {font-size: .74rem; font-weight: 600; color: var(--a-pri-text); background: var(--a-pri-soft);
  border: 1px solid var(--a-pri-line); border-radius: 8px; padding: 2px 8px; white-space: nowrap;}
.u-hero {padding-top: 8px;}
.u-hero .pill {display: inline-block; font-size: .74rem; font-weight: 700; letter-spacing: .06em; color: #15803d;
  background: #dcfce7; border: 1px solid #bbf7d0; border-radius: 999px; padding: 5px 13px;}
.u-hero .h1 {font-size: 4rem; line-height: 1.02; font-weight: 800; letter-spacing: -2.4px; color: var(--a-text);
  margin: 22px 0 22px 0; padding: 0;}
.u-hero .h1 .hl {color: var(--a-pri);}
.u-hero p {font-size: 1.12rem; color: var(--a-muted); line-height: 1.6; margin: 0 0 20px 0; max-width: 480px;}
.u-ticks {list-style: none; padding: 0; margin: 0;}
.u-ticks li {display: flex; align-items: center; gap: 10px; color: var(--a-text-2); margin: 0 0 10px 0;
  font-size: .98rem;}
.u-ticks li i {color: #16a34a; font-style: normal; font-weight: 800;}
.st-key-card-upload {box-shadow: 0 10px 30px -12px rgba(16,24,40,.18); border-radius: 20px; padding: 26px 26px;}
.st-key-card-upload .a-h3 {font-size: 1.3rem; margin-bottom: 4px;}
.st-key-card-upload [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {display: none;}
.st-key-card-upload [data-testid="stExpander"] summary > span::after {content: var(--a-add); margin-left: auto;
  color: var(--a-pri); font-weight: 600; font-size: .9rem;}
.st-key-card-upload [data-testid="stExpander"] details[open] summary > span::after {content: "";}
.u-privacy {text-align: center; color: var(--a-muted); font-size: .84rem; margin-top: 4px;}
.u-steps {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 56px;}
.u-step {background: var(--a-card); border: 1px solid var(--a-line); border-radius: 18px; padding: 24px 22px;}
.u-step .k {color: var(--a-pri); font-weight: 700; font-size: .92rem;}
.u-step .t {font-weight: 700; color: var(--a-text); font-size: 1.1rem; margin: 10px 0 6px 0;}
.u-step .s {color: var(--a-muted); font-size: .95rem;}

/* the result */
.u-score {display: flex; flex-wrap: wrap; gap: 24px 40px; align-items: center; background: var(--a-card);
  border: 1px solid var(--a-line); border-radius: 20px; padding: 26px 28px; box-shadow: var(--a-shadow);}
.u-score .left {display: flex; align-items: center; gap: 24px; flex: 1 1 380px; min-width: 0;}
.u-score .head {font-size: 1.55rem; font-weight: 800; color: var(--a-text); letter-spacing: -.5px; line-height: 1.2;
  margin: 10px 0 8px 0;}
.u-score .sub {color: var(--a-muted); font-size: .95rem;}
.u-score .job {color: var(--a-muted); font-size: .84rem; margin-top: 6px;}
.u-parts {flex: 1 1 300px; min-width: 0;}
.u-part {margin: 14px 0 0 0;}
.u-part .row {display: flex; justify-content: space-between; align-items: baseline; gap: 8px;}
.u-part .n {font-weight: 600; color: var(--a-text);} .u-part .v {font-weight: 700; color: var(--a-text);}
.u-part .bar {height: 7px; background: var(--a-line-2); border-radius: 99px; overflow: hidden; margin: 6px 0 4px 0;}
.u-part .bar i {display: block; height: 100%; border-radius: 99px;}
.u-part .s {color: var(--a-muted); font-size: .8rem;}
.u-h2 {font-size: 1.45rem; font-weight: 800; color: var(--a-text); letter-spacing: -.4px; margin: 36px 0 2px 0;}
.u-h2sub {color: var(--a-muted); font-size: .95rem; margin: 0 0 16px 0;}
.u-count {display: inline-flex; align-items: center; gap: 6px; margin: 0 0 14px 0; padding: 7px 14px;
  border-radius: 99px; background: var(--a-pri-soft); color: var(--a-pri-text); font-size: .88rem; font-weight: 700;}
.u-issue {display: flex; gap: 14px; align-items: flex-start; background: var(--a-card); border: 1px solid var(--a-line);
  border-radius: 16px; padding: 16px 18px; margin: 0 0 12px 0;}
.u-issue .k {flex: 0 0 auto; width: 30px; height: 30px; border-radius: 9px; background: var(--a-pri-soft);
  color: var(--a-pri-text); font-weight: 700; display: flex; align-items: center; justify-content: center;}
.u-issue .t {font-weight: 700; color: var(--a-text); display: flex; flex-wrap: wrap; align-items: center; gap: 8px;}
.u-issue .w {color: var(--a-muted); font-size: .93rem; margin-top: 4px;}
.u-lock {position: relative; background: var(--a-card); border: 1px solid var(--a-line); border-radius: 16px;
  padding: 18px; margin: 0 0 12px 0; overflow: hidden; min-height: 140px;}
.u-lock .ghost {filter: blur(5px); opacity: .55;}
.u-lock .ghost div {height: 12px; background: var(--a-line); border-radius: 6px; margin: 12px 0;}
.u-lock .over {position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 6px;}
.u-lock .ic {width: 36px; height: 36px; border-radius: 50%; background: var(--a-pri); color: #fff; display: flex;
  align-items: center; justify-content: center; font-size: 16px;}
.u-lock b {color: var(--a-text);}
.u-lock a {font-size: .88rem; font-weight: 600;}
.st-key-cta {background: var(--a-cta); border-radius: 22px; padding: 30px 32px; margin-top: 28px;}
.st-key-cta [data-testid="stHorizontalBlock"] {align-items: center;}
.u-cta .h2 {color: var(--a-cta-text); font-size: 1.65rem; font-weight: 800; letter-spacing: -.4px; line-height: 1.25;
  margin: 0 0 16px 0; padding: 0;}
.u-cta .wl {display: flex; gap: 12px; align-items: flex-start; color: var(--a-cta-sub); margin: 0 0 10px 0;}
.u-cta .wl i {flex: 0 0 auto; width: 20px; height: 20px; border-radius: 6px; background: rgba(255,255,255,.18);
  color: #fff; font-style: normal; font-size: .75rem; display: flex; align-items: center; justify-content: center;
  margin-top: 2px;}
.st-key-cta [data-testid="stLinkButton"] a {width: 100%; min-height: 48px;}
.stApp .st-key-cta_premium a, .stApp .st-key-cta_premium a:hover {background: #ffffff !important;
  border-color: #ffffff !important; box-shadow: none;}
.stApp .st-key-cta_premium a *, .stApp .st-key-cta_premium a:hover * {color: #312e81 !important;}
.stApp .st-key-cta_session a, .stApp .st-key-cta_session a:hover {background: transparent !important;
  border: 1px solid rgba(255,255,255,.5) !important; box-shadow: none;}
.stApp .st-key-cta_session a *, .stApp .st-key-cta_session a:hover * {color: #ffffff !important;}
.stApp .st-key-cta_session a:hover {border-color: #ffffff !important;}
.u-foot {text-align: center; color: var(--a-muted); font-size: .84rem; margin: 24px 0 0 0;}

@media (max-width: 900px) {
  .u-hero .h1 {font-size: 3rem; letter-spacing: -1.6px;}
}
@media (max-width: 640px) {
  .st-key-topbar {margin-bottom: 24px; padding: 10px 0;}
  .u-brand .badge {display: none;}
  .u-brand .logo {font-size: 1.25rem;}
  .st-key-topbar [data-testid="stLinkButton"] a, .st-key-topbar button {min-height: 38px; padding: 4px 12px;}
  .u-hero .h1 {font-size: 2.45rem; letter-spacing: -1.2px; margin: 16px 0;}
  .u-hero p {font-size: 1rem;}
  .u-steps {grid-template-columns: 1fr; gap: 12px; margin-top: 28px;}
  .st-key-card-upload {padding: 20px 16px;}
  .u-score {padding: 20px 18px;} .u-score .left {gap: 16px; flex-basis: 100%;}
  .u-score .head {font-size: 1.25rem;}
  .st-key-cta {padding: 24px 20px;}
  .u-cta .h2 {font-size: 1.35rem;}
}
"""


def css(*parts, extra=""):
    """The page's <style>: Inter, the palette (the app's own theme first), the base rules, the page's own rules and
    `extra`."""
    return (f'<style>@import url("{FONT_URL}");' + PALETTE + theme_css() + BASE
            + "".join(parts) + extra + "</style>")


def css_text(text):
    """A text for CSS `content:` (the drop zone's words come from lab_text, not from the CSS)."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def drop_zone(main, link, hint, add=""):
    """The drop zone's words ('Drop the PDF here or ' + 'browse', the hint under it) and the "Add" of the job row,
    as CSS variables (the words stay in lab_text.py)."""
    return (f":root {{--a-drop-main: {css_text(main + ' ')}; --a-drop-link: {css_text(link)}; "
            f"--a-drop-hint: {css_text(hint)}; --a-add: {css_text(add)};}}")


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def esc(text):
    """Escaped text for the page ($ escaped too, so Streamlit never reads it as math)."""
    return html.escape(str(text if text is not None else "")).replace("$", "&#36;")


def tone_of(label):
    return LABEL_TONE.get(label, "grey")


def pill(score, label):
    """The colored score box (69 yellow, 19 red, 92 green: the label's tone)."""
    return f'<span class="a-pill a-{tone_of(label)}">{int(float(score or 0))}</span>'


def tag(text, tone="grey", icon=""):
    return f'<span class="a-tag a-{tone}">{icon}{esc(text)}</span>'


def initials(name):
    words = [w for w in str(name or "").replace("(", " ").split() if w[:1].isalpha()]
    return ((words[0][0] + (words[-1][0] if len(words) > 1 else "")) if words else "?").upper()


def avatar(name, primary=False):
    return f'<span class="a-avatar{" pri" if primary else ""}">{esc(initials(name))}</span>'


def who(name, primary=False, bold=True):
    inner = f"<b>{esc(name)}</b>" if bold else f"<span>{esc(name)}</span>"
    return f'<div class="a-who">{avatar(name, primary)}{inner}</div>'


def stat_cards(items):
    """items: (title, value, extra css classes)."""
    cards = "".join(f'<div class="a-stat {cls}"><div class="t">{esc(t)}</div><div class="v">{esc(v)}</div></div>'
                    for t, v, cls in items)
    return f'<div class="a-stats">{cards}</div>'


def ring(score, label=None, size=96, stroke=8, sub=None, number_size=None):
    """A score ring: the score (and the label, or `sub`) inside, the arc in the label's tone."""
    tone = tone_of(label)
    r = (size - stroke) / 2
    circ = 2 * 3.14159265 * r
    filled = circ * max(0.0, min(100.0, float(score or 0))) / 100
    c = size / 2
    inner = f'<div class="n" style="font-size:{number_size or round(size * .3)}px">{int(float(score or 0))}</div>'
    if sub:
        inner += f'<div class="o">{esc(sub)}</div>'
    elif label:
        inner += f'<div class="l" style="color:var(--a-{tone if tone != "grey" else "muted"})">{esc(label)}</div>'
    return (f'<div class="a-ring" style="width:{size}px;height:{size}px">'
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<circle cx="{c}" cy="{c}" r="{r:.1f}" fill="none" stroke="var(--a-line-2)" stroke-width="{stroke}"/>'
            f'<circle cx="{c}" cy="{c}" r="{r:.1f}" fill="none" stroke="{RING_COLOR.get(tone, "var(--a-muted)")}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-dasharray="{filled:.1f} {circ:.1f}" '
            f'transform="rotate(-90 {c} {c})"/></svg><div class="in">{inner}</div></div>')


def bar_tone(value):
    return "ok" if value >= 70 else "warn" if value >= 40 else "bad"


def empty(icon, title, sub=""):
    return (f'<div class="a-empty"><div class="ic">{icon}</div><div class="t">{esc(title)}</div>'
            + (f'<div class="s">{esc(sub)}</div>' if sub else "") + "</div>")


def page_title(title, sub=""):
    return f'<div class="a-title">{esc(title)}</div>' + (f'<p class="a-title-sub">{esc(sub)}</p>' if sub else "")
