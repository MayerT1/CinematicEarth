"""Burn animated annotations into an Earth Studio render.

The planner aims the camera exactly at each stop, so during a stop the city
is at screen centre: the pin is drawn there, with a leader line and a card.

Requires the ``video`` extra: ``pip install CinematicEarth[video]`` (opencv,
pillow) and an ``ffmpeg`` binary on PATH.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np


@dataclass
class OverlayStyle:
    accent: str = "#FFB000"
    card_alpha: float = 0.72
    show_coords: bool = True
    show_counter: bool = True
    attribution: str = "Google Earth"       # required by Earth Studio terms; "" if already burned in
    font: Optional[str] = None              # path to .ttf (default DejaVu Sans / Arial)
    fade_in: float = 0.6                    # s after stop start before card appears
    notes: Dict[str, str] = field(default_factory=dict)


def _deps():
    try:
        import cv2  # noqa
        from PIL import Image, ImageDraw, ImageFont  # noqa
    except ImportError as e:
        raise ImportError("overlay needs: pip install 'CinematicEarth[video]'") from e
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")


def _font_path(style, bold):
    if style.font:
        return style.font
    cands = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
             "arialbd.ttf" if bold else "arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
             "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf"]
    try:
        p = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold" if bold else "DejaVu Sans"],
                           capture_output=True, text=True).stdout.strip()
        if p:
            cands.insert(0, p)
    except Exception:
        pass
    return cands


class Annotator:
    def __init__(self, stops, H, style: OverlayStyle, cuts=()):
        from PIL import ImageFont
        self.stops, self.H, self.style, self.s = stops, H, style, H / 1080
        self.cuts = list(cuts)
        self._fonts = {}
        self._IF = ImageFont
        h = style.accent.lstrip("#")
        self.acc = tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))
        self.cards = [self._card(i) for i in range(len(stops))]
        self.attrib = self._block([(style.attribution, self.font(False, 20), (240, 240, 240))], 0.0, False) \
            if style.attribution else None

    def font(self, bold, size):
        key = (bold, int(size * self.s))
        if key not in self._fonts:
            cands = _font_path(self.style, bold)
            for c in ([cands] if isinstance(cands, str) else cands):
                try:
                    self._fonts[key] = self._IF.truetype(c, key[1])
                    break
                except Exception:
                    continue
            else:
                self._fonts[key] = self._IF.load_default()
        return self._fonts[key]

    def _block(self, lines, bg_alpha, bar=True):
        from PIL import Image, ImageDraw
        s = self.s
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        pad, gap, bw = int(22 * s), int(8 * s), int(6 * s) if bar else 0
        boxes = [probe.textbbox((0, 0), t, font=f) for t, f, _ in lines]
        w = max(b[2] - b[0] for b in boxes) + 2 * pad + bw
        h = sum(b[3] - b[1] for b in boxes) + gap * (len(lines) - 1) + 2 * pad
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(10 * s), fill=(12, 16, 22, int(255 * bg_alpha)))
        if bar:
            d.rectangle([0, int(4 * s), bw, h - 1 - int(4 * s)], fill=self.acc + (255,))
        y = pad
        for (t, f, c), b in zip(lines, boxes):
            d.text((pad + bw - b[0], y - b[1]), t, font=f, fill=tuple(c) + (255,))
            y += (b[3] - b[1]) + gap
        return np.asarray(im)[..., [2, 1, 0, 3]].copy()

    def _card(self, i):
        st = self.stops[i]
        title = st.get("title") or st["name"]
        city, _, region = title.partition(",")
        L = []
        if self.style.show_counter:
            L.append((f"{i + 1:02d} / {len(self.stops):02d}", self.font(True, 19), self.acc))
        L.append((city.strip(), self.font(True, 46), (255, 255, 255)))
        if region.strip():
            L.append((region.strip(), self.font(False, 23), (225, 225, 225)))
        if self.style.show_coords:
            la, lo = st["lat"], st["lon"]
            L.append((f"{abs(la):.3f}°{'N' if la >= 0 else 'S'}   {abs(lo):.3f}°{'E' if lo >= 0 else 'W'}",
                      self.font(False, 19), (175, 185, 195)))
        note = self.style.notes.get(st["name"]) or st.get("note")
        if note:
            L.append((note, self.font(True, 21), self.acc))
        return self._block(L, self.style.card_alpha)

    @staticmethod
    def _blend(frame, rgba, x, y, op):
        if op <= 0:
            return
        h, w = rgba.shape[:2]
        H, W = frame.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        sub = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
        a = sub[..., 3:4] / 255 * op
        roi = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = (roi * (1 - a) + sub[..., :3] * a).astype(np.uint8)

    @staticmethod
    def _blend_mask(frame, mask, x0, y0, bgr, op):
        H, W = frame.shape[:2]
        h, w = mask.shape
        xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
        m = mask[ya - y0:yb - y0, xa - x0:xb - x0]
        a = (m.astype(np.float32) / 255 * op)[..., None]
        roi = frame[ya:yb, xa:xb].astype(np.float32)
        frame[ya:yb, xa:xb] = (roi * (1 - a) + np.array(bgr, np.float32) * a).astype(np.uint8)

    def _pin(self, frame, tau, op):
        import cv2
        s = self.s
        H, W = frame.shape[:2]
        cx, cy = W // 2, H // 2
        ease = lambda x: 1 - (1 - min(1, max(0, x))) ** 3
        x0, y0 = cx - int(130 * s), cy - int(190 * s)
        mw = np.zeros((int(330 * s), int(330 * s)), np.uint8)
        ma = mw.copy()
        c = (cx - x0, cy - y0)
        lw = max(1, int(round(2.5 * s)))
        for k in range(2):
            ph = ((tau + k * 0.8) % 1.6) / 1.6
            cv2.circle(ma, c, int((12 + 95 * ph) * s), int(230 * (1 - ph)), lw, cv2.LINE_AA)
        R = int(24 * s)
        cv2.ellipse(mw, c, (R, R), -90, 0, 360 * ease(tau / 0.6), 255, lw, cv2.LINE_AA)
        cv2.circle(mw, c, int(8 * s), 255, -1, cv2.LINE_AA)
        cv2.circle(ma, c, int(5.5 * s), 255, -1, cv2.LINE_AA)
        cv2.circle(mw, c, int(5.5 * s), 0, -1, cv2.LINE_AA)
        p0 = (c[0] + int(R * 0.707), c[1] - int(R * 0.707))
        p1 = (c[0] + int(115 * s), c[1] - int(115 * s))
        p2 = (p1[0] + int(55 * s), p1[1])
        g = ease((tau - 0.35) / 0.5)
        if g > 0:
            q = min(1, g / 0.7)
            cv2.line(mw, p0, (int(p0[0] + (p1[0] - p0[0]) * q), int(p0[1] + (p1[1] - p0[1]) * q)), 255, lw, cv2.LINE_AA)
            if g > 0.7:
                q2 = (g - 0.7) / 0.3
                cv2.line(mw, p1, (int(p1[0] + (p2[0] - p1[0]) * q2), p1[1]), 255, lw, cv2.LINE_AA)
        self._blend_mask(frame, ma, x0, y0, self.acc[::-1], op)
        self._blend_mask(frame, mw, x0, y0, (255, 255, 255), op)
        return x0 + p2[0], y0 + p2[1]

    def __call__(self, frame, t):
        ease = lambda x: 1 - (1 - min(1, max(0, x))) ** 3
        for c in self.cuts:                       # dip to black around hard cuts
            if abs(t - c) < 0.45:
                k = max(0.0, 1 - abs(t - c) / 0.45)
                frame[:] = (frame.astype(np.float32) * (1 - k)).astype(np.uint8)
        for i, st in enumerate(self.stops):
            a, b = st["t_start"], st["t_end"]
            if a <= t <= b:
                tau, D = t - a, b - a
                op = min(1, max(0, tau / 0.25)) * min(1, max(0, (D - tau) / 0.5))
                ex, ey = self._pin(frame, tau, op)
                card = self.cards[i]
                ci = ease((tau - self.style.fade_in - 0.15) / 0.45)
                self._blend(frame, card, ex + int(10 * self.s) + int((1 - ci) * 30 * self.s),
                            ey - card.shape[0] // 2, op * ci)
                break
        if self.attrib is not None:
            H, W = frame.shape[:2]
            self._blend(frame, self.attrib, W - self.attrib.shape[1] - int(20 * self.s),
                        H - self.attrib.shape[0] - int(16 * self.s), 1.0)
        return frame


def _plan_dict(plan):
    if isinstance(plan, (str, os.PathLike)):
        with open(plan) as f:
            return json.load(f)
    if hasattr(plan, "to_json"):
        return plan.to_json()
    return plan


def preview_frame(plan, t, width=1920, height=1080, style: Optional[OverlayStyle] = None):
    """Annotation over a grey frame at time t (BGR array)."""
    _deps()
    pd = _plan_dict(plan)
    fr = np.full((height, width, 3), 90, np.uint8)
    return Annotator(pd["stops"], height, style or OverlayStyle())(fr, t)


def annotate_video(render, plan, out="flyover_final.mp4", style: Optional[OverlayStyle] = None,
                   crf=18, progress=True):
    """render: Earth Studio .zip of JPEGs, a folder of frames, or a video file."""
    _deps()
    import cv2
    style = style or OverlayStyle()
    pd = _plan_dict(plan)
    fps, duration = pd["settings"]["fps"], pd["duration"]
    tmp = None
    if os.path.isdir(render) or str(render).lower().endswith(".zip"):
        if str(render).lower().endswith(".zip"):
            tmp = tempfile.mkdtemp(prefix="ce_")
            zipfile.ZipFile(render).extractall(tmp)
            root = tmp
        else:
            root = render
        frames = sorted(glob.glob(os.path.join(root, "**", "*.jp*g"), recursive=True) +
                        glob.glob(os.path.join(root, "**", "*.png"), recursive=True))
        if not frames:
            raise ValueError("no frames found")
        H, W = cv2.imread(frames[0]).shape[:2]
        n = len(frames)
        reader = (cv2.imread(p) for p in frames)
    else:
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                               "-show_entries", "stream=width,height,nb_read_packets", "-of", "csv=p=0", render],
                              capture_output=True, text=True).stdout.strip().split(",")
        W, H, n = int(info[0]), int(info[1]), int(info[2])
        dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", render, "-f", "rawvideo",
                                "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)

        def gen():
            while True:
                b = dec.stdout.read(W * H * 3)
                if len(b) < W * H * 3:
                    return
                yield np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()
        reader = gen()
    dt = duration / n if abs(n - round(duration * fps)) > 2 else 1 / fps
    ann = Annotator(pd["stops"], H, style, pd.get("cuts", []))
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-crf", str(crf), "-preset", "medium", "-movflags", "+faststart", out],
                           stdin=subprocess.PIPE)
    it = reader
    if progress:
        try:
            from tqdm.auto import tqdm
            it = tqdm(reader, total=n, desc="annotate")
        except ImportError:
            pass
    for k, fr in enumerate(it):
        enc.stdin.write(ann(fr, k * dt).tobytes())
    enc.stdin.close()
    enc.wait()
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return out
