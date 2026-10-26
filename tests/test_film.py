"""The film command (scripts/film), alone in a terminal, on files: the storyboard in, an mp4 out. Chrome and ffmpeg run for real when the machine has
them (the test is skipped otherwise); nothing here calls claude, codex or the network (the brand has no web font)."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILM = ROOT / "scripts" / "film"
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
import compose  # noqa: E402

SHOTS = [{"seconds": 1, "visual": "texte", "text": "Le matin commence ici", "colour": "#1e2a24", "read": "Le matin commence ici."},
         {"seconds": 1, "visual": "logo", "text": "", "colour": "#f4efe6", "read": "Cabane."}]


class Film(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-film-"))
        self.piece = self.tmp / "piece"
        self.piece.mkdir()
        (self.piece / "brand.md").write_text("- name: Cabane\n- background: #F4EFE6\n- text: #1E2A24\n- accent: #C8553D\n- logo: placeholder\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self, shots, *args):
        sb = self.tmp / "storyboard.json"
        sb.write_text(json.dumps({"shots": shots}), encoding="utf-8")
        return subprocess.run([sys.executable, str(FILM), str(self.piece), str(sb), "--out", str(self.tmp / "film.mp4"), *args], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    @unittest.skipUnless(compose.find_chrome() and shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs Chrome, ffmpeg and ffprobe")
    def test_each_shot_becomes_frames_and_the_frames_a_vertical_mp4(self):
        r = self.run_cmd(SHOTS, "--fps", "4")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["video"], got["seconds"], got["frames"]), (str(self.tmp / "film.mp4"), 2.0, 8))
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", got["video"]], capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "1080,1920")

    def test_a_storyboard_that_does_not_hold_is_an_error_with_its_reason(self):
        for shots, word in (([], "list of shots"), ([{**SHOTS[0], "seconds": 0}], "shot 1"), ([{**SHOTS[0], "visual": "video"}], "shot 1"),
                            ([{**SHOTS[0], "colour": "rouge"}], "shot 1"), ([{**SHOTS[0], "text": ""}], "shot 1")):
            with self.subTest(shots=shots):
                r = self.run_cmd(shots)
                self.assertEqual((r.returncode, r.stdout), (1, ""))
                self.assertTrue(r.stderr.startswith("film: "), r.stderr)
                self.assertIn(word, r.stderr)

    def test_a_piece_without_brand_is_an_error(self):
        (self.piece / "brand.md").unlink()
        r = self.run_cmd(SHOTS)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
