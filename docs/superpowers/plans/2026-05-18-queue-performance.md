# Queue Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce latency on `/queuestandard`, `/queuevoting`, and match start/end by eliminating a redundant HTTP call, caching player info, firing display updates in the background, and parallelizing Discord API operations.

**Architecture:** All changes are in `cogs/ranked.py`. The cache is a module-level dict with TTL expiry. `validate_player` is refactored to return the fetched player data so callers don't need to re-fetch it. Sequential `await` chains are replaced with `asyncio.gather` where operations are independent.

**Tech Stack:** Python 3.10, discord.py 2.2, aiohttp, asyncio

---

## Files

- Modify: `cogs/ranked.py`

---

### Task 1: Add player info cache

Add a module-level TTL cache to `get_player_info` so repeat calls for the same player within 5 minutes skip the HTTP round-trip.

**Files:**
- Modify: `cogs/ranked.py`

- [ ] **Step 1: Add cache constants near the top of `ranked.py`, after the existing imports and before the `OrderedSet` class**

Add these two lines after line 40 (`logger = logging.getLogger('discord')`):

```python
_player_cache: Dict[int, tuple] = {}
PLAYER_CACHE_TTL = timedelta(minutes=5)
```

The `Dict` import is already present. `timedelta` is already imported from `datetime`.

- [ ] **Step 2: Rewrite `get_player_info` to check and populate the cache**

Current implementation (lines 707–714):
```python
async def get_player_info(self, player_id: int):
    url = f'https://secondrobotics.org/api/ranked/player/{player_id}'
    try:
        async with self._get_session().get(url) as x:
            return await x.json()
    except Exception as e:
        logger.error(f"Failed to fetch player info for {player_id}: {e}")
        return None
```

Replace with:
```python
async def get_player_info(self, player_id: int):
    if player_id in _player_cache:
        data, ts = _player_cache[player_id]
        if datetime.now() - ts < PLAYER_CACHE_TTL:
            return data
        del _player_cache[player_id]

    url = f'https://secondrobotics.org/api/ranked/player/{player_id}'
    try:
        async with self._get_session().get(url) as x:
            data = await x.json()
    except Exception as e:
        logger.error(f"Failed to fetch player info for {player_id}: {e}")
        return None

    _player_cache[player_id] = (data, datetime.now())
    return data
```

- [ ] **Step 3: Verify manually**

Start the bot. Call `/queuestandard` twice in quick succession (leave then rejoin). Check the logs — the second join should produce only one `GET /api/ranked/player/...` line, not two. The first join will show one request; subsequent joins within 5 minutes show zero new requests.

- [ ] **Step 4: Commit**

```
git add cogs/ranked.py
git commit -m "perf: add TTL cache to get_player_info"
```

---

### Task 2: Eliminate duplicate API call in validate_player

`validate_player` currently makes its own HTTP request and discards the result. Refactor it to call `get_player_info` instead, and return the player data so callers can pass it downstream.

**Files:**
- Modify: `cogs/ranked.py`

- [ ] **Step 1: Refactor `validate_player` to use `get_player_info` and return the data**

Current implementation (lines 594–616):
```python
async def validate_player(self, interaction: discord.Interaction, game: str) -> bool:
    url = f'https://secondrobotics.org/api/ranked/player/{interaction.user.id}'
    try:
        async with self._get_session().get(url) as x:
            res = await x.json()
    except Exception as e:
        logger.error(f"Failed to validate player {interaction.user.id}: {e}")
        await interaction.followup.send("Could not reach the ranked API. Please try again.", ephemeral=True)
        return False
    if not res["exists"]:
        await interaction.followup.send(
            f"You must register for an account at <{REGISTRATION_URL}> before you can queue.",
            ephemeral=True)
        return False

    # Check if the player is already in a game
    if await self.is_player_in_match(interaction.user):
        await interaction.followup.send(
            "You are already in a match. Please finish your current match before queuing for a new one.",
            ephemeral=True)
        return False

    return True
```

