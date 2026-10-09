"""Regression checks using dummy configuration and no Discord connection."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from tests.support import test_configuration


with test_configuration():
    from config import EVENT_STAFF_ID, server_games
    from game_selection import game_autocomplete, resolve_game_id
    from cogs.server import ServerActions
    from cogs.gamehangout import GameHangout


def make_interaction():
    user = Mock(spec=discord.Member)
    user.id = 100
    user.roles = [SimpleNamespace(id=EVENT_STAFF_ID)]
    return SimpleNamespace(
        user=user,
        guild=Mock(),
        channel=SimpleNamespace(id=200),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        original_response=AsyncMock(),
    )


class GameSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_game_beyond_initial_choices_is_searchable(self):
        catalog = {f"Game {i}": str(i) for i in range(100)}
        catalog["Searchable Game"] = "100"
        with patch.dict(server_games, catalog, clear=True):
            initial = await game_autocomplete(None, "")
            self.assertNotIn("Searchable Game", [choice.name for choice in initial])
            choices = await game_autocomplete(None, "  SEARCHABLE  ")
        self.assertEqual([(c.name, c.value) for c in choices], [("Searchable Game", "100")])

    async def test_substring_search(self):
        choices = await game_autocomplete(None, "buzz")
        self.assertEqual([choice.name for choice in choices], ["BioBuzz"])

    async def test_unknown_search_has_no_suggestions(self):
        self.assertEqual(await game_autocomplete(None, "not a game"), [])

    async def test_large_catalog_keeps_exact_match_visible(self):
        catalog = {f"Game {i}": str(i) for i in range(100)}
        catalog.update({f"Game 9 variant {i}": f"variant-{i}" for i in range(30)})
        # Insert the exact match last so limiting before ranking would hide it.
        catalog["Game 9"] = catalog.pop("Game 9")
        with patch.dict(server_games, catalog, clear=True):
            choices = await game_autocomplete(None, "Game 9")
            self.assertEqual(choices[0].name, "Game 9")
            self.assertIn("Game 99", [choice.name for choice in choices])

    def test_every_game_resolves_by_id_and_full_name(self):
        for name, game_id in server_games.items():
            with self.subTest(game=name):
                self.assertEqual(resolve_game_id(game_id), game_id)
                self.assertEqual(resolve_game_id(f"  {name.upper()}  "), game_id)

    def test_partial_or_unknown_values_are_rejected(self):
        for value in ("", "bio", "not a game", "999"):
            with self.subTest(value=value):
                self.assertIsNone(resolve_game_id(value))

    def test_biobuzz_has_unique_incremented_id(self):
        self.assertEqual(server_games["Override"], "23")
        self.assertEqual(server_games["BioBuzz"], "24")
        self.assertEqual(len(server_games), len(set(server_games.values())))

    async def test_launch_rejects_unknown_game_before_starting_server(self):
        cog = ServerActions.__new__(ServerActions)
        cog.start_server_process = Mock()
        interaction = make_interaction()
        await ServerActions.launch_server.callback(cog, interaction, "bad game", "test")
        cog.start_server_process.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_launch_normalizes_full_name_and_selected_id(self):
        for value in ("  bIoBuZz  ", "24"):
            with self.subTest(value=value):
                cog = ServerActions.__new__(ServerActions)
                cog.start_server_process = Mock(return_value=("test result", -1))
                interaction = make_interaction()
                await ServerActions.launch_server.callback(cog, interaction, value, "test")
                self.assertEqual(cog.start_server_process.call_args.args[0], "24")

    async def test_hangout_rejects_unknown_game_before_creating_resources(self):
        cog = GameHangout(Mock())
        interaction = make_interaction()
        with patch("cogs.gamehangout.HangoutSession") as session_class:
            await GameHangout.hangout_create.callback(cog, interaction, "bad game")
            session_class.assert_not_called()
        interaction.response.defer.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_launched_server_watch_uses_selected_game_name(self):
        cog = ServerActions.__new__(ServerActions)
        cog.start_server_process = Mock(return_value=("server started", 11115))
        cog._create_watch_message = AsyncMock()
        interaction = make_interaction()
        await ServerActions.launch_server.callback(cog, interaction, "24", "test")
        await asyncio.sleep(0)
        cog._create_watch_message.assert_awaited_once_with(11115, "BioBuzz")

    async def test_hangout_normalizes_full_name_and_selected_id(self):
        for value in ("  bIoBuZz  ", "24"):
            with self.subTest(value=value):
                cog = GameHangout(Mock())
                interaction = make_interaction()
                with patch("cogs.gamehangout.HangoutSession") as session_class:
                    session_class.return_value.create_hangout_resources = AsyncMock(return_value=True)
                    await GameHangout.hangout_create.callback(cog, interaction, value)
                    self.assertEqual(session_class.call_args.args[1], "BioBuzz")
                self.assertIn(interaction.user.id, cog.active_hangouts)


if __name__ == "__main__":
    unittest.main()
