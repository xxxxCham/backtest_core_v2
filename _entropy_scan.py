import re, os

targets = [
    "agents/strategy_builder.py",
    "ui/builder_view.py",
    "agents/builder_code_repair.py",
    "agents/builder_code_validation.py",
    "agents/builder_validation.py",
    "agents/builder_candidate_executor.py",
    "agents/builder_loop.py",
    "ui/exec_tabs.py",
    "ui/main.py",
]

for fp in targets:
    if not os.path.exists(fp):
        continue
    with open(fp, encoding="utf-8") as f:
        code = f.read()
    n = len(code.splitlines())
    te = len(re.findall(r"^\s*except\b", code, re.M))
    ga = len(re.findall(r"getattr\(", code))
    gt = len(re.findall(r"\.get\(", code))
    ii = len(re.findall(r"isinstance\(", code))
    ha = len(re.findall(r"hasattr\(", code))
    t = te + ga + gt + ii + ha
    print(f"{fp:48s} {n:5d}L  ex={te:3d} ga={ga:3d} gt={gt:3d} is={ii:3d} ha={ha:3d} T={t:4d}")
