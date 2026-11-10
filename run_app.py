"""
Start the app (app.py) with the Streamlit fix applied before the server starts (streamlit_fix.py).

  py -3.12 run_app.py --server.port 8501 --server.headless true --server.address 127.0.0.1

Any Streamlit option can follow; it is the same as "streamlit run app.py <options>".
"""

import os
import shutil
import sys

import streamlit_fix

HERE = os.path.dirname(os.path.abspath(__file__))

RENDER_SECRETS = "/etc/secrets/secrets.toml"                        # Render's "Secret File" path
LOCAL_SECRETS = os.path.join(HERE, ".streamlit", "secrets.toml")    # where the app reads it


def use_render_secrets():
    """On Render the secrets file arrives as a "Secret File" at /etc/secrets/secrets.toml, while the app
    reads .streamlit/secrets.toml next to app.py. Copy it once, before the server starts.
    The file content is never printed or logged; only the paths are."""
    if not os.path.isfile(RENDER_SECRETS):
        return                      # not Render (on this PC there is no /etc/secrets): keep the current behaviour
    if os.path.exists(LOCAL_SECRETS):
        return                      # already in place: nothing to do
    try:
        os.makedirs(os.path.dirname(LOCAL_SECRETS), exist_ok=True)
        shutil.copyfile(RENDER_SECRETS, LOCAL_SECRETS)
        try:
            os.chmod(LOCAL_SECRETS, 0o600)      # the secrets file stays private to the app
        except OSError:
            pass
        print("secrets: copied %s to %s" % (RENDER_SECRETS, LOCAL_SECRETS), flush=True)
    except Exception as e:          # a clear message with the paths, never the content
        print("secrets: could not copy %s to %s (%s). The app keeps running without it."
              % (RENDER_SECRETS, LOCAL_SECRETS, type(e).__name__), flush=True)


if __name__ == "__main__":
    use_render_secrets()
    streamlit_fix.apply()
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", os.path.join(HERE, "app.py"), *sys.argv[1:]]
    sys.exit(cli.main())
