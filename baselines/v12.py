from collections import deque

from kaggle_environments import make

# ─── Crop data ──────────────────────────────────────────────────────
CROPS = {
    "WHEAT":      {"seed": 10, "first_yield_day": 2, "max_yield_day": 4,  "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20, "first_yield_day": 2, "max_yield_day": 3,  "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50, "first_yield_day": 8, "max_yield_day": 8,  "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100,"first_yield_day": 10,"max_yield_day": 10, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80, "first_yield_day": 10,"max_yield_day": 12, "max_yield": 6, "ongoing": False},
}

TOTAL_DAYS = 30
MAX_MARKET_ORDERS = 10

def fib(n):
    if n <= 1: return 1
    a, b = 1, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

def agent(obs):
    """
    Kaggriculture Agent v12 — Top 10 Fix
    - Fixed BFS depth and scoring to work on a 10x10 grid (unlocked map).
    - Prevents workers from going blind and wandering aimlessly.
    """
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {})
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)
    step = obs.get("step", 0)
    market_data = obs.get("market", {})
    market_prices = market_data.get("prices", {})

    fx, fy = me["farmer"]
    tiles = me["tiles"]
    height = len(tiles)
    width = len(tiles[0]) if height > 0 else 0
    hands = me.get("hands", [])
    money = me.get("money", 0)
    unlocked = me.get("unlocked_quadrants", ["NW"])

    seeds = private.get("seeds", {})
    shed = private.get("shed", {})

    days_left = TOTAL_DAYS - day

    def get_tile(x, y):
        if 0 <= y < height and 0 <= x < width:
            return tiles[y][x]
        return "LOCKED"

    # ─── Farm scan ───────────────────────────────────────────────────
    empty_count = 0
    plant_count = 0
    weed_count = 0
    total_unlocked = 0

    for yy in range(height):
        for xx in range(width):
            t = tiles[yy][xx]
            if t != "LOCKED":
                total_unlocked += 1
            if t is None:
                empty_count += 1
            elif isinstance(t, dict):
                kind = t.get("kind")
                if kind == "WEED":
                    weed_count += 1
                elif kind == "PLANT":
                    plant_count += 1

    target_workers = max(1, total_unlocked // 8 + 1)
    target_hands = target_workers - 1
    max_plants = target_workers * 8

    # ─── Tile scoring ────────────────────────────────────────────────
    def tile_score(x, y):
        t = get_tile(x, y)
        if t == "LOCKED":
            return -1

        if isinstance(t, dict):
            kind = t.get("kind")
            if kind == "WEED":
                return 150
            if kind == "PLANT":
                crop = t.get("crop")
                cd = CROPS.get(crop, {})
                age = day - t.get("planted_day", 0)
                watered = t.get("watered_today", False)
                yu = t.get("yield_units", 0)
                
                if yu > 0 and age >= cd.get("first_yield_day", 999):
                    return 140
                if not watered:
                    return 120
            return 0

        elif t is None:
            has_seeds = any(seeds.get(c, 0) > 0 for c in CROPS)
            if has_seeds and plant_count < max_plants:
                return 60
            return 0
        return 0

    # ─── BFS movement ────────────────────────────────────────────────
    def bfs_best_move(sx, sy, occupied_set):
        best_score = -1
        best_first_dir = None
        visited = {(sx, sy)}
        queue = deque()
        directions = [
            ("EAST", 1, 0), ("SOUTH", 0, 1),
            ("WEST", -1, 0), ("NORTH", 0, -1),
        ]

        for direction, dx, dy in directions:
            nx, ny = sx + dx, sy + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) not in visited:
                visited.add((nx, ny))
                queue.append((nx, ny, direction, 1))

        while queue:
            cx, cy, first_dir, dist = queue.popleft()
            # Deep search across full map
            if dist > 25:
                continue

            score = tile_score(cx, cy)
            if (cx, cy) in occupied_set:
                score = max(score - 100, 0)

            # Lower distance penalty so distant targets are still attractive
            effective = score - dist * 1.5
            if effective > best_score:
                best_score = effective
                best_first_dir = first_dir

            for _, ddx, ddy in directions:
                nx, ny = cx + ddx, cy + ddy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                if (nx, ny) in visited:
                    continue
                visited.add((nx, ny))
                queue.append((nx, ny, first_dir, dist + 1))

        if best_first_dir and best_score > 0:
            return [best_first_dir]

        # If completely idle (no targets), move randomly to avoid getting stuck in loops
        import random
        valid = []
        for direction, dx, dy in directions:
            nx, ny = sx + dx, sy + dy
            if 0 <= nx < width and 0 <= ny < height and get_tile(nx, ny) != "LOCKED":
                valid.append(direction)
        if valid:
            return [random.choice(valid)]
        return ["PASS"]

    # ─── Tile action ─────────────────────────────────────────────────
    def decide_tile_action(current_tile, unit_seeds):
        if isinstance(current_tile, dict):
            kind = current_tile.get("kind")
            if kind == "WEED":
                return ["DIG"]
            if kind == "PLANT":
                crop = current_tile.get("crop")
                cd = CROPS.get(crop, {})
                age = day - current_tile.get("planted_day", 0)
                watered = current_tile.get("watered_today", False)
                yu = current_tile.get("yield_units", 0)

                if yu > 0 and age >= cd.get("first_yield_day", 999):
                    if not cd.get("ongoing", False):
                        max_yd = cd.get("max_yield_day", 0)
                        if age >= max_yd or yu >= cd.get("max_yield", 1) or days_left <= 3:
                            return ["HARVEST"]
                        if crop == "WHEAT" and yu >= 1:
                            return ["HARVEST"]
                        if crop == "CARROT" and yu >= 2:
                            return ["HARVEST"]
                    else:
                        if yu >= 2 or days_left <= 3:
                            return ["HARVEST"]

                if not watered:
                    return ["WATER"]

        elif current_tile is None:
            if plant_count >= max_plants and days_left > 3:
                return ["PASS"]

            if days_left <= 5:
                if unit_seeds.get("WHEAT", 0) > 0:
                    return ["PLANT", "WHEAT"]
                if unit_seeds.get("CARROT", 0) > 0:
                    return ["PLANT", "CARROT"]
            elif days_left <= 10:
                if unit_seeds.get("CARROT", 0) > 0:
                    return ["PLANT", "CARROT"]
                if unit_seeds.get("WHEAT", 0) > 0:
                    return ["PLANT", "WHEAT"]
            else:
                if days_left > 14 and unit_seeds.get("MELON", 0) > 0:
                    unit_seeds["MELON"] -= 1
                    return ["PLANT", "MELON"]
                if unit_seeds.get("CARROT", 0) > 0:
                    unit_seeds["CARROT"] -= 1
                    return ["PLANT", "CARROT"]
                if unit_seeds.get("WHEAT", 0) > 0:
                    unit_seeds["WHEAT"] -= 1
                    return ["PLANT", "WHEAT"]

        return ["PASS"]

    # ═══════════════════════════════════════════════════════════════════
    # MARKET ORDERS
    # ═══════════════════════════════════════════════════════════════════
    market = []

    hires_today = me.get("hires_today", 0)
    hands_wanted = target_hands - hires_today
    cost_accumulator = 0
    for i in range(hands_wanted):
        if len(market) >= MAX_MARKET_ORDERS:
            break
        cost = fib(hires_today + i)
        if money >= cost_accumulator + cost + 10:
            cost_accumulator += cost
            market.append(["HIRE"])
        else:
            break

    if days_left <= 2:
        for item in ["MELON", "STRAWBERRY", "TOMATO", "CARROT", "WHEAT", "EGG", "MILK", "WOOL", "FERTILIZER"]:
            qty = shed.get(item, 0)
            if qty > 0:
                market.append(["SELL", item, qty])
    else:
        melon_qty = shed.get("MELON", 0)
        if melon_qty > 0:
            melon_price = market_prices.get("MELON", 250)
            sell_amt = 0
            if melon_price >= 220:
                sell_amt = min(melon_qty, 6)
            elif melon_price >= 180:
                sell_amt = min(melon_qty, 4)
            elif melon_price >= 120:
                sell_amt = min(melon_qty, 2)
            
            if sell_amt > 0:
                market.append(["SELL", "MELON", sell_amt])

        for item, max_sell in [("STRAWBERRY", 6), ("TOMATO", 6), ("CARROT", 15), ("WHEAT", 20)]:
            qty = shed.get(item, 0)
            if qty > 0 and len(market) < MAX_MARKET_ORDERS:
                market.append(["SELL", item, min(qty, max_sell)])

    n_extra = len(unlocked) - 1
    if n_extra == 0 and money >= 3000 and day >= 8 and len(market) < MAX_MARKET_ORDERS:
        market.append(["BUY_LAND"])
    elif n_extra == 1 and money >= 6000 and day >= 12 and len(market) < MAX_MARKET_ORDERS:
        market.append(["BUY_LAND"])
    elif n_extra == 2 and money >= 12000 and day >= 16 and len(market) < MAX_MARKET_ORDERS:
        market.append(["BUY_LAND"])
    # Calculate seeds
    total_seeds = sum(seeds.get(c, 0) for c in CROPS)
    headroom = max(0, max_plants - plant_count)
    seeds_wanted = max(0, min(headroom, empty_count) - total_seeds)

    if len(market) < MAX_MARKET_ORDERS and seeds_wanted > 0 and money >= 30:
        if days_left > 14 and money >= 300:
            n = min(seeds_wanted, 8, max(0, int((money - 150) / 80)))
            if n > 0:
                market.append(["BUY_SEED", "MELON", n])
                seeds_wanted -= n

        if seeds_wanted > 0 and days_left > 5 and money >= 50:
            n = min(seeds_wanted, 5, max(0, int((money - 30) / 20)))
            if n > 0 and len(market) < MAX_MARKET_ORDERS:
                market.append(["BUY_SEED", "CARROT", n])
                seeds_wanted -= n

        if seeds_wanted > 0 and money >= 20:
            n = min(seeds_wanted, 5, max(0, int((money - 10) / 10)))
            if n > 0 and len(market) < MAX_MARKET_ORDERS:
                market.append(["BUY_SEED", "WHEAT", n])

    market = market[:MAX_MARKET_ORDERS]

    # ═══════════════════════════════════════════════════════════════════
    # UNIT ACTIONS
    # ═══════════════════════════════════════════════════════════════════
    all_positions = [(fx, fy)]
    for h in hands:
        all_positions.append((h[0], h[1]))

    farmer_tile = get_tile(fx, fy)
    farmer_action = decide_tile_action(farmer_tile, seeds)
    if farmer_action == ["PASS"]:
        occupied = set((p[0], p[1]) for p in all_positions[1:])
        farmer_action = bfs_best_move(fx, fy, occupied)

    hands_actions = []
    for h_idx, hand_pos in enumerate(hands):
        hx, hy = hand_pos[0], hand_pos[1]
        hand_tile = get_tile(hx, hy)
        hand_action = decide_tile_action(hand_tile, seeds)
        if hand_action == ["PASS"]:
            occupied = {(fx, fy)}
            for j, other in enumerate(hands):
                if j != h_idx:
                    occupied.add((other[0], other[1]))
            hand_action = bfs_best_move(hx, hy, occupied)
        hands_actions.append(hand_action)

    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market,
    }

# ═══════════════════════════════════════════════════════════════════════
if False:
    scores = []
    n_runs = 15
    print(f"Running {n_runs} games against 'random' opponent...\n")

    for i in range(n_runs):
        env = make("kaggriculture", debug=True)
        env.run([agent, "random"])
        final = env.steps[-1]
        p0 = final[0].reward
        p1 = final[1].reward
        scores.append(p0)
        print(f"  Game {i+1:2d}: Player 0 = ${p0:,.0f}  |  Player 1 = ${p1:,.0f}")

    avg = sum(scores) / len(scores)
    best = max(scores)
    worst = min(scores)
    median = sorted(scores)[len(scores)//2]
    print(f"\n{'='*50}")
    print(f"  Average: ${avg:,.0f}")
    print(f"  Median:  ${median:,.0f}")
    print(f"  Best:    ${best:,.0f}")
    print(f"  Worst:   ${worst:,.0f}")
    print(f"{'='*50}")