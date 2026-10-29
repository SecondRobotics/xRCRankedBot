import unittest
from gateway_intents import build_intents


class GatewayIntentTests(unittest.TestCase):
    def test_ranked_bot_requests_only_necessary_gateway_events(self):
        intents = build_intents()
        self.assertTrue(intents.guilds)
        self.assertTrue(intents.members)
        self.assertTrue(intents.voice_states)
        self.assertFalse(intents.presences)
        self.assertFalse(intents.message_content)
        self.assertFalse(intents.messages)
