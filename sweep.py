"""Sweep tunables against a frozen, env-immune opponent.

Supersedes `tune.py` for anything intended to ship. `tune.py` passes `KAG_*`
through to a `.py` opponent as well as to us, so both sides move together and
the sweep silently measures a mirror match (see PROJECT_STATUS.md, Phase 13).
This freezes the opponent with `freeze.py` first, so only our side changes.

    python sweep.py MAX_ANIMALS 8 10 12 14
    python sweep.py --games 32 GOOSE_ENABLED 0 1
    python sweep.py --ref 8a5925b MAX_LAND_BUYS 1 2      # vs some other commit
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def build_frozen(ref, workdir):
    """git show <ref>:main.py -> frozen (defaults-only) opponent file."""
    raw = os.path.join(workdir, "ref_raw.py")
    out = os.path.join(workdir, "ref_frozen.py")
    with open(raw, "w") as fh:
        subprocess.run(["git", "show", f"{ref}:main.py"], stdout=fh, cwd=HERE, check=True)
    subprocess.run([sys.executable, "freeze.py", raw, out], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL)
    return out


def run(opp, games, seed0, overrides):
    env = dict(os.environ)
    for k, v in overrides.items():
        env["KAG_" + k] = str(v)
    out = subprocess.run(
        [sys.executable, "bench.py", "--agent", "main.py", "--opp", opp,
         "-n", str(games), "--seed0", str(seed0), "--swap", "--workers", "16"],
        capture_output=True, text=True, env=env, cwd=HERE,
    )
    mean = opp_mean = None
    wr = ""
    for line in out.stdout.splitlines():
        if "mean" in line:
            nums = re.findall(r"\$\s*([\d,]+)", line)
            if len(nums) >= 2:
                mean, opp_mean = (float(n.replace(",", "")) for n in nums[:2])
        elif "winrate" in line:
            wr = line.split("=")[-1].strip()
    if mean is None:
        print(out.stdout, out.stderr, file=sys.stderr)
        return None
    return mean, opp_mean, wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD", help="commit whose main.py is the opponent")
    ap.add_argument("--games", type=int, default=32, help="seeds; doubled by --swap")
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("name")
    ap.add_argument("values", nargs="+")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as workdir:
        opp = build_frozen(args.ref, workdir)
        print(f"opponent: frozen {args.ref}   ({args.games * 2} games, seed0={args.seed0})\n")

        base = run(opp, args.games, args.seed0, {})
        print(f"{'baseline':>16}  ${base[0]:>10,.0f}  vs ${base[1]:>10,.0f}"
              f"   {base[2]:>10}")
        for v in args.values:
            r = run(opp, args.games, args.seed0, {args.name: v})
            if r is None:
                continue
            print(f"{args.name + '=' + str(v):>16}  ${r[0]:>10,.0f}  vs ${r[1]:>10,.0f}"
                  f"   {r[2]:>10}   {r[0] - r[1]:+,.0f} margin")


main()
