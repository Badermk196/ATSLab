"""
A fix for Streamlit 1.58 with Starlette 1.x (no scoring here).

Streamlit's gzip middleware holds back the "start" message of every answer and lets Starlette send it later. Starlette
1.x sends the start message at once for a type it never compresses (a PNG image such as /favicon.png, a zip, a font)
and later sends only the body, so the start message is never sent: "Expected ASGI message 'http.response.start', but
got 'http.response.body'" and a 500 error. Streamlit's override only adds audio/ and video/ to the types never
compressed, which Starlette 1.x already leaves out by itself, so Starlette's own method is put back.

apply() is called by run_app.py before the server starts, and by app.py (for a server started with
"streamlit run app.py"). It changes nothing when the versions do not have this problem.
"""


def apply():
    """-> True when the fix is in place (or was already), False when this Streamlit / Starlette does not need it."""
    try:
        from starlette.middleware import gzip as G
        from streamlit.web.server.starlette import starlette_gzip_middleware as M
    except ImportError:
        return False
    starlette_excludes_media = all(any(t.startswith(p) for t in G.DEFAULT_EXCLUDED_CONTENT_TYPES)
                                   for p in ("audio/", "video/"))
    if not hasattr(G.IdentityResponder(None, 0), "partial_response") or not starlette_excludes_media:
        return False                        # an older Starlette: Streamlit's own code is right for it
    for ours, base in ((M._MediaAwareGZipResponder, G.GZipResponder),
                       (M._MediaAwareIdentityResponder, G.IdentityResponder)):
        if "send_with_compression" in ours.__dict__:
            ours.send_with_compression = base.send_with_compression
    return True
