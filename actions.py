"""Where does the crew's day actually go?

Counts every unit action the agent issues, split into farm work, flock work and
walking, alongside the flock's realised output. Use it to check that a change
bought more production rather than just more commuting.

    uv run actions.py --seed 2003 --opp pass
"""

import argparse
from collections import Counter

from kaggle_environments import make

import main

MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
FLOCK_OPS = {"FEED", "CARE", "COLLECT_FERTILIZER", "BUILD_COOP", "PLACE", "PICKUP"}


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2003)
    ap.add_argument("--opp", default="pass")
    args = ap.parse_args()

    per_day = {}

    def traced(obs):
        result = main.agent(obs)
        day = obs.get("day", 0)
        c = per_day.setdefault(day, Counter())
        me = obs["farms"][obs["player"]]
        for act in [result["farmer"], *result["hands"]]:
            op = act[0] if act else "PASS"
            if op in MOVES:
                c["MOVE"] += 1
            elif op == "HARVEST":
                # Same op for crops and coops; split by what is underfoot.
                c["HARVEST"] += 1
            else:
                c[op] += 1
        birds = [t for row in me["tiles"] for t in row
                 if isinstance(t, dict) and "animal" in t]
        c["birds"] = len(birds)
        c["eggs_held"] = sum(t.get("yield_units", 0) for t in birds)
        c["fed"] = sum(1 for t in birds if t.get("fed_today"))
        c["cared"] = sum(1 for t in birds if t.get("cared_today"))
        return result

    env = make("kaggriculture", configuration={"seed": args.seed})
    env.run([traced, args.opp])

    print(f"{'day':>3} {'birds':>5} {'fed':>4} {'card':>4} {'held':>4} "
          f"{'MOVE':>5} {'PASS':>5} {'WATER':>5} {'PLANT':>5} {'HARV':>5} "
          f"{'FEED':>5} {'CARE':>5} {'FERT':>5} {'PICK':>5} {'DROP':>5}")
    tot = Counter()
    for day in sorted(per_day):
        c = per_day[day]
        tot.update({k: v for k, v in c.items()
                    if k not in ("birds", "eggs_held", "fed", "cared")})
        print(f"{day:>3} {c['birds']:>5} {c['fed']:>4} {c['cared']:>4} "
              f"{c['eggs_held']:>4} {c['MOVE']:>5} {c['PASS']:>5} {c['WATER']:>5} "
              f"{c['PLANT']:>5} {c['HARVEST']:>5} {c['FEED']:>5} {c['CARE']:>5} "
              f"{c['COLLECT_FERTILIZER']:>5} {c['PICKUP']:>5} {c['DROP']:>5}")

    total = sum(tot.values())
    print(f"\ntotal unit-actions: {total:,}")
    for op, n in tot.most_common():
        print(f"  {op:<20} {n:>6,}  {n / total:>5.1%}")
    print(f"\nFinal: ${env.steps[-1][0].reward:,.0f}")


main_()
