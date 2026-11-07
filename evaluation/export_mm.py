"""Export MM-Agent solution json to the paper markdown, using the original
MM-Agent exporter layout (utils.json_to_markdown) with the field names fixed:
  mathematical_formulas -> preliminary_formulas
  result                -> solution_interpretation
  answer                -> subtask_outcome_analysis
Nothing else is added (no five_step_record, verification_plan, code)."""
import glob, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
SRC = os.environ.get("MM_AGENT_OUTPUT", "")  # output folder of an MM-Agent run (<task>_*/json/<task>.json)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "mm_export")

def md(p):
    L = ["# Problem Background", p.get("problem_background", "") + "\n",
         "# Problem Requirement", p.get("problem_requirement", "") + "\n",
         "## Problem Analysis", p.get("problem_analysis", "") + "\n"]
    if "problem_modeling" in p:
        L += ["## Problem Modeling", p["problem_modeling"] + "\n"]
    L.append("## Tasks\n")
    for i, t in enumerate(p.get("tasks", []), 1):
        L += [f"### Task {i}", "#### Task Description", t.get("task_description", "") + "\n",
              "#### Task Analysis", t.get("task_analysis", "") + "\n", "#### Mathematical Formulas"]
        f = t.get("preliminary_formulas", "")
        L += [f"$${x}$$" for x in f] if isinstance(f, list) else ([f"$${f}$$"] if f else [])
        L += ["", "#### Mathematical Modeling Process", t.get("mathematical_modeling_process", "") + "\n",
              "#### Result", t.get("solution_interpretation", "") + "\n",
              "#### Answer", t.get("subtask_outcome_analysis", "") + "\n"]
        for k, c in enumerate(t.get("charts", []) or [], 1):
            L += [("#### Charts" if k == 1 else ""), f"##### Chart {k}", str(c) + "\n"]
    return "\n".join(L)

if __name__ == "__main__":
    for f in sorted(glob.glob(SRC + "/*/json/*.json")):
        task = os.path.basename(f)[:-5]
        p = json.load(open(f, encoding="utf-8"))
        s = md(p)
        open(os.path.join(OUT, f"{task}.md"), "w", encoding="utf-8").write(s)
        print(task, len(s) // 1000, "k chars;", "empty results:", sum(1 for t in p["tasks"] if not t.get("solution_interpretation")))
