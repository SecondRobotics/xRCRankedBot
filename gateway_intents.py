import discord


def build_intents():
    """Slash commands, member/role caching, and voice movement only."""
    return discord.Intents(guilds=True, members=True, voice_states=True)
