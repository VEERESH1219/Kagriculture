# Kaggriculture — start-here brief for the next session

**Written:** 2026-08-12 · **Branch:** `KA-agent` · **HEAD:** (post-Phase-8 land/animal rework commit, see `git log`)

Open this in a fresh chat and say *"read NEXT_SESSION.md and start Phase 9."*
Everything needed to resume is here or linked from here.

---

## 0. The one question first: should I submit `main.py`?

**Yes — this is the biggest measured gain of any session so far.**

After Phase 8 shipped cow/sheep, a top-of-leaderboard replay analysis (see
§3) led to a land-purchase fix (`MAX_LAND_BUYS=1`) and a re-tuned flock cap
(`MAX_ANIMALS=10`, up from 6) that together measured **98% winrate and
+$13.3k mean margin** over 128 games against the prior (already-submitted)
Phase 8 build.

Pre-flight checks:

| Check | Result |
|---|---|
| `agent` is the last callable in the file | ✅ |
| Signature is `agent(obs)` | ✅ |
| Runs clean vs `pass` | ✅ $92,084 mean, 32/32 |
| Stdlib only, self-contained | ✅ |
| `KAG_DEBUG=1` run with animals on — no hidden exceptions | ✅ |

**Recommendation: submit now.**

---

## 1. State of the repo

Working tree: current changes are in `main.py`, `PROJECT_STATUS.md`,
`.gitignore` (added `replays/`, which holds a downloaded episode replay used
for the leaderboard analysis below — not source, don't commit it). Check
`git status` and `git log origin/KA-agent..HEAD` before assuming what's pushed.

### Measured performance (current HEAD, `QUAD_BONUS=2.0`, `MAX_LAND_BUYS=1`, `MAX_ANIMALS=10`)

| Matchup | Games | Ours | Opponent |
|---|---|---|---|
| vs `pass` | 64 | $92,084 | $3,000 |
| vs `baselines/v12.py` | 64 (swap) | $87,456 | $3,632 |
| vs prior build (frozen Phase-8 HEAD) | 128 (swap) | $77,035 | $63,689 |

Phase 8's numbers for the same matchups were $86,937 / $81,851 / (its own
frozen-HEAD test, $65,519 vs $57,112) — this session improved everywhere it
was checked, no regression found.

**Quote the frozen-HEAD number, not the `pass` number** — same logic as
every prior session: `pass` doesn't compete for the market.

---

## 2. What Phase 8 did — cow and sheep

