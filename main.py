"""Kaggriculture agent.

Design notes, derived from reading the engine source rather than inferring
behaviour from games:

* The board has no impassable tiles -- LOCKED quadrants are walkable, they just
  reject tile ops. Manhattan distance is therefore exact, and BFS is pointless.
* Watering only adds yield inside a per-crop window. Outside it, watering every
  other day keeps the plant alive (two consecutive dry end-of-days kill it).
  Skipping the redundant waterings frees a large share of every unit's day.
* Hire cost is fib(n) with mult 1 and resets daily, so labour is nearly free.
  Land is the binding constraint, so tile-days are what we optimise.
* WHEAT and EGG decay their price logarithmically and never really saturate.
  Everything else is polynomial and caps out -- MELON hardest of all, and it is
  in no shop's demand list, so only the town centre's 1/day drains it.
* The shed holds 100 items and end-of-day overflow is discarded silently.

Kaggle's loader (`agent.py: get_last_callable`) runs the LAST callable defined
in this file, not the one named `agent`. Nothing may be defined below `agent`.
"""

import math
import os

TOTAL_DAYS = 30
TURNS_PER_DAY = 24
SHED_CAP = 100
MAX_MARKET_ORDERS = 10

CROPS = {
    "WHEAT":      {"seed": 10,  "first_yield_day": 2,  "max_yield_day": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first_yield_day": 2,  "max_yield_day": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first_yield_day": 8,  "max_yield_day": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

MARKET_I0 = 10000
PRICE_FLOOR = 1
MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "T": 400, "below_func": "sqrt",   "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base":  35, "T": 450, "below_func": "log",    "below_target": 0.20, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base":  60, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "below_func": "sqrt",   "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "T": 300, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base":  50, "T": 332, "below_func": "linear", "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "T": 122, "below_func": "sqrt",   "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "T": 105, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
SHOP_TICKS_PER_DAY = 6   # townShopSellInterval 4, over 24 turns
SHOP_UNLOCK_DAYS = 3     # townShopUnlockInterval
MAX_SHOP_INSTANCES = 8

# Expected consumption of an item per shop instance per tick, given shops are
# drawn uniformly with replacement from SHOPS (single-product shops pull 2x).
EXPECTED_PULL = {}
for _item in MARKET_PARAMS:
    _total = 0.0
    for _products in SHOPS.values():
        if _item in _products:
            _total += 2.0 if len(_products) == 1 else 1.0
    EXPECTED_PULL[_item] = _total / len(SHOPS)

LAND_PRICES = [1000, 2000, 4000]
LAND_MIN_DAYS = [5, 6, 8]
SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]

# ── Tunables (overridable as KAG_<NAME> for sweeps; see tune.py) ───────────
def _tune(name, default):
    raw = os.environ.get("KAG_" + name)
    return type(default)(raw) if raw is not None else default


MOVE_COST = _tune("MOVE_COST", 7.0)          # dollar cost of one step walked
MAX_UNITS = _tune("MAX_UNITS", 12)           # farmer + hands; fib payroll bites hard past this
TILES_PER_UNIT = _tune("TILES_PER_UNIT", 6.0)
PLANTS_PER_UNIT = _tune("PLANTS_PER_UNIT", 11)  # tiles one unit can tend per day
LAND_BUFFER = _tune("LAND_BUFFER", 800)      # stay this liquid after buying land
RESERVE_FRAC = _tune("RESERVE_FRAC", 0.45)   # hold while price < this x base
SEED_RATION = _tune("SEED_RATION", 6)        # per-turn cap on slow, pricey seeds
HIRE_FLOOR = _tune("HIRE_FLOOR", 20)         # hands drive everything: never skip
CASH_FLOOR = _tune("CASH_FLOOR", 150)

DEBUG = bool(os.environ.get("KAG_DEBUG"))


def _shape(func, x):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    return x


def market_price(item, inventory):
    """Exact port of the engine's price curve."""
    p = MARKET_PARAMS[item]
    base, T = p["base"], p["T"]
    if inventory < MARKET_I0:
        f = p["below_func"]
        amp = p["below_target"] * base / _shape(f, T)
        price = base + amp * _shape(f, MARKET_I0 - inventory)
    else:
        f = p["above_func"]
        amp = p["above_target"] * base / _shape(f, T)
        price = base - amp * _shape(f, inventory - MARKET_I0)
    return max(PRICE_FLOOR, int(round(price)))


def fib_hire_cost(n_already_today):
    a, b = 1, 1
    for _ in range(n_already_today):
        a, b = b, a + b
    return a


def _build_crop_plans():
    """Per crop: the age to harvest at, and the yield reachable by then.

    Non-ongoing crops start at 1 unit and gain 1 per watering inside
    [ceil(max_yield_day/2), max_yield_day], capped at max_yield.
    Ongoing crops accrue 1 unit per `interval` days from first_yield_day and
    are scheduled to die one day after their final production.
    """
    plans = {}
    for crop, cd in CROPS.items():
        if cd["ongoing"]:
            target_age = cd["first_yield_day"] + cd["interval"] * (cd["max_yield"] - 1)
            units = cd["max_yield"]
            window_start = 10 ** 9  # watering never adds yield without fertilizer
        else:
            window_start = (cd["max_yield_day"] + 1) // 2
            units = min(cd["max_yield"], 1 + (cd["max_yield_day"] - window_start + 1))
            target_age = cd["first_yield_day"]
            while target_age < cd["max_yield_day"]:
                if min(cd["max_yield"], 1 + max(0, target_age - window_start + 1)) >= units:
                    break
                target_age += 1
        plans[crop] = {
            "window_start": window_start,
            "target_age": target_age,
            "units": units,
            # Harvest frees the tile the same day, so a cycle is target_age days.
            "cycle": max(1, target_age),
        }
    return plans


CROP_PLANS = _build_crop_plans()


def daily_town_demand(shops, day=0, horizon=0):
    """Units of each product the town pulls out of market inventory per day.

    Averaged over the next `horizon` days, because shops keep unlocking (one
    every SHOP_UNLOCK_DAYS, capped at MAX_SHOP_INSTANCES) and future demand is
    what matters when deciding what to put in the ground today.
    """
    demand = {item: 1.0 for item in MARKET_PARAMS if item != "FERTILIZER"}
    known = 0.0
    for shop in shops:
        products = SHOPS.get(shop)
        if not products:
            continue
        known += 1
        mult = 2 if len(products) == 1 else 1
        for item in products:
            demand[item] = demand.get(item, 0.0) + SHOP_TICKS_PER_DAY * mult

    if horizon > 0:
        span = range(day, day + horizon + 1)
        avg_instances = sum(min(MAX_SHOP_INSTANCES, d // SHOP_UNLOCK_DAYS) for d in span) / len(span)
        unknown = max(0.0, avg_instances - known)
        if unknown:
            for item in demand:
                demand[item] += SHOP_TICKS_PER_DAY * unknown * EXPECTED_PULL.get(item, 0.0)
    return demand


def batch_revenue(item, start_inv, count):
    """Revenue from selling `count` units starting at market inventory `start_inv`."""
    total = 0
    inv = start_inv
    for _ in range(count):
        p = market_price(item, inv)
        total += p
        if p > PRICE_FLOOR:  # sales at the floor do not add supply
            inv += 1
    return total


def sellable_count(item, start_inv, have, reserve):
    """Units to sell now before the marginal price falls under `reserve`."""
    n = 0
    inv = start_inv
    while n < have:
        p = market_price(item, inv)
        if p < reserve:
            break
        n += 1
        if p > PRICE_FLOOR:
            inv += 1
    return n


def nearest_shed_tile(x, y):
    return min(SHED_TILES, key=lambda t: abs(t[0] - x) + abs(t[1] - y))


def step_toward(x, y, tx, ty):
    dx, dy = tx - x, ty - y
    if abs(dx) >= abs(dy):
        return "EAST" if dx > 0 else "WEST"
    return "SOUTH" if dy > 0 else "NORTH"


def _decide(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {}) or {}
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)
    market = obs.get("market", {}) or {}
    minv = dict(market.get("inventory", {}))
    town = obs.get("town", {}) or {}

    tiles = me["tiles"]
    size = len(tiles)
    money = me.get("money", 0)
    hands = me.get("hands", [])
    unlocked = me.get("unlocked_quadrants", ["NW"])
    hires_today = me.get("hires_today", 0)

    seeds = dict(private.get("seeds", {}) or {})
    shed = dict(private.get("shed", {}) or {})
    inventories = private.get("inventories", []) or [{}]

    # The season stops mid-day 29, so day 29 never gets an end-of-day drop:
    # anything still in a unit's hands then is worth nothing.
    days_left = (TOTAL_DAYS - 1) - day
    last_day = days_left <= 0
    now_step = day * TURNS_PER_DAY + hour

    # ── Farm scan ──────────────────────────────────────────────────────────
    empties = []
    weeds = []
    plants = []
    unlocked_tiles = 0
    pipeline = {}  # crop -> units still to come, ours, not yet sold

    for y in range(size):
        row = tiles[y]
        for x in range(size):
            t = row[x]
            if t == "LOCKED":
                continue
            unlocked_tiles += 1
            if t is None:
                empties.append((x, y))
            elif isinstance(t, dict):
                kind = t.get("kind")
                if kind == "WEED":
                    weeds.append((x, y))
                elif kind == "PLANT":
                    crop = t.get("crop")
                    if crop not in CROPS:
                        continue
                    age = day - t.get("planted_day", 0)
                    plants.append((x, y, t, crop, age))
                    pipeline[crop] = pipeline.get(crop, 0) + max(
                        t.get("yield_units", 0), CROP_PLANS[crop]["units"]
                    )

    for item, qty in shed.items():
        if item in CROPS and qty > 0:
            pipeline[item] = pipeline.get(item, 0) + qty
    for inv in inventories:
        for item, qty in inv.items():
            if item in CROPS and qty > 0:
                pipeline[item] = pipeline.get(item, 0) + qty

    shops = town.get("unlocked_shops", [])
    demand_cache = {}

    def demand_over(horizon):
        d = demand_cache.get(horizon)
        if d is None:
            d = daily_town_demand(shops, day, horizon)
            demand_cache[horizon] = d
        return d

    # ── Crop valuation ─────────────────────────────────────────────────────
    # Price a planting at the inventory we expect to face when it comes out of
    # the ground: today's inventory, minus everything the town will consume in
    # the meantime, plus our own unsold pipeline. The town's drawdown is what
    # creates the scarcity premiums (strawberry, tomato) worth chasing, and the
    # pipeline term is what stops us flooding any one market.
    profit_cache = {}

    def crop_profit(crop):
        """Total dollars a fresh planting of `crop` should clear over its cycle."""
        cached = profit_cache.get(crop)
        if cached is not None:
            return cached
        plan = CROP_PLANS[crop]
        cycle = plan["cycle"]
        if cycle > days_left:
            profit_cache[crop] = -1.0
            return -1.0
        drawdown = demand_over(cycle).get(crop, 1.0) * cycle
        start = minv.get(crop, MARKET_I0) - drawdown + pipeline.get(crop, 0)
        profit = batch_revenue(crop, start, plan["units"]) - CROPS[crop]["seed"]
        profit_cache[crop] = profit
        return profit

    def crop_value(crop):
        """Profit per tile-day -- what a tile is worth, for costing jobs."""
        p = crop_profit(crop)
        return p / CROP_PLANS[crop]["cycle"] if p > 0 else p

    # Ranking has to price BOTH scarce resources, and which one binds flips
    # during the game. On day 0 land is free and cash is the constraint, so a
    # $100 strawberry seed is a trap; by day 15 cash is ample and every tile-day
    # counts. Charging seed cost against cash-per-free-tile interpolates between
    # "maximise return on capital" and "maximise return on land" automatically.
    cash_per_tile = max(1.0, (money - CASH_FLOOR)) / max(1, len(empties))

    def crop_score(crop):
        p = crop_profit(crop)
        if p <= 0:
            return p
        cycle = CROP_PLANS[crop]["cycle"]
        return p / (cycle * (1.0 + CROPS[crop]["seed"] / cash_per_tile))

    crop_ranking = sorted(CROPS, key=crop_score, reverse=True)
    best_crop = max(CROPS, key=crop_value)
    best_value = crop_value(best_crop)
    # What one freed tile is worth: a full cycle of the best crop we could put on it.
    tile_unlock_value = max(0.0, best_value) * CROP_PLANS[best_crop]["cycle"]

    def price_of(item):
        return market_price(item, minv.get(item, MARKET_I0))

    # ── Job list: (value in dollars, x, y, action) ─────────────────────────
    jobs = []

    for (x, y, t, crop, age) in plants:
        plan = CROP_PLANS[crop]
        cd = CROPS[crop]
        yu = t.get("yield_units", 0)
        watered = t.get("watered_today", False)
        unwatered = t.get("consecutive_unwatered", 0)
        lifespan = t.get("max_lifespan_step", -1)
        decaying = 0 <= lifespan <= now_step
        mature = age >= cd["first_yield_day"] and yu > 0

        # Harvest once the plant has all the yield it is going to get. Note we
        # deliberately do NOT harvest merely because age hit target_age: the
        # final in-window watering happens on that same day and is worth a unit.
        if mature and (yu >= plan["units"] or decaying or last_day
                       or (not cd["ongoing"] and age > cd["max_yield_day"])):
            jobs.append((yu * price_of(crop) + tile_unlock_value * 0.5, x, y, ["HARVEST"]))
            continue

        # An ongoing crop that has given up its last harvest is now just a
        # future weed sitting on a tile we want back.
        if cd["ongoing"] and age >= plan["target_age"] and yu <= 0:
            jobs.append((tile_unlock_value * 0.8, x, y, ["DIG"]))
            continue

        if watered:
            continue

        reachable = (plan["target_age"] - age) <= days_left
        gain = 0.0
        # Yield bonus, only inside the window and only while it can absorb more.
        if (not cd["ongoing"] and plan["window_start"] <= age <= cd["max_yield_day"]
                and yu < cd["max_yield"]):
            gain = float(price_of(crop))
        # Survival: a second consecutive dry end-of-day turns this into a weed.
        # Pointless on the last day, since that end-of-day never arrives.
        if unwatered >= 1 and not last_day and reachable:
            remaining = max(0, plan["units"] - yu)
            gain = max(gain, remaining * price_of(crop) * 0.9 + tile_unlock_value * 0.2)
        if gain > 0:
            jobs.append((gain, x, y, ["WATER"]))

    for (x, y) in weeds:
        if not last_day:
            jobs.append((tile_unlock_value * 0.8, x, y, ["DIG"]))

    # Never take on more plants than the crew can keep watered -- an unwatered
    # plant is not just wasted seed, it becomes a weed that costs a DIG too.
    crew = max(1, len(hands) + 1)
    care_capacity = max(0, crew * PLANTS_PER_UNIT - len(plants))

    plant_budget = 0
    if not last_day and best_value > 0:
        usable_seeds = sum(seeds.get(c, 0) for c in CROPS if crop_profit(c) > 0)
        plant_budget = min(len(empties), usable_seeds, care_capacity)
        plant_job_value = max(best_value * CROP_PLANS[best_crop]["cycle"], 1.0)
        for (x, y) in empties:
            jobs.append((plant_job_value, x, y, ["PLANT"]))

    # On the last day nothing auto-drops, so carried goods must be walked in.
    if last_day:
        for idx in range(1 + len(hands)):
            inv = inventories[idx] if idx < len(inventories) else {}
            worth = sum(market_price(i, minv.get(i, MARKET_I0)) * q
                        for i, q in inv.items() if i in MARKET_PARAMS and q > 0)
            if worth <= 0:
                continue
            x, y = (me["farmer"] if idx == 0 else hands[idx - 1])[:2]
            tx, ty = nearest_shed_tile(x, y)
            if hour + abs(tx - x) + abs(ty - y) < TURNS_PER_DAY - 2:
                jobs.append((worth + 1e6, tx, ty, ["DROP", idx]))

    # ── Assignment: highest-value job takes the nearest idle unit ──────────
    positions = [tuple(me["farmer"][:2])] + [tuple(h[:2]) for h in hands]
    n_units = len(positions)
    assigned = [None] * n_units
    free = set(range(n_units))

    # DROP jobs are pinned to the one unit whose hands are full.
    for value, jx, jy, action in jobs:
        if action[0] != "DROP":
            continue
        idx = action[1]
        if idx in free:
            assigned[idx] = (jx, jy, ["DROP"])
            free.discard(idx)

    # Rank every (unit, job) pair by value per action spent reaching it, so a
    # unit prefers a decent job at its feet over a great one across the farm.
    pairs = []
    for j, (value, jx, jy, action) in enumerate(jobs):
        if action[0] == "DROP":
            continue
        for idx in range(n_units):
            px, py = positions[idx]
            dist = abs(jx - px) + abs(jy - py)
            if value - dist * MOVE_COST <= 0:
                continue
            pairs.append((value / (dist + 1.0), idx, j))
    pairs.sort(key=lambda p: -p[0])

    claimed = set()
    for _, idx, j in pairs:
        if idx not in free:
            continue
        value, jx, jy, action = jobs[j]
        if (jx, jy) in claimed:
            continue
        if action[0] == "PLANT":
            if plant_budget <= 0:
                continue
            plant_budget -= 1
        assigned[idx] = (jx, jy, action)
        free.discard(idx)
        claimed.add((jx, jy))
        if not free:
            break

    seeds_left = dict(seeds)
    unit_actions = []
    for idx in range(n_units):
        job = assigned[idx]
        if job is None:
            unit_actions.append(["PASS"])
            continue
        jx, jy, action = job
        px, py = positions[idx]
        if (px, py) != (jx, jy):
            unit_actions.append([step_toward(px, py, jx, jy)])
            continue
        if action[0] == "PLANT":
            # Pick the crop at execution time and decrement, so we never queue
            # more PLANTs of a crop than we hold seeds -- the engine drops all
            # of them if we overcommit.
            crop = next((c for c in crop_ranking
                         if seeds_left.get(c, 0) > 0 and crop_profit(c) > 0), None)
            if crop is None:
                unit_actions.append(["PASS"])
                continue
            seeds_left[crop] -= 1
            unit_actions.append(["PLANT", crop])
        else:
            unit_actions.append(list(action))

    # ── Market orders ──────────────────────────────────────────────────────
    # Orders resolve in list order, so selling first funds everything after it.
    incoming = sum(sum(v for v in inv.values() if v > 0) for inv in inventories)
    shed_fill = sum(v for v in shed.values() if v > 0)

    reserve_frac = RESERVE_FRAC
    if days_left <= 1:
        reserve_frac = 0.0
    elif days_left <= 4:
        reserve_frac = 0.15
    if shed_fill + incoming > SHED_CAP - 10:
        reserve_frac = min(reserve_frac, 0.05)  # overflow is discarded, so dump
    elif shed_fill > SHED_CAP * 0.7:
        reserve_frac *= 0.4

    sell_orders = []
    sell_inv = dict(minv)
    proceeds = 0
    candidates = sorted(((i, q) for i, q in shed.items() if q > 0 and i in MARKET_PARAMS),
                        key=lambda kv: -market_price(kv[0], sell_inv.get(kv[0], MARKET_I0)))
    for item, qty in candidates:
        reserve = reserve_frac * MARKET_PARAMS[item]["base"]
        n = sellable_count(item, sell_inv.get(item, MARKET_I0), qty, reserve)
        if n > 0:
            proceeds += batch_revenue(item, sell_inv.get(item, MARKET_I0), n)
            sell_inv[item] = sell_inv.get(item, MARKET_I0) + n
            sell_orders.append(["SELL", item, n])

    cash = money + proceeds

    land_orders = []
    projected_tiles = unlocked_tiles
    n_extra = len(unlocked) - 1
    if n_extra < len(LAND_PRICES):
        price = LAND_PRICES[n_extra]
        if days_left >= LAND_MIN_DAYS[n_extra] and cash >= price + LAND_BUFFER:
            land_orders.append(["BUY_LAND"])
            cash -= price
            projected_tiles += (size * size) // 4

    # Size the crew against the land we will own after this turn's purchase.
    target_units = max(2, min(MAX_UNITS, int(projected_tiles / TILES_PER_UNIT) + 1))

    hire_orders = []
    if hour <= 3 and not last_day:
        for i in range(max(0, target_units - n_units)):
            cost = fib_hire_cost(hires_today + i)
            if cash - cost < HIRE_FLOOR:
                break
            cash -= cost
            hire_orders.append(["HIRE"])

    seed_orders = []
    if not last_day:
        held = sum(seeds.values())
        # Tiles today's harvests will free are plantable again today.
        freeing = sum(1 for (_, _, t, crop, age) in plants
                      if not CROPS[crop]["ongoing"]
                      and t.get("yield_units", 0) >= CROP_PLANS[crop]["units"])
        # Only seed what the crew we are hiring can actually look after.
        room = max(0, target_units * PLANTS_PER_UNIT - len(plants))
        need = min(len(empties) + freeing, room) - held
        # Keep tomorrow's payroll liquid: an unstaffed farm turns into weeds.
        payroll = sum(fib_hire_cost(i) for i in range(max(0, target_units - 1)))
        budget = cash - CASH_FLOOR - payroll
        for crop in crop_ranking:
            if need <= 0 or budget <= 0:
                break
            if crop_profit(crop) <= 0:
                continue
            cost = CROPS[crop]["seed"]
            n = min(need, int(budget // cost))
            if crop in ("MELON", "STRAWBERRY", "TOMATO"):
                n = min(n, SEED_RATION)  # don't sink the whole purse into one slow crop
            if n > 0:
                seed_orders.append(["BUY_SEED", crop, n])
                budget -= n * cost
                need -= n

    # Fit into the per-turn order cap, trimming sells first: they are the most
    # divisible and the cheapest to defer by one turn.
    fixed = land_orders + hire_orders + seed_orders
    room = max(0, MAX_MARKET_ORDERS - len(fixed))
    orders = sell_orders[:room] + fixed
    if len(orders) > MAX_MARKET_ORDERS:
        orders = sell_orders[:1] + fixed[:MAX_MARKET_ORDERS - 1]

    return {
        "farmer": unit_actions[0] if unit_actions else ["PASS"],
        "hands": unit_actions[1:],
        "market": orders[:MAX_MARKET_ORDERS],
    }


def agent(obs):
    if DEBUG:
        return _decide(obs)
    try:
        return _decide(obs)
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}