Replace with:
```python
async def validate_player(self, interaction: discord.Interaction, game: str) -> tuple:
    res = await self.get_player_info(interaction.user.id)
    if res is None:
        await interaction.followup.send("Could not reach the ranked API. Please try again.", ephemeral=True)
        return False, None
    if not res["exists"]:
        await interaction.followup.send(
            f"You must register for an account at <{REGISTRATION_URL}> before you can queue.",
            ephemeral=True)
        return False, None
    if await self.is_player_in_match(interaction.user):
        await interaction.followup.send(
            "You are already in a match. Please finish your current match before queuing for a new one.",
            ephemeral=True)
        return False, None
    return True, res
```

- [ ] **Step 2: Update `queue_player` to unpack the tuple and pass player_info to `add_player_to_queue`**

Current (lines 571–592):
```python
async def queue_player(self, interaction: discord.Interaction, game: str, from_button: bool = False):
    logger.info(f"{interaction.user.name} called /q")
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.errors.NotFound:
        return

    if not await self.validate_player(interaction, game):
        return

    qdata = game_queues[game]
    player = interaction.user

    if not self.is_valid_queue_channel(interaction, from_button):
        await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
        return

    if await self.is_player_in_queue_or_match(player, qdata):
        return

    await self.add_player_to_queue(player, qdata, interaction)
    await self.check_queue_status(qdata, interaction)
```

Replace with:
```python
async def queue_player(self, interaction: discord.Interaction, game: str, from_button: bool = False):
    logger.info(f"{interaction.user.name} called /q")
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.errors.NotFound:
        return

    valid, player_info = await self.validate_player(interaction, game)
    if not valid:
        return

    qdata = game_queues[game]
    player = interaction.user

    if not self.is_valid_queue_channel(interaction, from_button):
        await interaction.followup.send(QUEUE_CHANNEL_ERROR_MSG, ephemeral=True)
        return

    if await self.is_player_in_queue_or_match(player, qdata):
        return

    await self.add_player_to_queue(player, qdata, interaction, player_info)
    await self.check_queue_status(qdata, interaction)
```

- [ ] **Step 3: Update `add_player_to_queue` to accept and use `player_info`**

Current (lines 644–654):
```python
async def add_player_to_queue(self, player: discord.Member, qdata: Queue, interaction: discord.Interaction):
    qdata._queue.put(player)
    await self.update_ranked_display()
    res = await self.get_player_info(player.id)
    display_name = res['display_name'] if res else player.display_name
    followup = await interaction.followup.send(
        f"🟢 **{display_name}** 🟢\nadded to queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short})."
        f" *({qdata._queue.qsize()}/{qdata.alliance_size * 2})*\n"
        f"[Edit Display Name](https://secondrobotics.org/user/settings/)", ephemeral=True)

    await followup.delete(delay=60)
```

Replace with:
```python
async def add_player_to_queue(self, player: discord.Member, qdata: Queue, interaction: discord.Interaction, player_info=None):
    qdata._queue.put(player)
    await self.update_ranked_display()
    display_name = player_info['display_name'] if player_info else player.display_name
    followup = await interaction.followup.send(
        f"🟢 **{display_name}** 🟢\nadded to queue for [{qdata.full_game_name}](https://secondrobotics.org/ranked/{qdata.api_short})."
        f" *({qdata._queue.qsize()}/{qdata.alliance_size * 2})*\n"
        f"[Edit Display Name](https://secondrobotics.org/user/settings/)", ephemeral=True)

    await followup.delete(delay=60)
```

- [ ] **Step 4: Update the `queue` command (queuevoting) to unpack the tuple and pass player_info**

In the `queue` command method (around line 1144), find:
```python
        if not await self.validate_player(interaction, game):
            return

        await self.add_player_to_vote_queue(interaction.user, queue, game, interaction)
```

Replace with:
```python
        valid, player_info = await self.validate_player(interaction, game)
        if not valid:
            return

        await self.add_player_to_vote_queue(interaction.user, queue, game, interaction, player_info)
```

