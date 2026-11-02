"""
1000Jobs ATS Lab - the app: two pages, each with its own link.

  /user  (and the bare address /)   the User page, for job seekers: share only this link
  /admin                            the Admin page, for the 1000Jobs team (name + password)

  py -3.12 run_app.py          (or: py -3.12 -m streamlit run app.py)

Secrets and settings: lab_settings.py; how to run it on a server: DEPLOY.md. The scoring is not changed here
(cv_score.py, version 1.0). The one-page dashboard (dashboard.py) still runs on its own too.
"""

import streamlit as st

import admin_page
import streamlit_fix
import user_page

streamlit_fix.apply()           # also for a server started with "streamlit run app.py" (run_app.py applies it earlier)

# (link, page, browser tab title). The first one is also the bare address "/".
LINKS = (("user", user_page.user, "1000Jobs Resume Check"),
         ("admin", admin_page.admin, "1000Jobs ATS Lab - Admin"))
SIDEBAR = {"user": "collapsed", "admin": "expanded"}      # the Admin page has the left menu, the User page none


def with_layout(page, link):
    """The page with its own layout: wide (the design sets its own widths), the sidebar open on the Admin page."""
    def run():
        st.set_page_config(layout="wide", initial_sidebar_state=SIDEBAR[link])
        page()
    run.__name__ = f"{link}_page"
    return run


def pages():
    """The st.Page list (made while the app runs: Streamlit needs its run context for it)."""
    link, page, title = LINKS[0]
    return [st.Page(with_layout(page, link), title=title, url_path="start", default=True)] + \
        [st.Page(with_layout(page, link), title=title, url_path=link) for link, page, title in LINKS]


def main():
    st.set_page_config(page_title="1000Jobs ATS Lab", page_icon="📄", layout="wide")
    st.navigation(pages(), position="hidden").run()    # no menu: each page is opened by its own link


if __name__ == "__main__":      # streamlit runs this file as __main__; tests import it to check the links
    main()
