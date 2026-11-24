"""
Speed table: one admin page load per view and one full check, with the time of each part.

  py -3.12 profile_speed.py            (needs DATABASE_URL in .streamlit/secrets.toml for the Neon numbers; read only)

The model is the one saved on this PC (HF_HUB_OFFLINE=1: it is never downloaded). The AI review line is one real call
unless a review is already saved. The database lines count every statement sent to Postgres.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
os.environ["HF_HUB_OFFLINE"] = "1"                      # never download the model
os.environ.setdefault("ATSLAB_WARMUP", "0")


def page_table():
    import lab_db
    import lab_timing as TM
    from streamlit.testing.v1 import AppTest

    def app():
        import admin_page
        admin_page.admin()

    rows = []
    for view in ("check", "history", "review", "settings", "log", "bugs"):
        for run in (1, 2):
            TM.reset_all()
            at = AppTest.from_function(app, default_timeout=180)
            at.session_state["admin"] = "Bader"
            at.session_state["admin_view"] = view
            began = time.perf_counter()
            at.run()
            total = time.perf_counter() - began
            if at.exception:
                print("  page error:", str(at.exception[0].value)[:200])
            calls, db = TM.snapshot_all().get("database", (0, 0.0))
            rows.append((view, "first load of a visitor" if run == 1 else "next click", total, calls, db))
    print(f"{'view':10s} {'run':26s} {'page s':>7s} {'db calls':>9s} {'db s':>7s}")
    for view, run, total, calls, db in rows:
        print(f"{view:10s} {run:26s} {total:7.2f} {calls:9d} {db:7.2f}")


def check_table(with_review):
    import ATSLab_v3 as L
    import cv_layout as Y
    import cv_review as R
    import cv_score as C
    import dashboard as D
    import lab_reuse
    import test_dashboard as T
    if with_review:
        D.AI_REVIEW = True
    D.fresh_modules()
    acc = {}

    def wrap(mod, name, label):
        fn = getattr(mod, name)

        def timed(*a, **k):
            began = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                acc[label] = acc.get(label, 0.0) + time.perf_counter() - began
        setattr(mod, name, timed)
    wrap(L, "embedder_ok", "AI model: safety probe")
    wrap(L, "_load_embedder", "AI model: load")
    wrap(L, "extract_cv", "PDF reading")
    wrap(Y, "analyse_layout", "page picture + layout")
    wrap(R, "review_cv", "AI review (network)")
    wrap(C, "score_cv", "score_cv total")
    cache = tempfile.mkdtemp()
    T.seed(cache)
    pdf, job = T.cv_bytes(), T.job_text()
    for n, label in ((1, "first check in a fresh server"), (2, "same file again (result reused)")):
        acc.clear()
        began = time.perf_counter()
        if n == 1:
            r = D.run_check(pdf, "Neda.pdf", True, job, cache, cache, job_title="Delivery Lead")
            lab_reuse.run(lambda *a, **k: r, pdf, "Neda.pdf", True, job, job_title="Delivery Lead",
                          version=D.SCORE_VERSION)                       # saves it, as the pages do
        else:
            r = lab_reuse.run(lambda *a, **k: 1 / 0, pdf, "Neda.pdf", True, job, job_title="Delivery Lead",
                              version=D.SCORE_VERSION)
        total = time.perf_counter() - began
        print(f"\ncheck {n} ({label}): {total:.2f}s  score={r['score']}")
        rules = acc.get("score_cv total", 0.0) - sum(v for k, v in acc.items() if k.startswith(("AI model", "page", "AI review")))
        for k, v in sorted(acc.items()):
            print(f"    {k:28s} {v:7.2f}s")
        if acc:
            print(f"    {'rules and the rest of score_cv':28s} {rules:7.2f}s")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "pages"):
        page_table()
    if what in ("all", "check"):
        check_table(with_review=os.environ.get("ATSLAB_AI_REVIEW", "1") != "0")
