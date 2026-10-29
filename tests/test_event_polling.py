import asyncio
import unittest

import aiohttp
from aiohttp import web

from orchestrator_client import OrchestratorClient, OrchestratorTokens, OrchestratorAPIError


class EventPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_poll_outlives_normal_request_timeout(self):
        async def events(request):
            await asyncio.sleep(0.08)
            return web.json_response({"events": []})

        app = web.Application()
        app.router.add_get("/v1/events", events)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        client = OrchestratorClient(f"http://127.0.0.1:{port}", OrchestratorTokens("test"), timeout_seconds=0.02)
        try:
            self.assertEqual(await client.get_events(wait_ms=80), [])
        finally:
            await client.close()
            await runner.cleanup()

    async def test_python310_timeout_is_reported_as_service_unavailable(self):
        class TimedOutSession:
            closed = False
            def request(self, *args, **kwargs):
                raise asyncio.TimeoutError()

        client = OrchestratorClient("http://unused", OrchestratorTokens("test"), session=TimedOutSession())
        with self.assertRaises(OrchestratorAPIError) as error:
            await client.list_servers()
        self.assertEqual(error.exception.code, "SERVICE_UNAVAILABLE")
