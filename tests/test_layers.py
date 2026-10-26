"""The layers: the app runs the agents of the studio, it does not hold them (scripts/check_layers.py)."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_layers", ROOT / "scripts" / "check_layers.py")
check_layers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_layers)


class Layers(unittest.TestCase):
    def test_the_app_holds_no_agent(self):
        self.assertEqual(check_layers.main(), 0)

    def test_a_direct_call_or_a_prompt_in_the_app_fails_with_its_file_and_line(self):
        for line in ('res = run(["claude", "-p", prompt])', 'argv = [exe, "-p", prompt, "--model", "sonnet"]', '"Return ONLY one JSON object, no prose\\n"',
                     'p = "You are the judge of one still ad"'):
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "app").mkdir()
                (Path(tmp) / "app" / "backend.py").write_text("x = 1\n" + line + "\n", encoding="utf-8")
                self.assertEqual(check_layers.main(Path(tmp)), 1)

    def test_an_exception_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app").mkdir()
            (Path(tmp) / "app" / "backend.py").write_text('run(["claude", "-p"])\n', encoding="utf-8")
            check_layers.EXCEPTIONS["app/backend.py"] = "test"
            try:
                self.assertEqual(check_layers.main(Path(tmp)), 0)
            finally:
                check_layers.EXCEPTIONS.clear()


if __name__ == "__main__":
    unittest.main()
