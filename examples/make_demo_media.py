"""Make README demo media from examples/Demo_vid.mp4 using the ffmpeg bundled with imageio-ffmpeg.

    python examples/make_demo_media.py [--start 5] [--gif-seconds 10]

Writes:
  examples/Demo_vid_small.mp4  ~9 MB, 960 px wide (fits GitHub's 10 MB upload limit)
  examples/demo.gif            looping preview for the README / PyPI
"""
import argparse
import os
import subprocess
import sys

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
FF = imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    print(">", " ".join(os.path.basename(a) if a == FF else a for a in args))
    r = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y"] + args)
    if r.returncode:
        sys.exit(f"ffmpeg failed ({r.returncode})")


def mb(p):
    return os.path.getsize(p) / 1e6


ap = argparse.ArgumentParser()
ap.add_argument("--src", default=os.path.join(HERE, "Demo_vid.mp4"))
ap.add_argument("--start", type=float, default=5, help="GIF start time (s)")
ap.add_argument("--gif-seconds", type=float, default=10)
ap.add_argument("--target-mb", type=float, default=9.0)
a = ap.parse_args()

if not os.path.exists(a.src):
    sys.exit(f"not found: {a.src}")

# duration -> bitrate for the target size (two-pass)
dur = float(subprocess.run([FF, "-i", a.src], capture_output=True, text=True).stderr
            .split("Duration: ")[1].split(",")[0].split(":")[-1]) + 60 * int(
    subprocess.run([FF, "-i", a.src], capture_output=True, text=True).stderr
    .split("Duration: ")[1].split(",")[0].split(":")[1])
kbps = int(a.target_mb * 8 * 1000 / dur * 0.97)
mp4 = os.path.join(HERE, "Demo_vid_small.mp4")
log = os.path.join(HERE, "ffmpeg2pass")
null = "NUL" if os.name == "nt" else "/dev/null"
vf = "scale=960:-2,fps=30"
run(["-i", a.src, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k",
     "-pass", "1", "-passlogfile", log, "-an", "-f", "mp4", null])
run(["-i", a.src, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k",
     "-pass", "2", "-passlogfile", log, "-an", "-movflags", "+faststart", mp4])
for f in os.listdir(HERE):
    if f.startswith("ffmpeg2pass"):
        os.remove(os.path.join(HERE, f))
print(f"{mp4}: {mb(mp4):.1f} MB ({dur:.0f} s @ {kbps} kb/s)")

# GIF: palette pass then render pass
gif = os.path.join(HERE, "demo.gif")
pal = os.path.join(HERE, "_palette.png")
flt = "fps=10,scale=640:-1:flags=lanczos"
run(["-ss", str(a.start), "-t", str(a.gif_seconds), "-i", a.src, "-vf", flt + ",palettegen=max_colors=128", pal])
run(["-ss", str(a.start), "-t", str(a.gif_seconds), "-i", a.src, "-i", pal,
     "-lavfi", flt + "[x];[x][1:v]paletteuse", gif])
os.remove(pal)
print(f"{gif}: {mb(gif):.1f} MB")
if mb(gif) > 10:
    print("GIF is over 10 MB: rerun with --gif-seconds 6")
