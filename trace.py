"""Per-day trace of one episode, for diagnosing agent behaviour."""

import argparse

from kaggle_environments import make

import main


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--opp", default="random")
    ap.add_argument("--hour", type=int, default=12)
    args = ap.parse_args()

    log = []

    def traced(obs):
        result = main.agent(obs)
        if obs.get("hour") == args.hour:
            me = obs["farms"][obs["player"]]
            priv = obs.get("private", {})
            tiles = me["tiles"]
            counts = {}
            empty = weed = locked = coop = birds = 0
            for row in tiles:
                for t in row:
                    if t == "LOCKED":
                        locked += 1
                    elif t is None:
                        empty += 1
                    elif isinstance(t, dict):
                        if "animal" in t:
                            birds += 1
                        elif t.get("kind") in ("COOP", "PASTURE"):
                            coop += 1
                        elif t.get("kind") == "WEED":
                            weed += 1
                        elif t.get("kind") == "PLANT":
                            counts[t["crop"]] = counts.get(t["crop"], 0) + 1
            shed = {k: v for k, v in priv.get("shed", {}).items() if v}
            seeds = {k: v for k, v in priv.get("seeds", {}).items() if v}
            prices = {k: v for k, v in obs["market"]["prices"].items()
                      if k in ("WHEAT", "MELON", "STRAWBERRY", "EGG", "FERTILIZER")}
            log.append(
                f"D{obs['day']:2d} ${me['money']:>8,.0f} hands={len(me['hands']):>2} "
                f"land={len(me['unlocked_quadrants'])} free={empty:>2} weed={weed:>2} "
                f"birds={birds}/{birds + coop} "
                f"plants={counts} seeds={seeds} shed={shed} px={prices}"
            )
        return result

    env = make("kaggriculture", configuration={"seed": args.seed}, debug=True)
    env.run([traced, args.opp])
    print("\n".join(log))
    print(f"\nFinal: ${env.steps[-1][0].reward:,.0f} vs ${env.steps[-1][1].reward:,.0f}")


main_()
