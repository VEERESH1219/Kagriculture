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

# Phase 8 re-derivation (2026-08-12): the original note here ("only GOOSE is
# worth the tiles") judged animals on lifetime market cap -- EGG never
# saturates, MILK/WOOL do around $6-8k. But action cost is the binding
# constraint, not tile count (actions.py: MOVE+PASS is most of the crew's
# day), and on $-per-action COW and SHEEP win: they harvest every 2-3 days
# instead of daily for roughly double the goose's $26/action at ~$49-50.
# All three eat WHEAT, per the engine's FEED handler (it doesn't check
# animal type). COOP holds only GOOSE; PASTURE holds either COW or SHEEP.
ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP", "first_yield_day": 4,
              "interval": 1, "max_held": 4, "product": "EGG", "feed": "WHEAT"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8,
              "interval": 2, "max_held": 6, "product": "MILK", "feed": "WHEAT"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6,
              "interval": 3, "max_held": 6, "product": "WOOL", "feed": "WHEAT"},
}
# `_end_of_day` runs on `(step + 1) % turns_per_day == 0`, and the season stops
# mid-day 29, so the last end-of-day -- the last time an animal produces -- is
# the end of day 28. Fertilizer, though, is re-flagged every end-of-day from the
# day the animal is placed, so it is collectable one day later than the last egg.
LAST_EOD_DAY = TOTAL_DAYS - 2
# Base production is 1, and CARE on a fed day banks a +1 bonus that the next fed
# production day spends -- so a goose kept fed and cared for lays 2/day.
EGGS_PER_YIELD = 2

# ── Tunables (overridable as KAG_<NAME> for sweeps; see tune.py) ───────────
def _tune(name, default):
    raw = os.environ.get("KAG_" + name)
    return type(default)(raw) if raw is not None else default


