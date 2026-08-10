# Kaggriculture Agent - Current Status(team)

## Overview
This document tracks the current features and recent improvements for the Kaggriculture agent.

**v10 Version Score:** ~9,700 – 15,300 (Average: ~$9,761, Median: ~$10,521)
*Significant improvement from the previous baseline of ~$8,238.*

---

## Current Implemented Features (v10)

### 1. Core Farming Loop
- [x] Multi-crop strategy: Heavily Melon-focused with Wheat and Carrot as fast cash fillers.
- [x] Strict plant capacity management (max 8 plants per worker) to prevent unwatered plants from dying and turning into weeds.
- [x] Water plants daily (critical fix: plants get `consecutive_unwatered=1` on the day they are planted).
- [x] Early Harvest optimization: Wheat and Carrot can be harvested before max yield to quickly replant and generate cash flow, while Melon waits for max yield.

### 2. Weed Management
- [x] Massive weed reduction due to strict watering capacity limits.
- [x] Dig weeds when encountered.

### 3. Labor
- [x] Hire up to 3 farm hands (1 farmer + 3 hands = 4 workers total).
- [x] Hands reset daily, so the agent hires 3 hands at hour 0 of every day (costing $4/day).
- [x] Farm hands utilize the same smart BFS movement logic as the farmer.

### 4. Movement
- [x] All units use smart BFS movement.
- [x] Distance penalty tweaked (reduced to `dist * 3`) to allow workers to spread out and plant across the entire grid without getting stuck in the corner.
- [x] Workers avoid moving to tiles that are already targeted by other workers (using an `occupied_set`).

### 5. Market & Economy
- [x] Batch selling: Sales are capped per turn (e.g., max 4 Melons, 15 Wheat) to prevent crashing the market prices via the `sq` price curve.
- [x] Aggressive day 0 seed buying (Melon, Carrot, Wheat) to maximize early game production.
- [x] Land expansion: Automatically buys land when economy is strong (money ≥ $3000 and day ≥ 10).
- [x] End-of-season dump: Sells entire shed inventory on the last 2 days.

---

## Features Tried but Removed or Deferred

| Feature              | Reason for Removal                     |
|----------------------|----------------------------------------|
| A* Pathfinding       | Caused performance instability         |
| Fertilizer system    | Requires further testing to prevent economy collapse |
| Goose / Eggs         | Too expensive + feeding issues         |
| 100% Melon           | Takes too long to yield, need fast cash crops (Wheat) early |

---

## Next Recommended Steps

### Phase 1 – Market Fine-Tuning
- Dynamically adjust batch selling limits based on actual observed market prices rather than static limits.
- Optimize the seed buying logic when expanding land to rapidly fill the newly acquired 25 tiles.

### Phase 2 – Advanced Items
- Reintroduce Fertilizer, but strictly limit its use to Melon crops on days 12-25 when money is abundant.
- Add logic to monitor the opponent's shed/market activity and undercut their sales.

---

## Notes
- The agent is heavily optimized around the environment's specific mechanics (e.g., plants needing water on the exact day they are planted, price curves).
- Performance is consistently beating the 'random' baseline by a massive margin.