The `main.py:80` comment ("only GOOSE is worth the tiles") judged animals on
lifetime market cap (EGG never saturates, MILK/WOOL do around $6-8k). But
action cost is the binding constraint (Phase 7's own finding), and on
$-per-action cow ($50) and sheep ($49) roughly double the goose's $26 — they
harvest every 2-3 days instead of daily. This was deliberately deferred from
an earlier session specifically until after Phase 7 changed the action-cost
structure the comparison depends on.

### Engine facts confirmed before writing any code

Read `kaggriculture.py` rather than guessing:

- `ANIMALS = {GOOSE: cost 300/COOP/interval 1, COW: cost 400/PASTURE/interval
  2, SHEEP: cost 500/PASTURE/interval 3}` — exact params taken from the
  engine source, not re-derived.
- The `FEED` action handler takes 1 `WHEAT` **unconditionally**, regardless
  of animal type — confirms `feed: "WHEAT"` is correct for all three.
  `COOP` only ever holds `GOOSE`; `PASTURE` holds either `COW` or `SHEEP`.
- The generic per-animal job-generation loop (`FEED`/`CARE`/`HARVEST`/
  `COLLECT_FERTILIZER`) and `animal_output()` were **already fully generic**
  over species before this change — they just never got exercised because
  `ANIMALS` only ever listed `GOOSE`. Only the species-*selection* logic
  (which species to value, buy, and build structures for) needed to grow.

### The refactor (~160 lines, main.py)

- `ANIMALS` gained `COW`/`SHEEP`.
- `goose_value()` → `animal_value(species, placed_day)`.
- `new_value = {species: animal_value(sp, day) - cost}`, ranked into
  `species_order` (best value first) so the shared crew-time/cash budget
  goes to the best species first — this is what lets cow/sheep's higher
  $-per-action win the budget over goose *without* a hand-coded species
  preference. It falls out of the existing value-ranking pattern the file
  already used everywhere else (crop ranking, job auction).
- `target_flock`/`build_need` computed once, per-species, greedily against
  a shared `crew * ANIMALS_PER_UNIT` slot budget and shared cash — `PASTURE`
  structures are a shared pool between COW and SHEEP, decremented as each
  species (in value order) claims some.
- `PLACE`/`BUILD_COOP`/`BUILD_PASTURE`/`PICKUP`/`BUY_ANIMAL` jobs all loop
  over species now. `BUILD_COOP` and `BUILD_PASTURE` on the same empty tile
  share the tile's default `(x, y)` job key so they're mutually exclusive in
  the auction, same trick used for the two `PLACE` options on one `PASTURE`
  tile.
- **Fixed a latent bug along the way**: the escape-penalty term inside the
  generic FEED loop called the goose-only `goose_value()` regardless of
  which species was actually about to escape. Harmless while only `GOOSE`
  existed (same species every time); would have mispriced cow/sheep escapes
  had this not been caught before shipping.

### Measurement — swept `MAX_ANIMALS` 4→24, replicated on 4 independent seed sets

All against a frozen Phase-7 opponent, `--swap`:

| Seed set | `MAX_ANIMALS` | n | Mean | Opp mean | Winrate |
|---|---|---|---|---|---|
| seed0=5000 | 8 | 64 | $65,967 | $60,948 | 61% |
| seed0=6000 | 6 | 64 | $68,065 | $60,530 | 75% |
| seed0=2000 | 6 | 64 | $66,932 | $55,666 | 88% |
| seed0=1000 (final) | 6 | 128 | $65,519 | $57,112 | 68% |

Falls off past 12, flat by 24. Shipped `MAX_ANIMALS=6` at the time.

---

## 3. What came next — a leaderboard replay found a bigger problem than the flock cap

Downloaded a top-of-leaderboard replay (`kaggle competitions replay
92267113`, saved to `replays/`, gitignored) between two ~$85k finishers.
Both ran the same strategy: land and crew maxed out by day 12, then an
almost-total pivot to animals. Final state: **12-13 animals, 100%
COW/SHEEP, zero GOOSE, 0-1 crop tiles, 56-57 of ~75 unlocked tiles sitting
completely empty.** Analysis method, if you want to do this again for a
future replay: `kaggle competitions replay <episode_id>` downloads the same
JSON `kaggle_environments` uses internally — index into `data['steps'][i][player]['observation']['farms'][player]` to read farm state at any point, same shape `bench.py`/`trace.py` already consume.

Naively raising `MAX_ANIMALS` further (10→24) made things *worse*, the
opposite of what the replay implied should be possible. Tracing our own
agent's day-by-day cash and animal count exposed the real problem:
`land_reserve` in `main.py` reserves the **entire** next quadrant's price +
buffer, continuously, until it's bought — and with `LAND_MIN_DAYS =
[5,6,8]`, that reserve is active almost the whole game, across all 3
purchasable quadrants sequentially, choking `spare_cash` and delaying real
animal investment until day 21+. Crew hit its cap by day 12, but the flock
stayed at 0 animals until day 12 and didn't stabilize until day 24+.

Added `MAX_LAND_BUYS` (of the 3 purchasable quadrants) and swept it
alongside `MAX_ANIMALS`. Matching the replay's own stopping point
(`MAX_LAND_BUYS=2`) already helped, but **`MAX_LAND_BUYS=1` (buy only NE,
skip SW/SE) did much better** — our agent's cash reaches the flock faster
once even one quadrant's reserve is removed, so it needs the extra land
less than the replay's strategy did. `MAX_LAND_BUYS=0` is a clear loss (the
first extra quadrant does matter). With land no longer starving the flock,
`MAX_ANIMALS`'s true optimum moved from 6 to 10.

**Lesson for next time a strategy idea comes from watching someone else
play:** the replay was the right prompt to go looking, but copying its
numbers directly (`MAX_LAND_BUYS=2`, their ~12-13 animal count) would have
shipped a worse build than what our own agent's cash trajectory, once
traced, actually supported. Use external play as a hypothesis generator,
verify by tracing your own agent, not by matching their numbers.

| Combination | Seed set | n | Mean | Opp mean | Winrate |
|---|---|---|---|---|---|
| `MAX_LAND_BUYS=1, MAX_ANIMALS=8` | seed0=2000 | 64 | $80,451 | $69,325 | 97% |
| `MAX_LAND_BUYS=1, MAX_ANIMALS=10` | seed0=3000 | 64 | $78,585 | $65,237 | 100% |
| `MAX_LAND_BUYS=1, MAX_ANIMALS=10` (final) | seed0=1000 | 128 | $77,035 | $63,689 | 98% |

Shipped `MAX_LAND_BUYS=1`, `MAX_ANIMALS=10`.

---

## 4. Remaining work, in the order I'd do it

### 🔜 Phase 9 — Fix the panic-dump rule  ← **START HERE** *(live bug, not an enhancement)*

When `shed_fill + incoming > SHED_CAP - 10`, `reserve_frac` drops to `0.05`
and the agent sells **anything at almost any price**. Traces showed melon
dumped at **$4** against a $250 base.

Overflow really is discarded, so the rule is right in principle — but it
should dump the **cheapest** items, not everything. This can fire *without*
animals whenever crop throughput is high, and now that the flock is bigger
(`MAX_ANIMALS=10`) and land tighter (`MAX_LAND_BUYS=1`, less shed-adjacent
tile flexibility... actually unrelated, but shed pressure from a bigger
flock is real), this may be costing more than it was. Small,
self-contained — find the `reserve_frac` logic near the market-orders
section of `main.py` and start there.

### Phase 10 — Land timing: mostly answered, but check `LAND_MIN_DAYS`/`LAND_BUFFER` interaction

`MAX_LAND_BUYS=1` (§3) answers the *how many* question. The *when* question
— `LAND_MIN_DAYS = [5,6,8]` gating when the reserve activates, and whether
`LAND_BUFFER=800` is still the right liquidity cushion now that the flock
competes harder for the same cash — hasn't been re-swept since the
`MAX_LAND_BUYS` change. Worth a quick check, likely smaller than the
`MAX_LAND_BUYS` win.

### Housekeeping

- `debug_wrapper.py` is redundant with `actions.py` / `trace.py`. Delete
  whenever.
- `PROJECT_STATUS.html` and `CODE_GUIDE.pdf`/`.html` are stale as of Phase 7
  and Phase 8. Re-render if anyone's going to read the formatted versions:
  ```bash
  google-chrome --headless --no-pdf-header-footer \
    --print-to-pdf=CODE_GUIDE.pdf CODE_GUIDE.html
  ```

---

## 5. How to run things

```bash
# Paired seeded benchmark. --swap cancels seat advantage. Ties are NOT wins.
.venv/bin/python bench.py --agent main.py --opp pass -n 32 --swap --seed0 1000
.venv/bin/python bench.py --agent main.py --opp baselines/v12.py -n 32 --swap

# Regression vs a frozen previous commit
git show <commit>:main.py > /tmp/prev.py
.venv/bin/python bench.py --agent main.py --opp /tmp/prev.py -n 64 --swap

# Sweep one parameter (against `pass` by default — see trap #3, prefer
# TUNE_OPP=/path/to/frozen/prev.py for anything you actually intend to ship)
.venv/bin/python tune.py MOVE_COST 3,5,7,9,11 -n 32
TUNE_OPP=/tmp/prev.py .venv/bin/python tune.py MAX_ANIMALS 4 6 8 12

# Where the time goes
.venv/bin/python actions.py

# Day-by-day trace of one game
.venv/bin/python trace.py

# Confirm which animal species actually get placed and produce (ad hoc,
# used to verify the Phase 8 refactor before trusting the bench numbers):
.venv/bin/python -c "
from kaggle_environments import make
import main
from collections import Counter
species_seen = Counter()
def traced(obs):
    result = main.agent(obs)
    me = obs['farms'][obs['player']]
    for row in me['tiles']:
        for t in row:
            if isinstance(t, dict) and 'animal' in t:
                species_seen[t['animal']] += 1
    return result
env = make('kaggriculture', configuration={'seed': 1000})
env.run([traced, 'pass'])
print(dict(species_seen))
"
```

**Every constant is an env var.** `_tune("NAME", default)` reads `KAG_NAME`.
Sweep without editing the file. `KAG_DEBUG=1` disables the try/except so
exceptions actually surface instead of silently returning no-ops.

Engine source of truth — read it rather than guessing at semantics:
```
.venv/lib/python3.13/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py
```

Submitting (kaggle CLI is installed in the project venv as of Phase 7 —
`.venv/bin/kaggle`, credentials at `~/.kaggle/access_token`):
```bash
.venv/bin/kaggle competitions submit kaggriculture -f main.py -m "message"
.venv/bin/kaggle competitions submissions kaggriculture
```

---

## 6. Traps this project has already fallen into

Read these before running an experiment. Each one cost real time.

1. **Replicate before you believe a sweep.** `OPP_SUPPLY=0.25` led sweep 1 at
   **81%** and went **negative** on fresh seeds. Always re-run the *whole
   curve* on an independent seed set, not just the winners. (Phase 7's
   `STICKY` also looked plausible on paper and lost on replication —
   replicating isn't optional even when the mechanism sounds right.)

2. **A deterministic agent vs a copy of itself ties exactly.** Mirror matches
   show ~6–20% "winrate" — that is the **neutral** result, not a loss. Don't
   panic at it, and don't cite it as evidence of anything.

3. **`pass` is not an opponent.** It flatters everything, because nothing
   competes for the market. Tune and verify against a frozen real build.

4. **Value harvests at marginal revenue, not sticker price.** The first
   fertilizer cut lost **$22k** by pricing extra units at `price_of(crop)`.
   Going through `batch_revenue(crop, start_inventory(crop, 3), n)` recovered
   $13.5k of it. Prices move as you sell — always price the batch. Phase 8's
   `animal_value()` follows the same pattern for eggs/milk/wool.

5. **Buy per *carrier*, not per opportunity.** Fertilizer bought one sack per
   profitable tile; capping at `1 + len(hands)` was worth $2.6k.

6. **Guess less, profile more.** A guess that fertilizer's loss was action
   cost was wrong (`actions.py` showed it was 2.5% of unit-actions). A guess
   that `STICKY`'s loss *was* about action cost was also wrong — profiling
   showed near-identical MOVE/PASS share with and without it. Phase 8 avoided
   a similar guess by reading the engine's `FEED` handler directly rather
   than assuming animal-specific feed items.

7. **Nothing callable may be defined below `agent`** in `main.py`. Kaggle's
   loader runs the *last* callable in the file.

8. **`OPP_SUPPLY=1.0` is a trade, not a free win.** It costs $4.8k against the
   weak-supplier `v12` baseline. Still the right call — 99/128 vs a real
   competitor — but don't describe it as a strict improvement.

9. **Persistent state must survive daily resets, not just episode resets.**
   Hands are wiped and rehired every morning, so a unit index doesn't mean
   the same physical unit two days running. A stateful scheme keyed on unit
   index (tried for `STICKY`) needs care about what goes stale; a stateless
   one (used for `QUAD_BONUS`) sidesteps the problem entirely. Prefer
   stateless when the data needed is cheap to recompute every turn.

10. **When generalizing single-case code to multiple cases, check each
    piece is actually still single-case before assuming it needs work.**
    Phase 8 found the per-animal `FEED`/`HARVEST`/`CARE` job loop was
    *already* generic (looked up `ANIMALS[animal]` throughout) — it only
    looked goose-specific because `ANIMALS` had one entry. Don't refactor
    code that's already correct; grep for the actual literal (`"GOOSE"`)
    rather than assuming every function touching animals needs a rewrite.

11. **A shared resource pool needs a single accounting pass, not repeated
    independent checks.** `PASTURE` is shared between COW and SHEEP; the
    flock-sizing pass decrements a shared `pool` dict as each species (best
    value first) claims free structures, so the second species sees what's
    left, not the original count. The `BUY_ANIMAL` order block deliberately
    does *not* do this same decrementing (comment explains why: the
    resulting slight overbuy just waits an extra turn in the shed, same
    tolerance the original single-species design already had) — don't
    "fix" that inconsistency without checking whether it's intentional.

12. **External play is a hypothesis generator, not a target to copy.** A
    top-leaderboard replay showed a winning strategy running ~12-13 animals
    and buying 2 extra land quadrants. Copying those numbers directly would
    have shipped a worse build — our agent's own cash trajectory, once
    traced, supported a *different* land count (1, not 2) and a different
    animal cap (10, not 12-13). The replay was right to prompt investigation
    (it revealed `MAX_ANIMALS` alone wasn't the bottleneck), but the actual
    fix came from profiling our own agent, same discipline as trap #6.

---

## 7. Where the deeper docs are

| File | What's in it |
|---|---|
| `PROJECT_STATUS.md` | **Source of truth.** Full experiment log, every result. |
| `PROJECT_STATUS.html` | Same, formatted and self-contained — **stale as of Phase 7/8, re-render if needed.** |
| `kaggriculture_handoff.md` | Deep technical handoff — engine facts, design rationale. |
| `CODE_GUIDE.pdf` / `.html` | Every `.py` file explained, 13 pages — **stale as of Phase 7/8.** |
| `README.md` | The full rulebook — crop/animal tables, price functions, buildings. |
| `AGENTS.md` | Kaggle submission and replay mechanics. |

---

## 8. Suggested opening message for the new chat

> Read `NEXT_SESSION.md`. Start Phase 9 — fix the panic-dump rule so it
> dumps the cheapest shed items instead of everything when
> `reserve_frac` collapses. Measure with a paired swap benchmark against
> the current HEAD before keeping any change.