MOVE_COST = _tune("MOVE_COST", 7.0)          # dollar cost of one step walked
MAX_UNITS = _tune("MAX_UNITS", 12)           # farmer + hands; fib payroll bites hard past this
TILES_PER_UNIT = _tune("TILES_PER_UNIT", 6.0)
PLANTS_PER_UNIT = _tune("PLANTS_PER_UNIT", 11)  # tiles one unit can tend per day
LAND_BUFFER = _tune("LAND_BUFFER", 800)      # stay this liquid after buying land
# Only index 0 is live once MAX_LAND_BUYS=1 caps purchases at the first
# extra quadrant -- indices 1-2 are dead weight now, kept for when/if
# MAX_LAND_BUYS goes back up. Tunable so it can be re-swept on its own.
LAND_MIN_DAYS[0] = _tune("LAND_MIN_DAYS0", LAND_MIN_DAYS[0])
# How many of the 3 purchasable quadrants (NE, SW, SE) to actually buy.
# Prompted by top leaderboard replays (episode 92267113, two ~$85k finishes):
# both winners stop at 2 extra quadrants (NW+NE+SW) and leave 56-57 of ~75
# unlocked tiles empty all game -- an animal-dominant economy barely needs
# the land, and land_reserve blocking spare_cash for a quadrant it will
# barely use starves the flock of cash for the back half of the season.
# Measured here, though, 1 beats 2: land_reserve is a *sequential, total*
# hold (the whole next price + buffer, every turn, until bought), so even
# the 2nd purchase's reserve window chokes early flock investment harder
# than the tiles it eventually buys are worth. 3 (buy all of them) is the
# old land-hungry default; replicated sweeps (98% winrate, +$13.3k mean
# margin over 128 games vs a frozen prior build) put the optimum at 1.
MAX_LAND_BUYS = _tune("MAX_LAND_BUYS", 1)
# Fraction of the next land purchase's reserve to actually hold back from the
# flock. Tried loosening this (0.3-0.5) specifically to see if it would let
# MAX_LAND_BUYS go back up to 2-3 (matching top-leaderboard land use) without
# re-starving the flock -- it didn't: still a loss vs the MAX_LAND_BUYS=1
# build at every fraction tried. At MAX_LAND_BUYS=1 the reserve isn't even
# the binding constraint (MAX_ANIMALS is), so this had no effect there
# either -- exact ties both times. 1.0 = the original full-reserve
# behaviour; left in for whoever revisits MAX_LAND_BUYS>=2 next.
LAND_RESERVE_FRAC = _tune("LAND_RESERVE_FRAC", 1.0)
RESERVE_FRAC = _tune("RESERVE_FRAC", 0.45)   # hold while price < this x base
SEED_RATION = _tune("SEED_RATION", 6)        # per-turn cap on slow, pricey seeds
# Assignment hysteresis: multiplies a (unit, job) pair's score when that unit
# was already walking to that exact job last turn AND is within STICKY_RANGE
# steps of it. Tried and parked OFF: measured a replicated loss on three
# independent 16-24 game seed sets against a frozen HEAD opponent, roughly
# -$7k to -$12k at STICKY=1.0, both ungated and range-gated to 2 steps.
# Action-count profiling (actions.py) showed almost no change in MOVE/PASS
# share, so the loss isn't from more walking -- pinning a unit to a job with
# decaying relative value evidently costs more in missed better options than
# it saves in avoided switching. 0.0 keeps the original greedy-every-turn
# behaviour exactly (multiplier 1x, no-op).
STICKY = _tune("STICKY", 0.0)
STICKY_RANGE = _tune("STICKY_RANGE", 2)      # steps-from-target within which STICKY applies
# Quadrant zoning: each unit gets a "home" quadrant (a stateless function of its
# index and the unlocked-quadrant list, so it needs no memory and survives the
# daily hand respawn cleanly). Jobs in a unit's home quadrant get a score
# multiplier, so the crew spreads out across the farm instead of converging on
# whichever single job currently scores highest.
#
# Swept 0.1 -> 5.0 against a frozen HEAD opponent, replicated on 3 independent
# seed sets (n=24 to 64, --swap). Plateaus from ~2.0: 81-86% winrate, +$5-6k
# mean margin. 2.0 is the chosen default, in the middle of the plateau rather
# than at an edge.
QUAD_BONUS = _tune("QUAD_BONUS", 2.0)
# We can see our own unsold pipeline but not the opponent's. This scales ours to
# stand in for theirs when pricing what a harvest will clear against: 0 prices a
# solo market (the behaviour before 2026-08-11), 1 assumes a symmetric opponent
# farming the same crops for the same reasons.
#
# Swept 0 -> 3 over two independent 64-game seed sets, played against a frozen
# copy of the 0 agent. 1.0 is the best value in BOTH runs (+$6.1k / +$8.9k
# margin, 99/128 games won) and it is also the a-priori right answer against a
# mirror, which is why it beat the tuned-looking values. Do not read a winner
# off one sweep: 0.25 led run 1 at 81% and went negative on fresh seeds.
# Past 2.0 it falls off a cliff -- at 3.0 every crop prices as doomed, the agent
# stops planting, and it loses 0/128.
#
# This is a trade, not a free win. Against a weak supplier the symmetric
# assumption over-corrects: v12 costs $4.8k (still 100% winrate). Flat vs pass.
#
# Re-swept with `poolsweep.py` against the calibrated varied pool (the sweep
# above used a frozen copy of ourselves, which the project has since shown
# does not predict the leaderboard -- see PROJECT_STATUS.md, Phase 13/14).
# 0.5 over 5 independent seed sets, 180-216 games per point:
#
#   seed0     1000    5000   12000   21000   33000     mean
#   winrate  +13.0   +6.1    -2.2    +1.9    +2.4     +4.2pp
#   margin    -669  -1,336  -2,806     +17  -2,379   -$1,435
#
# The two metrics disagree: 0.5 wins 4/5 on winrate and loses 4/5 on margin.
# Calibration rates both as equally good leaderboard predictors (Spearman
# +0.900 each), so this is a genuine split, not one metric being wrong.
# Shipped on winrate, because the public score is a win/loss skill rating
# rather than a dollar total. Expect parity, not a visible jump: +4.2pp of
# pool winrate is well inside the ~20-point leaderboard noise floor measured
# in Phase 13 (two byte-identical builds scored 708.4 and 728.1).
OPP_SUPPLY = _tune("OPP_SUPPLY", 0.5)
HIRE_FLOOR = _tune("HIRE_FLOOR", 20)         # hands drive everything: never skip
CASH_FLOOR = _tune("CASH_FLOOR", 150)
# Phase 8 (2026-08-12): re-measured with cow/sheep added and quadrant zoning
# (QUAD_BONUS) in place. The original goose-only flock lost money at every
# size tried, on the pre-Phase-7 action-cost structure -- a bird grossed
# ~$150/day for ~7 unit-actions, against a crew already spending half its
# day walking. With cow/sheep (harvest every 2-3 days instead of daily) and
# cheaper effective movement, the flock is a net win. Re-swept again once
# MAX_LAND_BUYS dropped from 3 to 1 (see above) -- the two are coupled: with
# land no longer starving the flock's cash, more animals pay off before
# hitting the crew-time ceiling.
#
# 10 was measured as the optimum here, but that measurement was invalid: it
# used `tune.py`, which leaks KAG_* into a .py opponent as well as into us,
# so both sides moved together and the sweep was really a mirror match (see
# PROJECT_STATUS.md, Phase 13). Re-swept 0-16 with `sweep.py` against a
# frozen, env-immune opponent, 48 games per point, 3 independent seed sets.
# The curve has a clear interior peak and 10 is far past it:
#
#   MAX_ANIMALS   0      1      2      3      4      5      6      8     10
#   margin     -25.6k  -9.1k  +0.5k  +3.5k  +7.1k  +6.0k  +5.6k  +1.3k   --
#   winrate       0%    15%    46%    65%    94%    71%    79%    65%    --
#   (seed0=1000 column shown; 5000 and 12000 agree on the shape)
#
# 0 losing $25.6k over 48 games confirms the flock itself is essential -- the
# error was only ever the ceiling, not the engine. 4 and 5 tie on mean margin
# (+$6,225 vs +$6,347 over the 3 sets); 5 ships because it is the more robust
# of the two -- spread of +/-$332 across seed sets against 4's +/-$985, wins
# 2 of 3 sets, and sits mid-plateau (4-6) rather than one step from the
# drop-off at 3.
MAX_ANIMALS = _tune("MAX_ANIMALS", 5)          # hard ceiling on the flock, all species combined
ANIMALS_PER_UNIT = _tune("ANIMALS_PER_UNIT", 2.0)  # flock-slots per crew member
ANIMAL_UPKEEP = _tune("ANIMAL_UPKEEP", 3.0)    # tile-equivalents of crew time per animal
# Every top-leaderboard replay checked (episode 92349280 and 4 others via
# player カワシギ, rank #1) runs zero geese, ever -- goose only wins the
# early value-ranking because it matures fastest (first_yield_day=4 vs
# cow's 8, sheep's 6), grabbing crew-time and cash a cow or sheep would
# have used better once it matured. Confirmed by removing it: replicated on
# 2 independent seed sets (78% winrate, +$4.6-4.8k mean margin vs the
# GOOSE-enabled build). 1 keeps goose in the species pool; the measured
# improvement is 0.
GOOSE_ENABLED = _tune("GOOSE_ENABLED", 0)

