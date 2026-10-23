"""ffmpeg helpers for the inference: frames out of a video (for motion), dominant colours out of an image.

An image or a video found on the web is read from a temporary folder and deleted at once (R8): only its address,
date and what was measured survive.
"""

import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from model import today


def _need_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required (brew install ffmpeg, apt install ffmpeg)")


def _fetch(url, folder):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ix-studio brandkit)"})
    name = Path(url.split("?")[0]).name or "download"
    dest = Path(folder) / name
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    st = (d.get("streams") or [{}])[0]
    num, _, den = st.get("r_frame_rate", "0/1").partition("/")
    fps = round(float(num) / float(den or 1), 3) if float(den or 1) else None
    return {"width": st.get("width"), "height": st.get("height"), "fps": fps, "duration": float(d.get("format", {}).get("duration", 0) or 0)}


def frames(video, out_dir, scene=0.3, max_frames=24):
    """Frames at each cut (scene change), plus the cut times: the tempo of an edit is measured, not guessed."""
    _need_ffmpeg()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = None
    src = video
    if str(video).startswith(("http://", "https://")):
        tmp = tempfile.mkdtemp(prefix="ixs-video-")
        src = _fetch(video, tmp)
    try:
        info = probe(src)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-vf", f"select='eq(n,0)+gt(scene,{scene})',showinfo,scale=640:-2",
                            "-fps_mode", "vfr", "-frames:v", str(max_frames), str(out / "frame-%03d.jpg")],
                           capture_output=True, text=True)
        cuts = []
        for line in r.stderr.splitlines():
            if "pts_time:" in line:
                try:
                    cuts.append(round(float(line.split("pts_time:")[1].split()[0]), 3))
                except ValueError:
                    pass
        shots = len(cuts)
        mean = round(info["duration"] / shots, 2) if shots else None
        stills = []
        if shots < 6 and info["duration"]:
            # few hard cuts: dissolves, one long take or moving type. Sample at regular steps so the motion can be seen.
            step = max(info["duration"] / 12, 0.5)
            subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(src), "-vf", f"fps=1/{step:.3f},scale=640:-2",
                            "-frames:v", "12", str(out / "still-%03d.jpg")], capture_output=True, text=True)
            stills = sorted(p.name for p in out.glob("still-*.jpg"))
        result = {"video": str(video), "at": today(), **info, "cuts": cuts, "shots": shots, "mean_shot_s": mean,
                  "frames": sorted(p.name for p in out.glob("frame-*.jpg")), "stills_every_s": round(step, 2) if stills else None,
                  "stills": stills, "scene_threshold": scene, "kept": tmp is None}
        (out / "cuts.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _kmeans(px, k=6, rounds=12):
    cents = px[:: max(1, len(px) // k)][:k]
    for _ in range(rounds):
        groups = [[] for _ in cents]
        for p in px:
            i = min(range(len(cents)), key=lambda j: sum((a - b) ** 2 for a, b in zip(p, cents[j])))
            groups[i].append(p)
        cents = [tuple(sum(c) / len(g) for c in zip(*g)) if g else cents[i] for i, g in enumerate(groups)]
    return [(c, len(g) / len(px)) for c, g in zip(cents, groups) if g]


def sample(image, k=6):
    """Dominant colours of an image. A sampled hex drifts a few points (brand-intake's finding): it ranks below CSS."""
    _need_ffmpeg()
    tmp = None
    src = image
    if str(image).startswith(("http://", "https://")):
        tmp = tempfile.mkdtemp(prefix="ixs-img-")
        src = _fetch(image, tmp)
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", "scale=48:48:flags=area", "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
        raw = r.stdout
        px = [tuple(raw[i:i + 3]) for i in range(0, len(raw) - 2, 3)]
        out = sorted(_kmeans(px, k), key=lambda x: -x[1])
        cols = [{"hex": "#" + "".join(f"{round(v):02x}" for v in c), "share": round(s, 3)} for c, s in out]
        return {"image": str(image), "at": today(), "colours": cols, "kept": tmp is None}
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
