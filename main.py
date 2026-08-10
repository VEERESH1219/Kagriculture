from kaggle_environments import make

from collections import deque
import heapq

from kaggle_environments import make

def agent(obs):
    """
    Improved Agent
    - Smarter movement
    - Weed clearing
    - Hires 1 farm hand
    - Plants Melon (high value) + some Wheat
    """
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {})
    day = obs.get("day", 0)
    step = obs.get("step", 0)

    fx, fy = me["farmer"]
    tiles = me["tiles"]
    height = len(tiles)
    width = len(tiles[0]) if height > 0 else 0
    hands = me.get("hands", [])
    money = me.get("money", 0)

    def get_tile(x, y):
        if 0 <= y < height and 0 <= x < width:
            return tiles[y][x]
        return "LOCKED"

    tile = get_tile(fx, fy)
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})

    market = []
    farmer_action = ["PASS"]
    hands_actions = [["PASS"] for _ in hands]

    # -------------------------------------------------
    # 1. Market: Buy seeds + Sell + Hire
    # -------------------------------------------------

    # Prefer Melon if we can afford it, otherwise Wheat
    if seeds.get("MELON", 0) == 0 and money >= 80:
        market.append(["BUY_SEED", "MELON", 1])
    elif seeds.get("WHEAT", 0) == 0 and money >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])

    # Sell everything valuable from shed
    for item in ["MELON", "WHEAT"]:
        qty = shed.get(item, 0)
        if qty > 0:
            market.append(["SELL", item, qty])

    # Hire 1 farm hand if we have none and enough money
    if len(hands) == 0 and money >= 30 and step > 10:
        market.append(["HIRE"])

    # -------------------------------------------------
    # 2. Helper: decide action for a unit on a tile
    # -------------------------------------------------
    def decide_action(current_tile, unit_seeds):
        if isinstance(current_tile, dict):
            kind = current_tile.get("kind")

            if kind == "WEED":
                return ["DIG"]

            if kind == "PLANT":
                crop = current_tile.get("crop")
                age = day - current_tile.get("planted_day", 0)
                watered = current_tile.get("watered_today", False)
                yield_units = current_tile.get("yield_units", 0)

                if crop == "MELON":
                    if age >= 10 and yield_units > 0:
                        return ["HARVEST"]
                    elif not watered:
                        return ["WATER"]
                elif crop == "WHEAT":
                    if age >= 2 and yield_units > 0:
                        return ["HARVEST"]
                    elif not watered:
                        return ["WATER"]

        elif current_tile is None:
            # Prefer planting Melon
            if unit_seeds.get("MELON", 0) > 0:
                return ["PLANT", "MELON"]
            if unit_seeds.get("WHEAT", 0) > 0:
                return ["PLANT", "WHEAT"]

        return ["PASS"]

    # -------------------------------------------------
    # 3. Farmer action
    # -------------------------------------------------
    farmer_action = decide_action(tile, seeds)

    # -------------------------------------------------
    # 4. Farm hand action (simple version)
    # -------------------------------------------------
    if hands:
        hx, hy = hands[0]
        hand_tile = get_tile(hx, hy)
        hands_actions[0] = decide_action(hand_tile, seeds)

    # -------------------------------------------------
    # 5. Smarter Movement (for farmer if idle)
    # -------------------------------------------------
    if farmer_action == ["PASS"]:
        best_score = -999
        best_dir = None

        directions = [
            ("EAST", 1, 0),
            ("SOUTH", 0, 1),
            ("WEST", -1, 0),
            ("NORTH", 0, -1),
        ]

        for direction, dx, dy in directions:
            nx, ny = fx + dx, fy + dy
            target = get_tile(nx, ny)

            if target == "LOCKED":
                continue

            score = 0

            if isinstance(target, dict):
                if target.get("kind") == "WEED":
                    score = 60
                elif target.get("kind") == "PLANT":
                    crop = target.get("crop")
                    age = day - target.get("planted_day", 0)
                    if crop == "MELON" and age >= 10 and target.get("yield_units", 0) > 0:
                        score = 50
                    elif crop == "WHEAT" and age >= 2 and target.get("yield_units", 0) > 0:
                        score = 40
                    elif not target.get("watered_today", False):
                        score = 30

            elif target is None:
                if seeds.get("MELON", 0) > 0 or seeds.get("WHEAT", 0) > 0:
                    score = 20

            score += 1  # slight bias to move

            if score > best_score:
                best_score = score
                best_dir = direction

        if best_dir:
            farmer_action = [best_dir]

    # -------------------------------------------------
    # 6. Simple movement for the hand if idle
    # -------------------------------------------------
    if hands and hands_actions[0] == ["PASS"]:
        hx, hy = hands[0]
        for direction, dx, dy in [("EAST",1,0), ("SOUTH",0,1), ("WEST",-1,0), ("NORTH",0,-1)]:
            nx, ny = hx + dx, hy + dy
            if get_tile(nx, ny) != "LOCKED":
                hands_actions[0] = [direction]
                break

    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market
    }



# ======================
# Test the agent
# ======================
if __name__ == "__main__":
    env = make("kaggriculture", debug=True)
    
    # Run against random agent
    env.run([agent, "random"])
    
    # Print final scores
    final = env.steps[-1]
    for i, s in enumerate(final):
        print(f"Player {i}: money = {s.reward}")