- [ ] **Step 5: Update `add_player_to_vote_queue` to accept and use `player_info`**

Current (lines 1164–1173):
```python
async def add_player_to_vote_queue(self, player: discord.Member, queue: Queue, preferred_game: str, interaction: discord.Interaction):
    queue._queue.put((player, preferred_game))
    res = await self.get_player_info(player.id)
    display_name = res['display_name'] if res else player.display_name
    await self.update_ranked_display()
    await interaction.followup.send(
        f"🟢 **{display_name}** 🟢\nadded to {queue.full_game_name} queue with preferred game: {preferred_game}. "
        f"({queue._queue.qsize()}/{queue.alliance_size * 2})",
        ephemeral=True
    )
```

Replace with:
```python
async def add_player_to_vote_queue(self, player: discord.Member, queue: Queue, preferred_game: str, interaction: discord.Interaction, player_info=None):
    queue._queue.put((player, preferred_game))
    display_name = player_info['display_name'] if player_info else player.display_name
    await self.update_ranked_display()
    await interaction.followup.send(
        f"🟢 **{display_name}** 🟢\nadded to {queue.full_game_name} queue with preferred game: {preferred_game}. "
        f"({queue._queue.qsize()}/{queue.alliance_size * 2})",
        ephemeral=True
    )
```

- [ ] **Step 6: Verify manually**

Start the bot. Use `/queuestandard` or `/queuevoting`. Check logs — you should see exactly one `GET /api/ranked/player/...` per queue join, not two. Confirm the green confirmation message still shows the player's display name correctly.

- [ ] **Step 7: Commit**

```
git add cogs/ranked.py
git commit -m "perf: eliminate duplicate player API call on queue join"
```

---

### Task 3: Fire-and-forget update_ranked_display on queue join/leave

`update_ranked_display()` edits the status embed and is currently awaited inline, blocking the user's response. Make it a background task in the three call sites inside `add_player_to_queue`, `add_player_to_vote_queue`, and `leave_all_queues`.

**Files:**
- Modify: `cogs/ranked.py`

- [ ] **Step 1: Change `add_player_to_queue` to background the display update**

In `add_player_to_queue` (the method you just edited in Task 2), change:
```python
    await self.update_ranked_display()
```
to:
```python
    asyncio.create_task(self.update_ranked_display())
```

- [ ] **Step 2: Change `add_player_to_vote_queue` to background the display update**

In `add_player_to_vote_queue` (also just edited in Task 2), change:
```python
    await self.update_ranked_display()
```
to:
```python
    asyncio.create_task(self.update_ranked_display())
```

- [ ] **Step 3: Change `leave_all_queues` to background the display update**

In `leave_all_queues` (around line 781), find:
```python
        await self.update_ranked_display()
        await interaction.response.send_message(message, ephemeral=True, delete_after=30)
```

Change to:
```python
        asyncio.create_task(self.update_ranked_display())
        await interaction.response.send_message(message, ephemeral=True, delete_after=30)
```

- [ ] **Step 4: Verify manually**

Queue up and leave. The ephemeral confirmation should arrive noticeably faster. The status embed in the queue status channel should still update within a moment.

- [ ] **Step 5: Commit**

```
git add cogs/ranked.py
git commit -m "perf: fire-and-forget update_ranked_display on queue join/leave"
```

---

### Task 4: Parallel role creation in random()

`create_role` for red and blue are currently sequential awaits. Gather them.

**Files:**
- Modify: `cogs/ranked.py`

- [ ] **Step 1: Replace sequential create_role calls with asyncio.gather**

In `random()` (around line 800), find:
```python
        match.red_role = await interaction.guild.create_role(
            name=f"Red {match.full_game_name}", colour=discord.Color(0xFF0000))
        match.blue_role = await interaction.guild.create_role(
            name=f"Blue {match.full_game_name}", colour=discord.Color(0x0000FF))
```

