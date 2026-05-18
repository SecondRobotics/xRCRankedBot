# Queue Performance Design

**Date:** 2026-05-18  
**Scope:** `cogs/ranked.py` — queue join and match start paths  
**Goal:** Reduce perceived latency on `/queuestandard`, `/queuevoting`, and match start

---

## Problem

Two classes of slowness:

1. **Queue join** — Every join makes two sequential HTTP calls to the same endpoint (`/api/ranked/player/{id}`): once in `validate_player()` to check registration, immediately again in `get_player_info()` to fetch the display name. Additionally, `update_ranked_display()` (a Discord message edit) is awaited inline, blocking the ephemeral response.

2. **Match start** — Role creation, role assignment, and end-of-game member moves are all sequential Discord API calls where they could be parallelized with `asyncio.gather`.

---

## Changes

### 1. Eliminate duplicate API call

`validate_player()` currently returns `bool` and discards the fetched response. Change it to return `tuple[bool, dict | None]` — the boolean result plus the raw player data. Callers (`queue_player`, `queue`) unpack this and pass the player data directly into `add_player_to_queue` / `add_player_to_vote_queue`, replacing the separate `get_player_info()` call inside those methods.

**Files:** `cogs/ranked.py` — `validate_player`, `queue_player`, `queue`, `add_player_to_queue`, `add_player_to_vote_queue`

### 2. Player info cache

Add a module-level cache:

```python
_player_cache: dict[int, tuple[dict, datetime]] = {}
PLAYER_CACHE_TTL = timedelta(minutes=5)
```

`get_player_info()` checks the cache before hitting the API. On a cache miss it fetches, stores, and returns. `validate_player()` calls `get_player_info()` instead of making its own request, so both the exists-check and display-name lookup share one fetch and one cache entry.

Cache is never explicitly invalidated — TTL expiry is sufficient. Player registration status and display names don't change mid-session.

**Files:** `cogs/ranked.py` — module level + `get_player_info`, `validate_player`

### 3. Background `update_ranked_display()`

In `add_player_to_queue`, `add_player_to_vote_queue`, and `leave_all_queues`, replace:

```python
await self.update_ranked_display()
```

with:

```python
asyncio.create_task(self.update_ranked_display())
```

The status embed update is best-effort and does not need to complete before the user receives their ephemeral confirmation.

**Files:** `cogs/ranked.py` — `add_player_to_queue`, `add_player_to_vote_queue`, `leave_all_queues`

### 4. Parallel role creation in `random()`

Replace two sequential `create_role` awaits:

```python
match.red_role = await guild.create_role(name="Red ...", ...)
match.blue_role = await guild.create_role(name="Blue ...", ...)
```

with:

```python
match.red_role, match.blue_role = await asyncio.gather(
    guild.create_role(name="Red ...", ...),
    guild.create_role(name="Blue ...", ...)
)
```

**Files:** `cogs/ranked.py` — `random`

### 5. Parallel `add_roles` in `random()`

The two loops that call `await player.add_roles(match.red_role)` for each player are sequential. Collect all coroutines first, then gather:

```python
role_tasks = []
for player in red:
    match.game.add_to_red(player)
    if not is_mock_member(player):
        role_tasks.append(player.add_roles(match.red_role))
for player in blue:
    match.game.add_to_blue(player)
    if not is_mock_member(player):
        role_tasks.append(player.add_roles(match.blue_role))
await asyncio.gather(*role_tasks, return_exceptions=True)
```

**Files:** `cogs/ranked.py` — `random`

### 6. Parallel member moves in `handle_game_end()`

Replace the nested for-loop moving members to lobby:

```python
for channel in [current_match.red_channel, current_match.blue_channel]:
    if channel:
        for member in channel.members:
            await member.move_to(lobby)
        await channel.delete()
```

with a gather across all members from both channels, followed by parallel channel deletion:

```python
move_tasks = [
    member.move_to(lobby)
    for channel in [current_match.red_channel, current_match.blue_channel]
    if channel
    for member in channel.members
]
await asyncio.gather(*move_tasks, return_exceptions=True)

delete_tasks = [
    channel.delete()
    for channel in [current_match.red_channel, current_match.blue_channel]
    if channel
]
await asyncio.gather(*delete_tasks, return_exceptions=True)
```

**Files:** `cogs/ranked.py` — `handle_game_end`

---

## Expected Impact

| Change | Savings |
|---|---|
| Eliminate duplicate API call | ~200–500 ms per queue join |
| Player cache (repeat joins) | ~200–500 ms on cache hits |
| Background display update | ~100–200 ms off critical path |
| Parallel role creation | ~100–200 ms at match start |
| Parallel add_roles (6 players) | ~500–800 ms at match start |
| Parallel member moves at game end | ~300–500 ms at game end |

---

## Out of Scope

- Optimistic queue join (skipping `validate_player` entirely) — bigger behavior change, marginal gain
- Persistent cross-session caching — overkill, in-memory TTL is sufficient
- Changes to `display_teams` ELO fetching — already uses `asyncio.gather`
