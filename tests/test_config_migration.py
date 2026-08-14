import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config


class ConfigMigrationTest(unittest.TestCase):
    def test_v2_adds_prompt_without_overwriting_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "actions": [
                            {"id": "grammar", "system": "custom grammar"},
                            {"id": "custom-action", "builtin": False},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"QUICKAI_CONFIG": str(path)}):
                config._cache = None
                loaded = config.load()

            actions = {action["id"]: action for action in loaded["actions"]}
            self.assertEqual(loaded["version"], 2)
            self.assertEqual(actions["grammar"]["system"], "custom grammar")
            self.assertIn("custom-action", actions)
            self.assertEqual(actions["prompt"]["icon"], "AP")
            self.assertEqual(json.loads(path.read_text())["version"], 2)


if __name__ == "__main__":
    unittest.main()