Replace with:
```python
        match.red_role, match.blue_role = await asyncio.gather(
            interaction.guild.create_role(name=f"Red {match.full_game_name}", colour=discord.Color(0xFF0000)),
            interaction.guild.create_role(name=f"Blue {match.full_game_name}", colour=discord.Color(0x0000FF))
        )
```

- [ ] **Step 2: Verify manually**

Start a match. Confirm that red and blue roles are created correctly and assigned to the right players. The match start should feel slightly snappier.

- [ ] **Step 3: Commit**

```
git add cogs/ranked.py
git commit -m "perf: parallel role creation at match start"
```

---

### Task 5: Parallel add_roles in random()

The two for-loops that assign red/blue roles to players are sequential — up to 6 Discord round-trips one after another. Collect all the coroutines and gather them.

**Files:**
- Modify: `cogs/ranked.py`

- [ ] **Step 1: Separate team assignment from role assignment in `random()`**

Find the two loops (around lines 814–827):
```python
        red = random.sample(players_list, int(match.team_size))
        for player in red:
            match.game.add_to_red(player)
            # Only add roles to real members
            if not is_mock_member(player):
                await player.add_roles(match.red_role)

        # Assign remaining players to blue team and give them the blue role
        blue = [player for player in players_list if player not in red]
        for player in blue:
            match.game.add_to_blue(player)
            # Only add roles to real members
            if not is_mock_member(player):
                await player.add_roles(match.blue_role)
```

Replace with:
```python
        red = random.sample(players_list, int(match.team_size))
        blue = [player for player in players_list if player not in red]

        for player in red:
            match.game.add_to_red(player)
        for player in blue:
            match.game.add_to_blue(player)

        role_tasks = []
        for player in red:
            if not is_mock_member(player):
                role_tasks.append(player.add_roles(match.red_role))
        for player in blue:
            if not is_mock_member(player):
                role_tasks.append(player.add_roles(match.blue_role))
        await asyncio.gather(*role_tasks, return_exceptions=True)
```

- [ ] **Step 2: Verify manually**

Start a 3v3 match. All 6 players should receive their correct roles. The time between "queue is full" and the teams embed appearing should be noticeably shorter.

- [ ] **Step 3: Commit**

```
git add cogs/ranked.py
git commit -m "perf: parallel add_roles at match start"
```

---

### Task 6: Parallel member moves in handle_game_end()

Members are currently moved to the lobby one at a time in a for-loop. Gather the moves, then delete both channels in parallel.

**Files:**
- Modify: `cogs/ranked.py`

- [ ] **Step 1: Replace the sequential member-move loop with asyncio.gather**

In `handle_game_end()` (around lines 1816–1831), find:
```python
        # Handle each channel sequentially
        for channel in [current_match.red_channel, current_match.blue_channel]:
            if channel:
                try:
                    # Move members one at a time
                    for member in channel.members:
                        try:
                            await member.move_to(lobby)
                        except Exception as e:
                            logger.error(f"Error moving member {member.name}: {e}")
                    
                    # Delete the channel after members are moved
                    await channel.delete()
                except discord.NotFound:
                    logger.warning(f"Channel {channel.name} was already deleted")
                except Exception as e:
                    logger.error(f"Error handling channel {channel.name}: {e}")
```

Replace with:
```python
        channels = [c for c in [current_match.red_channel, current_match.blue_channel] if c]

        move_tasks = [
            member.move_to(lobby)
            for channel in channels
            for member in channel.members
        ]
        await asyncio.gather(*move_tasks, return_exceptions=True)

        await asyncio.gather(
            *[channel.delete() for channel in channels],
            return_exceptions=True
        )
```

- [ ] **Step 2: Verify manually**

Complete a series (submit scores until one team wins 2). Players should be moved to the lobby and both voice channels deleted. No errors in logs.

- [ ] **Step 3: Commit**

```
git add cogs/ranked.py
git commit -m "perf: parallel member moves and channel deletion at game end"
```
