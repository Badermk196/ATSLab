"""
Keep the ATS Lab awake on Streamlit Cloud.

Streamlit Community Cloud puts an app to sleep after about 12 hours without a visitor. This script
opens the app in a headless browser, clicks "Yes, get this app back up!" when the sleep page appears,
and waits until the app is really running. It is run by .github/workflows/keep-awake.yml every 4 hours.

It never sends a resume, a password or a token: it only opens the public address and clicks the
wake-up button. No account is needed.

Exit code 0 when the app is awake (or was woken), 1 when the address could not be reached.
The output is short on purpose: the GitHub Actions log shows what happened.
"""

import os
import sys

from playwright.sync_api import sync_playwright

URL = os.environ.get("ATSLAB_URL", "https://1000jobs-atslab.streamlit.app")
WAKE_WORDS = ("get this app back up", "app back up", "wake", "zzz")
AWAKE_WORDS = ("1000jobs", "ats lab", "check a resume", "dashboard")
TIMEOUT = 90_000          # ms for the first load
AWAKE_WAIT = 180_000      # ms to wait for the app after the wake-up click


def log(message):
    print(message, flush=True)


def text_of(page):
    try:
        return (page.inner_text("body") or "").lower()
    except Exception:
        return ""


def wake_button(page):
    """The "Yes, get this app back up!" button, when the sleep page is showing."""
    for name in ("Yes, get this app back up!", "get this app back up", "Yes, get this app back up"):
        try:
            button = page.get_by_role("button", name=name)
            if button.count() and button.first.is_visible():
                return button.first
        except Exception:
            continue
    return None


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
        except Exception as e:
            log(f"could not reach {URL}: {type(e).__name__}")
            browser.close()
            return 1

        page.wait_for_timeout(4000)
        body = text_of(page)
        slept = any(word in body for word in WAKE_WORDS)
        button = wake_button(page)
        if button is not None:
            log("the app was asleep: clicking the wake-up button")
            try:
                button.click(timeout=15000)
            except Exception as e:
                log(f"the wake-up click failed: {type(e).__name__}")
        elif slept:
            log("the page looks like the sleep page, but no wake-up button was found")
        else:
            log("the app answered without a sleep page")

        # wait until the app itself is on the page, not the sleep page
        deadline = AWAKE_WAIT
        step = 5000
        waited = 0
        while waited < deadline:
            page.wait_for_timeout(step)
            waited += step
            body = text_of(page)
            if any(word in body for word in AWAKE_WORDS) and not (
                    "get this app back up" in body and "zzz" in body):
                log(f"the app is awake after {waited // 1000} s")
                browser.close()
                return 0
        log(f"the app did not show its page within {deadline // 1000} s")
        browser.close()
        return 0 if not slept else 1


if __name__ == "__main__":
    sys.exit(main())