# Fertilizer OFF by default -- built, measured, and it does not pay. FERTILIZE
# doubles what a watering adds, for `day`..`day+2`, and draws one FERTILIZER
# from the acting unit's OWN inventory -- not the shed -- so every application
# draws one FERTILIZER from the acting unit's OWN inventory -- not the shed --
# needs a PICKUP trip first.
#
# On paper only the ongoing crops are worth it: their scheduled productions go
# from 1 unit to 2, and one 3-day cover catches several --
#   STRAWBERRY  fires at ages 10,12,14,16; a cover catches two, so two
#               applications double all four:  +4 x $120 base
#   TOMATO      fires at ages 8,9,10,11; one cover catches three: +4 x $60
# The one-time crops never are: wheat gains +2 x $25 and carrot +1 x $35, both
# under the ~$100 a sack costs, and melon only reaches its cap two days sooner.
# So only TOMATO and STRAWBERRY are ever considered.
#
# It still loses, and the reason is that the paper numbers are quoted at base.
# We already flood tomato and strawberry -- they are the crops the engine likes
# -- so the marginal unit clears far below base while the sack costs $100 and
# rises as we buy. Measured over 16 seeds vs pass, against a $77,495 baseline:
#
#   naive (value units at sticker)      $55,381   -$22.1k
#   + price through batch_revenue       $68,956    -$8.5k
#   + buy per free hand, not per tile   $71,548    -$5.9k
#   + FERT_MARGIN 2.0 / 3.0      $75,078 / $76,350
#   + FERT_MARGIN 5.0                   $77,495       $0   (never fires)
#
# Monotonic to baseline: the best available outcome is to not do it. Revisit
# only if the agent stops saturating those two markets, or if animals ever come
# back -- they make fertilizer free, which removes the whole cost side.
FERT_ON = _tune("FERT_ON", 0)                # 1 enables the fertilizer engine
FERT_BATCH = _tune("FERT_BATCH", 4)          # fertilizer carried per shed trip
FERT_MARGIN = _tune("FERT_MARGIN", 1.0)      # revenue must beat this x sack price
FEED_DAYS = _tune("FEED_DAYS", 3)            # days of wheat feed to hold back from sales
PICKUP_BATCH = _tune("PICKUP_BATCH", 6)      # wheat carried per shed trip
PORTER_FILL = _tune("PORTER_FILL", 0.6)      # shed fill fraction that starts porter runs

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


def animal_output(animal, placed_day, from_day):
    """Production still ahead of one placed animal: (yield events, fertilizer pickups).

    A goose placed on day d first produces at the end of day `d + first_yield_day
    - 1`, and every `interval` days after. Its tile is flagged for fertilizer at
    the end of every day from d onward, which we collect the following morning.
    """
    a = ANIMALS[animal]
    first_eod = placed_day + a["first_yield_day"] - 1
    start = max(from_day, first_eod)
    yields = 0
    if start <= LAST_EOD_DAY:
        yields = (LAST_EOD_DAY - start) // a["interval"] + 1
    return yields, max(0, (TOTAL_DAYS - 1) - from_day)


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


def _quadrant_of(x, y, size):
    half = size // 2
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def step_toward(x, y, tx, ty):
    dx, dy = tx - x, ty - y
    if abs(dx) >= abs(dy):
        return "EAST" if dx > 0 else "WEST"
    return "SOUTH" if dy > 0 else "NORTH"


# Per-unit "what job was I walking to last turn" memory, keyed by player so a
# self-play match (same callable for both seats, same process) can't cross-talk.
# Reset at the top of a new episode so a stale key from a previous game can't
# award an undeserved bonus.
_TARGETS = {}


