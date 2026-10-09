"""Dummy configuration shared by tests."""

from contextlib import contextmanager
from unittest.mock import patch


TEST_ENV = {
    "DISCORD_BOT_TOKEN": "test-token",
    "DISCORD_APPLICATION_ID": "1",
    "SRC_API_TOKEN": "test-token",
    "GUILD_ID": "1",
    "QUEUE_STATUS_CHANNEL_ID": "2",
    "QUEUE_CHANNEL_ID": "3",
    "RULES_CHANNEL_ID": "4",
    "CATEGORY_ID": "5",
    "EVENT_STAFF_ID": "6",
    "TRIAL_STAFF_ID": "7",
    "LOBBY_VC_ID": "8",
    "BOTS_ROLE_ID": "9",
    "RANKED_ADMIN_USERNAME": "test-admin",
}


@contextmanager
def test_configuration():
    # Avoid reading .env or requiring deployment credentials.
    with patch.dict("os.environ", TEST_ENV, clear=True), patch("dotenv.load_dotenv"):
        yield
