"""Why so few job skills are found: for every job skill in every pair, is it really absent from the resume, in the
text but missed by the Lab, or only inside glued words? Also: how long and how specific the job skills are."""
import collections
import json
import os
import re
import sys

import pandas as pd

S = sys.argv[1]
pairs = pd.read_csv(os.path.join(S, "pairs.csv")).set_index("pair")
texts = pd.read_csv(os.path.join(S, "resumes.csv")).set_index("resume").text
rows = [json.loads(l) for l in open(os.path.join(S, "results.jsonl"), encoding="utf-8") if l.strip()]
cat = collections.Counter()
by_fit = collections.defaultdict(collections.Counter)
missed_examples, absent_terms, words = [], collections.Counter(), collections.Counter()
for r in rows:
    p = pairs.loc[r["pair"]]
    low = texts[p.resume].lower()
    flat = re.sub(r"[^a-z0-9+#]", "", low)
    for k in r["keywords"]:
        if k["type"] == "soft":
            continue
        t = k["term"].lower()
        words[min(len(t.split()), 4)] += 1
        if k["match"] != "missing":
            c = "found by the Lab"
        elif re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low):
            c = "in the text, missed by the Lab"
            if len(missed_examples) < 25:
                i = low.find(t)
                missed_examples.append((r["pair"], k["term"], texts[p.resume][max(0, i - 40):i + len(t) + 40]))
        elif re.sub(r"[^a-z0-9+#]", "", t) in flat:
            c = "only glued to other words / other spacing"
        else:
            c = "not in the resume"
            if p.fit:
                absent_terms[k["term"]] += 1
        cat[c] += 1
        by_fit["fit" if p.fit else "no fit"][c] += 1
tot = sum(cat.values())
print("job skills checked:", tot)
for c, n in cat.most_common():
    print(f"  {c:45} {n:5} ({100 * n / tot:.0f}%)")
for f, cc in by_fit.items():
    t = sum(cc.values())
    print(f, {c: f"{100 * n / t:.0f}%" for c, n in cc.items()})
print("skill length in words:", dict(sorted(words.items())))
print("\nmissed by the Lab although in the text (examples):")
for e in missed_examples:
    print(" ", e[0], "|", e[1], "|", repr(e[2]))
print("\nskills most often absent from GOOD FIT resumes:")
for t, n in absent_terms.most_common(40):
    print(f"  {n:3} {t}")