def _decide(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {}) or {}
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)
    if day == 0 and hour == 0:
        _TARGETS[player] = {}
    prev_targets = _TARGETS.setdefault(player, {})
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
    free_coops = []   # built COOPs with no bird in them
    animals = []      # (x, y, tile, animal)
    unlocked_tiles = 0
    pipeline = {}  # item -> units still to come, ours, not yet sold

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
                if "animal" in t:
                    animals.append((x, y, t, t["animal"]))
                    continue
                if kind in ("COOP", "PASTURE"):
                    free_coops.append((x, y, kind))
                    continue
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
        if item in MARKET_PARAMS and qty > 0:
            pipeline[item] = pipeline.get(item, 0) + qty
    for inv in inventories:
        for item, qty in inv.items():
            if item in MARKET_PARAMS and qty > 0:
                pipeline[item] = pipeline.get(item, 0) + qty

    # Everything the flock we already own will still lay this season counts as
    # supply we are committed to, exactly like a growing crop.
    for (x, y, t, animal) in animals:
        a = ANIMALS[animal]
        yields, colls = animal_output(animal, t.get("placed_day", day), day)
        pipeline[a["product"]] = pipeline.get(a["product"], 0) + yields * EGGS_PER_YIELD
        pipeline["FERTILIZER"] = pipeline.get("FERTILIZER", 0) + colls

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
    # the meantime, plus the unsold pipeline. The town's drawdown is what
    # creates the scarcity premiums (strawberry, tomato) worth chasing, and the
    # pipeline term is what stops us flooding any one market.
    #
    # `pipeline` holds only our own crop, because the opponent's fields are not
    # in the observation. Scaling it by OPP_SUPPLY charges a planting for the
    # supply we cannot see. The bias this corrects is worst on exactly the crops
    # we rank highest -- a symmetric opponent wants them for the same reasons --
    # so leaving it at 0 systematically overvalues our first choice.
    supply_scale = 1.0 + OPP_SUPPLY
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
        start = minv.get(crop, MARKET_I0) - drawdown + pipeline.get(crop, 0) * supply_scale
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

    def start_inventory(item, horizon):
        """Market inventory `item` will face once our share of it lands."""
        drawdown = demand_over(horizon).get(item, 0.0) * horizon
        return minv.get(item, MARKET_I0) - drawdown + pipeline.get(item, 0) * supply_scale

    # ── Flock valuation ────────────────────────────────────────────────────
    # An animal is priced exactly like a planting: the revenue its remaining
    # output clears against the inventory that output will face, less the
    # animal and the wheat it eats. `pipeline` already carries the existing
    # flock's production, so each extra animal is automatically valued at
    # the margin. Generic over species -- COOP holds GOOSE, PASTURE holds
    # COW or SHEEP, and all three eat WHEAT.
    crew = max(1, len(hands) + 1)

    def animal_value(species, placed_day):
        a = ANIMALS[species]
        yields, colls = animal_output(species, placed_day, day)
        units = yields * EGGS_PER_YIELD
        if units <= 0 and colls <= 0:
            return -1.0
        rev = batch_revenue(a["product"], start_inventory(a["product"], max(1, yields)), units)
        rev += batch_revenue("FERTILIZER", start_inventory("FERTILIZER", max(1, colls)), colls)
        # Feed is wheat we could otherwise have sold, one per day it is alive.
        return rev - colls * price_of("WHEAT")

    # Value of starting each species new today, net of buying it. Ranked so
    # the shared crew-time and cash budget below goes to the best species
    # first -- this is what lets cow/sheep's higher $-per-action naturally
    # win the budget over goose without hand-coding a preference.
    new_value = {sp: animal_value(sp, day) - ANIMALS[sp]["cost"] for sp in ANIMALS}
    buyable_species = ANIMALS if GOOSE_ENABLED else (sp for sp in ANIMALS if sp != "GOOSE")
    species_order = sorted((sp for sp in buyable_species if new_value[sp] > 0),
                            key=lambda sp: -new_value[sp])
    flock = len(animals)
    flock_by_species = {}
    for (_, _, _, sp) in animals:
        flock_by_species[sp] = flock_by_species.get(sp, 0) + 1
    free_by_kind = {"COOP": [], "PASTURE": []}
    for (x, y, kind) in free_coops:
        free_by_kind[kind].append((x, y))

    # Land compounds harder than any animal: $1,000 buys a 25-tile quadrant
    # worth roughly $10k of crop over the rest of a season, against $1,800
    # for a $300 goose. So the flock only gets the cash the land programme
    # does not want, which naturally holds it back until the farm is bought.
    n_extra_now = len(unlocked) - 1
    land_reserve = 0
    if (n_extra_now < min(len(LAND_PRICES), MAX_LAND_BUYS)
            and days_left >= LAND_MIN_DAYS[n_extra_now]):
        land_reserve = (LAND_PRICES[n_extra_now] + LAND_BUFFER) * LAND_RESERVE_FRAC
    spare_cash = max(0, money - CASH_FLOOR - land_reserve)

    # Greedily hand each species (best value first) a share of the shared
    # crew-time and cash budget, then work out how many of that allocation
    # still need a new structure built vs. can use one already standing.
    # PASTURE is shared between COW and SHEEP, so structures claimed by an
    # earlier (better-value) species come off the pool before the next one
    # looks at it.
    total_cap = min(MAX_ANIMALS, int(crew * ANIMALS_PER_UNIT))
    remaining_slots = max(0, total_cap - flock)
    remaining_cash = spare_cash
    target_flock = dict(flock_by_species)
    build_need = {"COOP": 0, "PASTURE": 0}
    pool = {"COOP": len(free_by_kind["COOP"]), "PASTURE": len(free_by_kind["PASTURE"])}
    for sp in species_order:
        a = ANIMALS[sp]
        room = min(remaining_slots, int(remaining_cash // a["cost"]))
        if room <= 0:
            continue
        target_flock[sp] = flock_by_species.get(sp, 0) + room
        remaining_slots -= room
        remaining_cash -= room * a["cost"]
        kind = a["structure"]
        use_free = min(pool[kind], room)
        pool[kind] -= use_free
        build_need[kind] += room - use_free

    # ── Job list ───────────────────────────────────────────────────────────
    # Each job is priced in dollars. `need` restricts it to units already
    # carrying something (FEED needs wheat, PLACE needs the bird); `unit` pins it
    # to one unit; `key` is what two jobs may not share this turn. Crop ops key
    # on the tile because they consume it, but a coop can be fed, cared for and
    # harvested by three different units in the same turn, so animal ops key on
    # (tile, op).
    jobs = []

    def add(value, x, y, action, need=None, unit=None, key=None):
        jobs.append({"v": value, "x": x, "y": y, "a": action,
                     "need": need, "unit": unit,
                     "key": (x, y) if key is None else key})

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
            add(yu * price_of(crop) + tile_unlock_value * 0.5, x, y, ["HARVEST"])
            continue

        # An ongoing crop that has given up its last harvest is now just a
        # future weed sitting on a tile we want back.
        if cd["ongoing"] and age >= plan["target_age"] and yu <= 0:
            add(tile_unlock_value * 0.8, x, y, ["DIG"])
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
            add(gain, x, y, ["WATER"])

    # Fertilizer jobs. `fertilized_until_day` already covers a span, so an
    # application only earns the productions it newly reaches -- re-fertilizing
    # inside an active cover is pure waste.
    def fert_units(crop, t, age):
        """Extra units one FERTILIZE now would add, over just watering."""
        cd = CROPS[crop]
        if not cd["ongoing"]:
            return 0
        room = cd["max_yield"] - t.get("yield_units", 0)
        if room <= 0:
            return 0
        first, iv = cd["first_yield_day"], cd["interval"]
        covered = t.get("fertilized_until_day", -1)
        hits = 0
        for k in (0, 1, 2):
            a = age + k
            if day + k <= covered or a - age > days_left:
                continue
            if a < first or (a - first) % iv or (a - first) // iv >= cd["max_yield"]:
                continue
            hits += 1
        return min(room, hits)

    # The extra units are marginal on top of everything already coming, so they
    # must be priced against the inventory they will actually meet. Valuing them
    # at today's sticker is what made the first cut of this lose $22k a game: it
    # bought ~115 sacks a season for units that cleared at a fraction of quote.
    # Cost is quoted post-buy, like the wheat feed, since each sack we take out
    # lifts the next one's price.
    fert_p_now = market_price("FERTILIZER", minv.get("FERTILIZER", MARKET_I0) - 1)
    want_fert = 0
    if FERT_ON and not last_day:
        for (x, y, t, crop, age) in plants:
            n = fert_units(crop, t, age)
            if n <= 0:
                continue
            rev = batch_revenue(crop, start_inventory(crop, 3), n)
            gain = rev - fert_p_now
            # The sack's price is not the whole cost: applying it burns a unit
            # action plus a share of a PICKUP trip, and the cash competes with
            # seed and land. FERT_MARGIN is the headroom that stands in for both.
            if rev > FERT_MARGIN * fert_p_now:
                want_fert += 1
                add(gain, x, y, ["FERTILIZE"], need=("FERTILIZER", 1))

    for (x, y) in weeds:
        if not last_day:
            add(tile_unlock_value * 0.8, x, y, ["DIG"])

    # ── Flock husbandry ────────────────────────────────────────────────────
    # Rough per-unit-wheat value reference for feed logistics, generalized
    # from the goose-only `egg_p` to whichever product the actual flock (or,
    # with nothing held yet, the best species we'd buy) currently produces.
    flock_species = set(flock_by_species) or set(species_order)
    flock_prod_p = max((float(price_of(ANIMALS[sp]["product"])) for sp in flock_species),
                        default=0.0)
    fert_p = float(price_of("FERTILIZER"))
    wheat_p = float(price_of("WHEAT"))
    unfed = 0

    for (x, y, t, animal) in animals:
        a = ANIMALS[animal]
        prod_p = float(price_of(a["product"]))
        yu = t.get("yield_units", 0)
        placed = t.get("placed_day", day)
        yields_left, _ = animal_output(animal, placed, day)
        produces_tonight = yields_left > 0 and day >= placed + a["first_yield_day"] - 1

        # HARVEST. Beyond the face value of what is held, a full nest wastes
        # tonight's laying, since max_held caps what may sit uncollected.
        if yu > 0:
            v = yu * prod_p
            if produces_tonight:
                v += max(0, yu + EGGS_PER_YIELD - a["max_held"]) * prod_p
            add(v, x, y, ["HARVEST"], key=(x, y, "HARVEST"))

        # Fertilizer is re-flagged every night and the town never consumes it,
        # so it is pure upside for one action -- until we have flooded it.
        if t.get("fertilizer_available") and fert_p > PRICE_FLOOR:
            add(fert_p, x, y, ["COLLECT_FERTILIZER"], key=(x, y, "COLLECT_FERTILIZER"))

        if last_day:
            continue

        # FEED costs a wheat out of the unit's own hands. Two consecutive dry
        # nights and the bird escapes, taking the rest of its season with it.
        if not t.get("fed_today"):
            unfed += 1
            v = -wheat_p
            if produces_tonight:
                v += t.get("pending_care_bonus", 0) * prod_p
            if t.get("consecutive_unfed", 0) >= 1:
                v += max(0.0, animal_value(animal, placed))   # it escapes tonight otherwise
            else:
                v += (EGGS_PER_YIELD * prod_p + fert_p) * 0.5
            if v > 0:
                add(v, x, y, ["FEED"], need=(a["feed"], 1), key=(x, y, "FEED"))

        # CARE banks a +1 bonus that tomorrow night's laying spends, so it only
        # pays while there is another laying night left to spend it on.
        if (not t.get("cared_today") and day + 1 <= LAST_EOD_DAY
                and day + 1 >= placed + a["first_yield_day"] - 1):
            add(prod_p, x, y, ["CARE"], key=(x, y, "CARE"))

    # Placing an animal we already own realises its whole remaining season.
    # A COOP only ever takes a GOOSE; a PASTURE takes whichever of COW/SHEEP
    # is worth more right now. Both PLACE options on one PASTURE tile share
    # the tile's default key, so only one of them can actually be claimed.
    if not last_day:
        for (x, y, kind) in free_coops:
            if kind == "COOP":
                v = animal_value("GOOSE", day)
                if v > 0:
                    add(v, x, y, ["PLACE", "GOOSE"], need=("GOOSE", 1))
            else:
                for sp in ("COW", "SHEEP"):
                    v = animal_value(sp, day)
                    if v > 0:
                        add(v, x, y, ["PLACE", sp], need=(sp, 1))

    # Never take on more plants than the crew can keep watered -- an unwatered
    # plant is not just wasted seed, it becomes a weed that costs a DIG too.
    # Animals draw on the same crew-time budget.
    care_capacity = max(0, crew * PLANTS_PER_UNIT - len(plants)
                        - int(len(animals) * ANIMAL_UPKEEP))

    # A structure is free to build; what it costs is the tile and the animal
    # that will go in it. `build_need` was computed above per structure kind,
    # already netted against free structures the flock-sizing pass claimed.
    coop_budget = build_need["COOP"]
    pasture_budget = build_need["PASTURE"]
    if coop_budget > 0:
        v = new_value.get("GOOSE", -1)
        for (x, y) in empties:
            add(v, x, y, ["BUILD_COOP"])
    if pasture_budget > 0:
        v = max(new_value.get("COW", -1), new_value.get("SHEEP", -1))
        for (x, y) in empties:
            # Default key (x, y) -- same as BUILD_COOP's -- so the two
            # options for one empty tile are mutually exclusive in the
            # auction rather than both claimable by different units.
            add(v, x, y, ["BUILD_PASTURE"])

    plant_budget = 0
    if not last_day and best_value > 0:
        usable_seeds = sum(seeds.get(c, 0) for c in CROPS if crop_profit(c) > 0)
        plant_budget = min(len(empties), usable_seeds, care_capacity)
        plant_job_value = max(best_value * CROP_PLANS[best_crop]["cycle"], 1.0)
        for (x, y) in empties:
            add(plant_job_value, x, y, ["PLANT"])

    # ── Shed runs ──────────────────────────────────────────────────────────
    carried_wheat = sum(i.get("WHEAT", 0) for i in inventories)
    shed_wheat = shed.get("WHEAT", 0)
    shed_fill = sum(v for v in shed.values() if v > 0)
    incoming = sum(sum(v for v in inv.values() if v > 0) for inv in inventories)

    # Fetch feed. FEED draws from the unit's hands, not the shed, so somebody has
    # to walk it out; one trip carries enough wheat for several birds.
    if not last_day and shed_wheat > 0 and unfed > carried_wheat:
        short = unfed - carried_wheat
        for i, (tx, ty) in enumerate(SHED_TILES):
            n = min(PICKUP_BATCH, shed_wheat - i * PICKUP_BATCH, short - i * PICKUP_BATCH)
            if n <= 0:
                break
            add(n * (EGGS_PER_YIELD * flock_prod_p + fert_p) * 0.5, tx, ty,
                ["PICKUP", "WHEAT", n])

    # Fetch fertilizer. Like FEED, FERTILIZE draws from the unit's own hands, so
    # the sacks have to be walked out before any of the jobs above can fire.
    carried_fert = sum(i.get("FERTILIZER", 0) for i in inventories)
    shed_fert = shed.get("FERTILIZER", 0)
    if FERT_ON and not last_day and shed_fert > 0 and want_fert > carried_fert:
        short = want_fert - carried_fert
        for i, (tx, ty) in enumerate(SHED_TILES):
            n = min(FERT_BATCH, shed_fert - i * FERT_BATCH, short - i * FERT_BATCH)
            if n <= 0:
                break
            add(n * fert_p_now * 0.5, tx, ty, ["PICKUP", "FERTILIZER", n])

    # Fetch animals bought this season but still sitting in the shed. Keyed
    # per species so two species queued at the same shed tile don't collide
    # (the default (x, y) key only distinguishes tiles, not item type).
    if not last_day:
        for sp in ANIMALS:
            shed_n = shed.get(sp, 0)
            placeable = min(shed_n, len(free_by_kind[ANIMALS[sp]["structure"]]))
            v = animal_value(sp, day)
            if placeable > 0 and v > 0:
                for (tx, ty) in SHED_TILES[:placeable]:
                    add(v, tx, ty, ["PICKUP", sp, 1], key=(tx, ty, "PICKUP", sp))

    # Porter runs. Goods only reach the shed at end of day, and whatever does not
    # fit there is discarded silently -- so once the day's haul is outgrowing the
    # shed, walking some of it in early, where the SELL orders can drain it, is
    # worth real money. On the last day there is no end-of-day drop at all.
    crowded = shed_fill + incoming > SHED_CAP * PORTER_FILL
    if last_day or (crowded and shed_fill < SHED_CAP):
        for idx in range(1 + len(hands)):
            inv = inventories[idx] if idx < len(inventories) else {}
            # Wheat in a unit's hands while birds are hungry is feed in transit,
            # not produce: valuing it would send the feed run straight back to
            # the shed it just came from, and the flock starves.
            worth = sum(market_price(i, minv.get(i, MARKET_I0)) * q
                        for i, q in inv.items() if i in MARKET_PARAMS and q > 0
                        and not (unfed > 0 and i == "WHEAT"))
            if worth <= 0:
                continue
            # Don't send a unit ferrying a live animal back to the shed it
            # came from -- also not MARKET_PARAMS, so `worth` already skips it.
            if not last_day and any(inv.get(sp, 0) > 0 for sp in ANIMALS):
                continue
            x, y = (me["farmer"] if idx == 0 else hands[idx - 1])[:2]
            tx, ty = nearest_shed_tile(x, y)
            if hour + abs(tx - x) + abs(ty - y) >= TURNS_PER_DAY - 2:
                continue
            add(worth + 1e6 if last_day else worth * 0.6, tx, ty,
                ["DROP", idx], unit=idx, key=(tx, ty, "DROP"))

    # ── Assignment: highest-value job takes the nearest idle unit ──────────
    positions = [tuple(me["farmer"][:2])] + [tuple(h[:2]) for h in hands]
    n_units = len(positions)
    # Each unit's home quadrant is a pure function of its index and the
    # unlocked-quadrant list -- no memory needed, so it can't go stale across
    # the daily hand respawn the way a remembered job target would.
    home_quadrant = [unlocked[idx % len(unlocked)] for idx in range(n_units)]
    assigned = [None] * n_units
    assigned_key = [None] * n_units
    free = set(range(n_units))

    claimed = set()

    # Unit-pinned jobs (the porter runs) go first: only the unit whose hands are
    # full can do them, so they get no say in the auction.
    for job in jobs:
        idx = job["unit"]
        if idx is None or idx not in free:
            continue
        assigned[idx] = (job["x"], job["y"], job["a"][:1])
        assigned_key[idx] = job["key"]
        free.discard(idx)
        claimed.add(job["key"])

    # Rank every (unit, job) pair by value per action spent reaching it, so a
    # unit prefers a decent job at its feet over a great one across the farm.
    pairs = []
    for j, job in enumerate(jobs):
        if job["unit"] is not None:
            continue
        value, jx, jy = job["v"], job["x"], job["y"]
        need = job["need"]
        for idx in range(n_units):
            if need is not None:
                inv = inventories[idx] if idx < len(inventories) else {}
                if inv.get(need[0], 0) < need[1]:
                    continue
            px, py = positions[idx]
            dist = abs(jx - px) + abs(jy - py)
            if value - dist * MOVE_COST <= 0:
                continue
            score = value / (dist + 1.0)
            if dist <= STICKY_RANGE and prev_targets.get(idx) == job["key"]:
                score *= 1.0 + STICKY
            if _quadrant_of(jx, jy, size) == home_quadrant[idx]:
                score *= 1.0 + QUAD_BONUS
            pairs.append((score, idx, j))
    pairs.sort(key=lambda p: -p[0])

    for _, idx, j in pairs:
        if idx not in free:
            continue
        job = jobs[j]
        if job["key"] in claimed:
            continue
        op = job["a"][0]
        if op == "PLANT":
            if plant_budget <= 0:
                continue
            plant_budget -= 1
        elif op == "BUILD_COOP":
            if coop_budget <= 0:
                continue
            coop_budget -= 1
        elif op == "BUILD_PASTURE":
            if pasture_budget <= 0:
                continue
            pasture_budget -= 1
        assigned[idx] = (job["x"], job["y"], job["a"])
        assigned_key[idx] = job["key"]
        free.discard(idx)
        claimed.add(job["key"])
        if not free:
            break

    _TARGETS[player] = {idx: assigned_key[idx] for idx in range(n_units)
                         if assigned_key[idx] is not None}

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
    reserve_frac = RESERVE_FRAC
    if days_left <= 1:
        reserve_frac = 0.0
    elif days_left <= 4:
        reserve_frac = 0.15
    if shed_fill + incoming > SHED_CAP - 10:
        reserve_frac = min(reserve_frac, 0.05)  # overflow is discarded, so dump
    elif shed_fill > SHED_CAP * 0.7:
        reserve_frac *= 0.4

    # Wheat in the shed is also the flock's feed, and a bird that starves is
    # worth far more than the wheat that would have kept it: hold some back.
    feed_hold = 0 if last_day else min(flock * FEED_DAYS, SHED_CAP // 4)

    sell_orders = []
    sell_inv = dict(minv)
    proceeds = 0
    candidates = sorted(((i, q) for i, q in shed.items() if q > 0 and i in MARKET_PARAMS),
                        key=lambda kv: -market_price(kv[0], sell_inv.get(kv[0], MARKET_I0)))
    for item, qty in candidates:
        if item == "WHEAT":
            qty = max(0, qty - feed_hold)
            if qty == 0:
                continue
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
    if n_extra < min(len(LAND_PRICES), MAX_LAND_BUYS):
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

    # Animals. A bought animal lands in the shed and sits there taking a slot
    # until a unit fetches it, so only buy against a structure that is
    # already standing empty -- the one-turn lag is cheaper than a blocked
    # shed. Species compete for the same shared `cash`, best value first, so
    # it decrements sequentially across the loop just like seed buying does.
    # PASTURE's free-tile count is shared between COW and SHEEP here (unlike
    # the flock-sizing pass above, this doesn't decrement it between them),
    # so the two can slightly overbuy against the same empty pasture -- the
    # excess just waits an extra turn in the shed, same as the single-goose
    # design already tolerated.
    animal_orders = []
    if not last_day:
        for sp in species_order:
            a = ANIMALS[sp]
            kind = a["structure"]
            have = flock_by_species.get(sp, 0)
            want_total = target_flock.get(sp, have)
            if want_total <= have:
                continue
            shed_n = shed.get(sp, 0)
            carried = sum(i.get(sp, 0) for i in inventories)
            want = min(len(free_by_kind[kind]), want_total - have) - shed_n - carried
            want = min(want, max(0, SHED_CAP - shed_fill - 5))
            n = min(max(0, want), int(max(0, cash - CASH_FLOOR - land_reserve) // a["cost"]))
            if n > 0:
                animal_orders.append(["BUY_ANIMAL", sp, n])
                cash -= n * a["cost"]

    # Feed. Growing our own wheat is cheaper, but a starved bird escapes and
    # takes its whole remaining season with it, so top up rather than risk it.
    feed_orders = []
    if not last_day and flock > 0:
        short = flock * FEED_DAYS - shed_wheat - carried_wheat
        # BUY_PRODUCT quotes at the post-buy inventory, and each unit bought
        # lifts the next quote, so treat this as a floor on the true cost.
        unit_cost = market_price("WHEAT", minv.get("WHEAT", MARKET_I0) - 1)
        if short > 0 and unit_cost < EGGS_PER_YIELD * flock_prod_p:
            n = min(short, max(0, SHED_CAP - shed_fill - 5),
                    int(max(0, cash - CASH_FLOOR) // max(1, 2 * unit_cost)))
            if n > 0:
                feed_orders.append(["BUY_PRODUCT", "WHEAT", n])
                cash -= n * unit_cost

    # Fertilizer. Only bought against jobs that already price out as profitable,
    # and never more than one cover's worth ahead -- a sack in the shed is a
    # shed slot not holding produce.
    fert_orders = []
    if FERT_ON and not last_day and want_fert > shed_fert + carried_fert:
        unit_cost = market_price("FERTILIZER", minv.get("FERTILIZER", MARKET_I0) - 1)
        # A sack is only worth buying if somebody can carry it out and use it.
        # Sizing the order by profitable *tiles* rather than by crew buys a
        # season of stock on day one and starves the land programme of cash.
        want_fert = min(want_fert, 1 + len(hands))
        n = min(want_fert - shed_fert - carried_fert,
                max(0, SHED_CAP - shed_fill - 5),
                int(max(0, cash - CASH_FLOOR - land_reserve) // max(1, unit_cost)))
        if n > 0:
            fert_orders.append(["BUY_PRODUCT", "FERTILIZER", n])
            cash -= n * unit_cost

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
    fixed = (land_orders + hire_orders + animal_orders + feed_orders
             + fert_orders + seed_orders)
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
