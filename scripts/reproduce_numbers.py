"""Recompute the numbers reported in the paper from results/*.csv.

    python scripts/reproduce_numbers.py

Standard library only; no API calls.
"""
import csv
import statistics
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(__file__).resolve().parent.parent / "results"
SYSTEMS = ["QDM", "ClaudeCode", "MM"]


def rows(name):
    with open(R / name, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def audit():
    items = rows("audit_items.csv")
    st = Counter(r["state"] for r in items)
    by = defaultdict(list)
    for r in items:
        by[r["problem"]].append(r["state"])
    open_ = st["U"] + st["M"]
    half = sum(1 for v in by.values() if sum(s in "UM" for s in v) >= len(v) / 2)
    print("== Audit (Table 1)")
    print(f"  problems {len(by)}, items {len(items)}, E/U/M {st['E']}/{st['U']}/{st['M']}")
    print(f"  open {open_} = {100 * open_ / len(items):.1f}%; problems with at least half open: {half}")
    for layer in sorted({r["layer"] for r in items}):
        s = [r["state"] for r in items if r["layer"] == layer]
        print(f"  {layer}: {len(s)} items, open {100 * sum(x in 'UM' for x in s) / len(s):.1f}%")


def mmbench():
    sc = {}
    for r in rows("mmbench_scores.csv"):
        d = {k: float(r[k]) for k in ("AE", "MR", "PS", "RBA")}
        d["Total"] = sum(d.values()) / 4
        sc[(r["problem"], r["system"], r["run"])] = d
    tasks = sorted({k[0] for k in sc})
    mean = {(t, m): {d: (sc[(t, m, "1")][d] + sc[(t, m, "2")][d]) / 2 for d in sc[(t, m, "1")]}
            for t in tasks for m in SYSTEMS}
    print("\n== MMBench (Fig. 2a; mean of two scoring runs)")
    for m in SYSTEMS:
        print(f"  {m:10s} " + "  ".join(
            f"{d} {statistics.mean(mean[(t, m)][d] for t in tasks):.2f}" for d in ("AE", "MR", "PS", "RBA", "Total")))
    for base in ("ClaudeCode", "MM"):
        wins = sum(mean[(t, "QDM")]["Total"] > mean[(t, base)]["Total"] for t in tasks)
        p = 2 * sum(comb(len(tasks), k) for k in range(wins, len(tasks) + 1)) / 2 ** len(tasks)
        gap = statistics.mean(mean[(t, "QDM")]["Total"] - mean[(t, base)]["Total"] for t in tasks)
        print(f"  QDM above {base}: {wins}/{len(tasks)}, mean margin {gap:.2f}, sign test p = {p:.4f}")
    a = [sc[(t, m, "1")]["Total"] for t in tasks for m in SYSTEMS]
    b = [sc[(t, m, "2")]["Total"] for t in tasks for m in SYSTEMS]
    print(f"  correlation of paper totals between runs r = {statistics.correlation(a, b):.2f}")
    print("  per problem: " + "; ".join(
        f"{t} " + "/".join(f"{mean[(t, m)]['Total']:.2f}" for m in SYSTEMS) for t in tasks))
    return mean, tasks


def questioner_split(mean, tasks):
    runs = {r["problem"]: r for r in rows("qdm_runs.csv")}
    ds = [t for t in tasks if all(x.startswith("deepseek") for x in
                                  (s.split(":")[0] for s in runs[t]["questioner_model_rounds"].split(";")))]
    print("\n== QDM runs (Table S2) and questioner model (Section S1)")
    for t in tasks:
        r = runs[t]
        print(f"  {t}: {r['question_rounds']} rounds, {r['model_calls']} calls, questioner {r['questioner_model_rounds']}")
    for name, grp in (("DeepSeek questioner", ds), ("GPT questioner", [t for t in tasks if t not in ds])):
        for base in ("ClaudeCode", "MM"):
            m = [mean[(t, "QDM")]["Total"] - mean[(t, base)]["Total"] for t in grp]
            print(f"  {name} ({len(grp)} problems) vs {base}: wins {sum(x > 0 for x in m)}/{len(m)}, "
                  f"mean margin {statistics.mean(m):.2f}")


def review():
    by = defaultdict(list)
    for r in rows("ai_scientist_review.csv"):
        by[r["system"]].append(r)
    print("\n== AI Scientist reviewer (Fig. 2b)")
    for m in SYSTEMS:
        rv = by[m]
        out = []
        for k in ("soundness", "presentation", "clarity", "overall"):
            v = [float(r[k]) for r in rv if r[k] != ""]
            out.append(f"{k} {statistics.mean(v):.2f}" + (f" (n={len(v)})" if len(v) < len(rv) else ""))
        acc = sum(r["decision"].lower().startswith("accept") for r in rv)
        chars = statistics.mean(int(r["paper_chars"]) for r in rv) / 1000
        print(f"  {m:10s} " + "  ".join(out) + f"  accepted {acc}/{len(rv)}  mean length {chars:.0f}k chars")


def controlled():
    q = rows("controlled_questions.csv")
    asked = Counter(r["condition"] for r in q)
    defect = Counter(r["condition"] for r in q if r["label"] == "DEFECT")
    by_model = Counter(r["model"] for r in q if r["label"] == "DEFECT" and r["condition"] == "D")
    print("\n== Controlled experiment (Fig. 3)")
    print("  defect-pointing questions: " + ", ".join(f"{c} {defect[c]}/{asked[c]}" for c in "BCD"))
    print("  under D by model: " + ", ".join(f"{m} {n}" for m, n in sorted(by_model.items())))
    req = rows("controlled_requirements.csv")
    for c in "ABCD":
        s = sum(int(r["settled"]) for r in req if r["condition"] == c)
        n = sum(int(r["total"]) for r in req if r["condition"] == c)
        per = " ".join(f"{t} {sum(int(r['settled']) for r in req if r['condition'] == c and r['problem'] == t)}/"
                       f"{sum(int(r['total']) for r in req if r['condition'] == c and r['problem'] == t)}"
                       for t in sorted({r['problem'] for r in req}))
        print(f"  requirements settled {c}: {s}/{n} = {100 * s / n:.1f}%   ({per})")


if __name__ == "__main__":
    audit()
    mean, tasks = mmbench()
    questioner_split(mean, tasks)
    review()
    controlled()
