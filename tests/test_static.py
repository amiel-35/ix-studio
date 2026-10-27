"""The interface's scripts parse: a script that does not leaves a blank page, which no test of the API sees."""

import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Scripts(unittest.TestCase):
    def test_every_script_of_the_interface_parses(self):
        for js in sorted(STATIC.glob("*.js")):
            with self.subTest(js.name):
                r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
