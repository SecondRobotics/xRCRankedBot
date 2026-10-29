import ast
from pathlib import Path
import unittest


class StagingIsolationTests(unittest.TestCase):
    def test_ranked_api_calls_do_not_hardcode_the_production_website(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ['cogs/ranked.py', 'cogs/general.py', 'cogs/userManagement.py']:
            tree = ast.parse((root / relative).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for origin in ['https://secondrobotics.org/api/', 'https://www.secondrobotics.org/api/']:
                        self.assertNotIn(origin, node.value, relative)
