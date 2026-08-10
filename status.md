# Kaggriculture Agent - Current Status(team)

## Overview
This document tracks the current features and planned improvements for the Kaggriculture agent.

**Base Version Score:** ~8,000 – 12,000 (best observed: ~11,987)

---

## Current Implemented Features

### 1. Core Farming Loop
- [x] Buy Wheat seeds
- [x] Buy Melon seeds (preferred when money ≥ 80)
- [x] Plant Melon (priority) and Wheat (fallback)
- [x] Water plants daily
- [x] Harvest mature crops
  - Wheat: age ≥ 2
  - Melon: age ≥ 10
- [x] Sell harvested produce from the shed

### 2. Weed Management
- [x] Detect weeds
- [x] Dig weeds when standing on them
- [x] Prefer moving toward weeds

### 3. Labor
- [x] Hire 1 farm hand (when money ≥ 30 and step > 10)
- [x] Farm hand can plant, water, harvest, and dig weeds
- [ ] Farm hand still uses simple (non-smart) movement

### 4. Movement
- [x] Farmer uses smart local movement
  - Prioritizes: Weed → Harvest → Water → Plant
- [x] Basic direction fallback (East → South → West → North)
- [ ] No real pathfinding (A* was tried but made the agent unstable)
- [ ] Farm hand movement is still basic

### 5. Market
- [x] Buy seeds when needed
- [x] Sell all Melon and Wheat from shed every turn
- [x] Hire hand via market order
- [ ] No fertilizer buying/usage
- [ ] No animal buying
- [ ] No land expansion (`BUY_LAND`)
- [ ] No advanced sell timing / price impact ranking

---

## Features Tried but Removed (Unstable)

| Feature              | Reason for Removal                     |
|----------------------|----------------------------------------|
| A* Pathfinding       | Caused performance instability         |
| Fertilizer system    | Economy collapsed when added too early |
| Goose / Eggs         | Too expensive + feeding issues         |
| Multi-hand hiring    | Caused money problems                  |
| Complex inventory logic | Introduced bugs                     |

---

## Recommended Improvement Roadmap

### Phase 1 – Stability & Efficiency (Next)
1. **Smart movement for the farm hand** (same logic as farmer)
2. Buy multiple seeds at once (instead of 1)
3. Better threshold for hiring the hand

### Phase 2 – Economy Boost
4. Simple Fertilizer usage (only on Melon, only when money is safe)
5. Stop selling everything every turn (basic price awareness)

### Phase 3 – Scaling
6. Land expansion (`BUY_LAND`)
7. Second farm hand
8. Basic animal (Goose) with very strict conditions

### Phase 4 – Advanced
9. Price-impact sell ranking
10. Terminal dump (force sell near day 30)
11. Opponent awareness

---

## Current Agent Architecture

```
Observation
    ↓
Market Decisions (Buy seeds / Sell / Hire)
    ↓
Decide action on current tile (Farmer + Hand)
    ↓
If idle → Smart Movement (Farmer only)
    ↓
Return action dict
```

---

## Notes
- The agent is currently **deterministic** and rule-based.
- No machine learning / reinforcement learning is used yet.
- Focus remains on building a strong, stable scripted agent first.

---

