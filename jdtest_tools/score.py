"""Score every pair the way the dashboard does (with the job, AI reviewer OFF), 4 processes.
Saves one JSON line per pair: Resume Score, Job Match, parts, each Job Match check (average of the 3 ATS), keywords.

  py -3.12 -P -E score.py <sample folder> [workers]
"""
import json
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, r"C:\ATSLab")
os.environ["ATSLAB_AI_REVIEW"] = "0"
SAMPLE = sys.argv[1]
JM_CHECKS = ("F1", "F2", "F3", "F4", "M1", "M2", "M3", "M4", "M5")
D = None


def init():
    global D
    os.environ["ATSLAB_AI_REVIEW"] = "0"
    import dashboard
    dashboard.AI_REVIEW = False
    D = dashboard


def one(task):
    pair, rid, jid, title = task
    with open(os.path.join(SAMPLE, "jobs", f"{jid}.txt"), encoding="utf-8") as f:
        text = f.read().strip()
    with open(os.path.join(SAMPLE, "resumes", f"{rid}.pdf"), "rb") as f:
        data = f.read()
    t0 = time.time()
    try:
        r = D.run_check(data, f"{rid}.pdf", True, text, cache=os.path.join(SAMPLE, "lab_jobs"), job_title=title)
    except D.CheckError as e:
        return {"pair": pair, "error": str(e), "secs": round(time.time() - t0, 1)}
    res = r["v3"]
    checks = {}
    for n in JM_CHECKS:
        vals = [res["ats"][p]["checks"][n] for p in res["ats"] if n in res["ats"][p]["checks"]]
        sc = [c["score"] for c in vals if c["score"] is not None]
        if vals:
            checks[n] = {"name": vals[0]["name"], "part": vals[0]["part"], "weight": vals[0]["weight"],
                         "score": round(sum(sc) / len(sc), 1) if sc else None,
                         "oracle": res["ats"].get("oracle", {}).get("checks", {}).get(n, {}).get("score"),
                         "detail": res["ats"].get("oracle", {}).get("checks", {}).get(n, {}).get("detail")}
    return {"pair": pair, "score": r["score"], "label": r["label"], "parts": r["parts"],
            "job_match": r["parts"].get("job_match"), "checks": checks,
            "keywords": [{k: x.get(k) for k in ("term", "type", "match")} for x in res["keywords"]],
            "experience_years": r["experience_years"], "job_title": res.get("job_title"),
            "gates": r["gates"], "secs": round(time.time() - t0, 1)}


if __name__ == "__main__":
    import pandas as pd
    pairs = pd.read_csv(os.path.join(SAMPLE, "pairs.csv"))
    with open(os.path.join(SAMPLE, "jobs.json"), encoding="utf-8") as f:
        jobs = json.load(f)
    out_path = os.path.join(SAMPLE, "results.jsonl")
    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            done = {json.loads(l)["pair"] for l in f if l.strip()}
    tasks = [(p.pair, p.resume, p.job, jobs[p.job]["title"]) for p in pairs.itertuples() if p.pair not in done]
    print(f"{len(tasks)} pairs to score ({len(done)} done)", flush=True)
    t0 = time.time()
    with Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 4, initializer=init) as pool, \
            open(out_path, "a", encoding="utf-8") as out:
        for k, row in enumerate(pool.imap_unordered(one, tasks), 1):
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if k % 25 == 0 or k == len(tasks):
                print(f"{k}/{len(tasks)} in {time.time() - t0:.0f}s", flush=True)
