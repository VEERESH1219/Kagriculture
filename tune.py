"""One-parameter-at-a-time sweep over main.py's KAG_* tunables.

    uv run tune.py MAX_UNITS 13 15 17
"""

import os
import statistics
import subprocess
import sys


def score(name, value, games, seed0):
    env = dict(os.environ, KAG_DEBUG="1")
    if name != "BASE":
        env["KAG_" + name] = str(value)
    # `pass` is deterministic; the built-in `random` agent seeds itself from the
    # clock, which adds a few percent of noise and drowns small effects.
    out = subprocess.run(
        [sys.executable, "bench.py", "-n", str(games), "--seed0", str(seed0),
         "--workers", "16", "--opp", os.environ.get("TUNE_OPP", "pass")],
        capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    for line in out.stdout.splitlines():
        if "mean" in line:
            return float(line.split("$")[1].split()[0].replace(",", ""))
    print(out.stdout, out.stderr)
    return 0.0


def main():
    name = sys.argv[1]
    values = sys.argv[2:]
    games, seed0 = 16, 2000
    base = score("BASE", None, games, seed0)
    print(f"{'baseline':>12}  ${base:>10,.0f}")
    for v in values:
        s = score(name, v, games, seed0)
        print(f"{name}={v:>7}  ${s:>10,.0f}   {s - base:+,.0f}")


main()
