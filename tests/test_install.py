"""install.sh: the one command of a new Mac. No network, no claude: a fake opener, the simulated studio."""

import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Install(unittest.TestCase):
    def env(self, tmp, **extra):
        opened = Path(tmp) / "opened"
        opener = Path(tmp) / "open"
        opener.write_text(f'#!/bin/sh\necho "$1" >> "{opened}"\n')
        opener.chmod(0o755)
        env = dict(os.environ, STUDIO_BACKEND="stub", STUDIO_HOME=str(Path(tmp) / "home"), STUDIO_OPEN=str(opener),
                   STUDIO_PORT=str(free_port()))
        env.update(extra)
        return env, opened

    def test_without_python_it_says_what_is_missing_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, opened = self.env(tmp, STUDIO_PYTHON="python-absent")
            r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 1)
            self.assertIn("Python 3.10", r.stdout)
            self.assertFalse(opened.exists())

    def test_it_launches_the_studio_and_opens_it_and_a_second_run_only_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, opened = self.env(tmp)
            p = subprocess.Popen(["bash", str(SCRIPT)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for _ in range(100):
                    if opened.exists():
                        break
                    time.sleep(0.1)
                self.assertTrue(opened.exists())
                self.assertEqual(opened.read_text().strip(), f"http://127.0.0.1:{env['STUDIO_PORT']}/")
                r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0)
                self.assertIn("tourne déjà", r.stdout)
                self.assertEqual(len(opened.read_text().split()), 2)
            finally:
                p.terminate()
                p.wait(timeout=10)
                p.stdout.close()

    def test_a_failed_download_says_so_and_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "alone"
            copy.mkdir()
            (copy / "install.sh").write_text(SCRIPT.read_text())
            env, opened = self.env(tmp, STUDIO_DIR=str(Path(tmp) / "studio"), STUDIO_TARBALL="file:///absent.tar.gz")
            r = subprocess.run(["bash", str(copy / "install.sh")], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 1)
            self.assertIn("téléchargement a échoué", r.stdout)
            self.assertFalse(opened.exists())

    def test_a_downloaded_archive_is_unpacked_once_and_kept_on_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src" / "ix-studio-main" / "app"
            src.mkdir(parents=True)
            (src / "server.py").write_text("import sys\nprint('served', sys.argv[1:])\n")
            tar = Path(tmp) / "m.tar.gz"
            subprocess.run(["tar", "-czf", str(tar), "-C", str(Path(tmp) / "src"), "ix-studio-main"], check=True)
            copy = Path(tmp) / "alone"
            copy.mkdir()
            (copy / "install.sh").write_text(SCRIPT.read_text())
            studio = Path(tmp) / "studio"
            env, _ = self.env(tmp, STUDIO_DIR=str(studio), STUDIO_TARBALL=f"file://{tar}")
            r = subprocess.run(["bash", str(copy / "install.sh")], env=env, capture_output=True, text=True, timeout=30)
            self.assertIn("served", r.stdout)
            (studio / "app" / "server.py").write_text("print('mine')\n")
            r = subprocess.run(["bash", str(copy / "install.sh")], env=env, capture_output=True, text=True, timeout=30)
            self.assertIn("mine", r.stdout)
            self.assertIn("déjà dans", r.stdout)


if __name__ == "__main__":
    unittest.main()
