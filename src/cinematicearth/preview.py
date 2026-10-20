"""Matplotlib diagnostics: ground track, altitude, pacing, pan/tilt."""
from __future__ import annotations

import numpy as np

from .planner import visual_delta, View


def pacing_curve(plan, step=0.1):
    ts = np.arange(0, plan.duration, step)
    vs = [plan.view_at(t) for t in ts]
    sp = [visual_delta(vs[k], vs[k + 1]) / step for k in range(len(vs) - 1)]
    return ts[:-1], np.array(sp)


def plot_plan(plan, path=None, show=True):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, 2, figsize=(15, 8))
    t, cam, tgt, rot = plan.times, plan.cam, plan.target, plan.rot
    wins = plan.stop_windows()

    a = ax[0, 0]
    a.plot(cam[:, 1], cam[:, 0], lw=0.7, label="camera")
    a.plot(tgt[:, 1], tgt[:, 0], lw=0.7, alpha=0.6, label="look-at target")
    a.scatter([s.lon for s in plan.stops], [s.lat for s in plan.stops], c="r", s=14, zorder=3)
    for i, s in enumerate(plan.stops):
        a.annotate(str(i + 1), (s.lon, s.lat), fontsize=7, xytext=(3, 3), textcoords="offset points")
    a.set_title("ground track"); a.set_xlabel("lon"); a.set_ylabel("lat"); a.legend(fontsize=8)

    a = ax[0, 1]
    a.semilogy(t, cam[:, 2] - tgt[:, 2], lw=0.8)
    for w in wins:
        a.axvspan(w["t_start"], w["t_end"], color="orange", alpha=0.2)
    a.set_title("camera height above target (orange = stops)"); a.set_xlabel("s"); a.set_ylabel("m")

    a = ax[1, 0]
    ts, sp = pacing_curve(plan)
    a.plot(ts, sp, lw=0.8)
    a.axhline(plan.settings.vmax(), color="r", ls="--", lw=0.8, label=f"'{plan.settings.speed}' limit")
    for w in wins:
        a.axvspan(w["t_start"], w["t_end"], color="orange", alpha=0.2)
    a.set_title("perceived screen speed"); a.set_xlabel("s"); a.legend(fontsize=8)

    a = ax[1, 1]
    a.plot(t, rot[:, 0], lw=0.8, label="pan / heading (unwrapped)")
    a2 = a.twinx()
    a2.plot(t, rot[:, 1], lw=0.8, color="g", label="tilt")
    a.set_title("camera rotation"); a.set_xlabel("s"); a.set_ylabel("pan deg"); a2.set_ylabel("tilt deg")
    a.legend(loc="upper left", fontsize=8); a2.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=90)
    if show:
        plt.show()
    return fig
