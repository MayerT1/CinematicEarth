"""Make README demo media from a flyover render using the ffmpeg bundled with imageio-ffmpeg.

    python examples/make_demo_media.py                       # uses examples/Demo_vid.mp4
    python examples/make_demo_media.py --src flyover_final.mp4 --speed 4 --gif-mb 12
    python examples/make_demo_media.py --no-mp4              # only remake the GIF

Writes:
  examples/Demo_vid_small.mp4  whole video, 960 px, ~9 MB (fits GitHub's 10 MB upload limit)
  examples/demo.gif            the WHOLE flyover sped up (default 5x), high-quality palette,
                               automatically shrunk until it is under --gif-mb
"""
import argparse
import os
import re
import subprocess
import sys

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
FF = imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    r = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y"] + args)
    if r.returncode:
        sys.exit(f"ffmpeg failed ({r.returncode}): {' '.join(args)}")


def duration(path):
    err = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def mb(p):
    return os.path.getsize(p) / 1e6


ap = argparse.ArgumentParser()
ap.add_argument("--src", default=os.path.join(HERE, "Demo_vid.mp4"))
ap.add_argument("--out-dir", default=HERE)
ap.add_argument("--target-mb", type=float, default=9.0, help="size of Demo_vid_small.mp4")
ap.add_argument("--speed", type=float, default=5.0, help="GIF speed-up of the whole video")
ap.add_argument("--gif-width", type=int, default=720)
ap.add_argument("--gif-fps", type=int, default=15)
ap.add_argument("--gif-mb", type=float, default=12.0, help="max GIF size")
ap.add_argument("--no-mp4", action="store_true", help="only (re)make the GIF")
a = ap.parse_args()

if not os.path.exists(a.src):
    sys.exit(f"not found: {a.src}")
dur = duration(a.src)
os.makedirs(a.out_dir, exist_ok=True)

# ---- small MP4 (two-pass to hit the size) ----
if not a.no_mp4:
    kbps = int(a.target_mb * 8 * 1000 / dur * 0.97)
    mp4 = os.path.join(a.out_dir, "Demo_vid_small.mp4")
    log = os.path.join(a.out_dir, "ffmpeg2pass")
    null = "NUL" if os.name == "nt" else "/dev/null"
    vf = "scale=960:-2,fps=30"
    run(["-i", a.src, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k",
         "-pass", "1", "-passlogfile", log, "-an", "-f", "mp4", null])
    run(["-i", a.src, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k",
         "-pass", "2", "-passlogfile", log, "-an", "-movflags", "+faststart", mp4])
    for f in os.listdir(a.out_dir):
        if f.startswith("ffmpeg2pass"):
            os.remove(os.path.join(a.out_dir, f))
    print(f"{mp4}: {mb(mp4):.1f} MB ({dur:.0f} s @ {kbps} kb/s)")

# ---- GIF: whole video sped up; fresh palette each try; shrink until it fits ----
gif = os.path.join(a.out_dir, "demo.gif")
pal = os.path.join(a.out_dir, "_palette.png")
width, fps = a.gif_width, a.gif_fps
for attempt in range(8):
    base = f"setpts=PTS/{a.speed},fps={fps},scale={width}:-1:flags=lanczos"
    run(["-i", a.src, "-vf", base + ",palettegen=max_colors=256:stats_mode=diff", pal])
    run(["-i", a.src, "-i", pal, "-lavfi",
         base + "[x];[x][1:v]paletteuse=dither=sierra2_4a:diff_mode=rectangle", gif])
    size = mb(gif)
    print(f"demo.gif: {dur / a.speed:.1f} s ({a.speed:g}x), {width} px, {fps} fps -> {size:.1f} MB")
    if size <= a.gif_mb:
        break
    if fps > 10:                       # drop frame rate first, then width
        fps = max(10, int(fps * 0.75))
    else:
        width = int(width * 0.85) // 2 * 2
os.remove(pal)
print(f"{gif}: {mb(gif):.1f} MB")
