"""Shared game search and validation for server and hangout commands."""

from typing import List, Optional

import discord
from discord import app_commands

from config import server_games


async def game_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    query = current.strip().casefold()
    choices = [
        app_commands.Choice(name=name, value=game_id)
        for name, game_id in server_games.items()
        if query in name.casefold()
    ]
    # Keep exact and prefix matches visible even for broad searches.
    choices.sort(key=lambda choice: (
        choice.name.casefold() != query,
        not choice.name.casefold().startswith(query),
    ))
    return choices[:25]


def resolve_game_id(value: str) -> Optional[str]:
    """Accept a selected ID or a complete game name typed without selecting."""
    value = value.strip()
    return next(
        (game_id for name, game_id in server_games.items()
         if value == game_id or value.casefold() == name.casefold()),
        None,
    )
