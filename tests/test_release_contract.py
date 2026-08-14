import unittest
from unittest.mock import AsyncMock, patch

from app.actions import DEFAULT_ACTIONS
from app.main import api_health, app


class ReleaseContractTest(unittest.TestCase):
    def test_actions_have_unique_ids_and_plain_markers(self):
        ids = [action["id"] for action in DEFAULT_ACTIONS]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(action["icon"].isascii() for action in DEFAULT_ACTIONS))
        self.assertTrue(all(1 <= len(action["icon"]) <= 2 for action in DEFAULT_ACTIONS))

    def test_agent_prompt_and_draft_defaults_route_are_shipped(self):
        prompt = next(action for action in DEFAULT_ACTIONS if action["id"] == "prompt")
        routes = {route.path for route in app.routes}

        self.assertIn("# Objective", prompt["system"])
        self.assertIn("/api/actions/defaults", routes)


class HealthContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_health_calls_the_backend_llm(self):
        config = {"base_url": "http://127.0.0.1:8000", "model": "llama"}
        health = {"ok": True, "models": ["llama"], "count": 1}

        with patch("app.main.cfgmod.load", return_value=config), patch(
            "app.main.upstream.health", new=AsyncMock(return_value=health)
        ):
            response = await api_health()

        self.assertEqual(response["llm"], health)
        self.assertEqual(
            set(response), {"app", "version", "base_url", "model", "llm"}
        )


if __name__ == "__main__":
    unittest.main()
