#!/usr/bin/env python3
"""
fig6_finding_f4.py
==================
Generates the Finding F4 figure:
  - Left:  mahal² over time for targeted_ramp (stays below chi2 gate)
  - Right: error comparison — all 6 approaches under targeted_ramp vs byzantine
  - Bottom: degradation factor bar chart
"""
import os, glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

METRICS   = os.path.expanduser("~/Dissertation/evidence/metrics")
FIGURES   = os.path.expanduser("~/Dissertation/evidence/figures/dissertation")
CHI2      = 7.815
HUBER_D   = 0.5
DRONE     = "px4_1"

APPROACHES = ["wls","ekf","wls_huber","wls_tukey","ransac","ekf_chi2_huber"]
LABELS     = ["WLS","EKF","WLS+Huber","WLS+Tukey","RANSAC","EKF+χ²+Huber"]
COLORS     = ["#888780","#378ADD","#EF9F27","#E24B4A","#639922","#7F77DD"]

os.makedirs(FIGURES, exist_ok=True)

fig = plt.figure(figsize=(14, 10))
fig.patch.set_facecolor("white")
gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.32)

# ── Panel A: mahal² over time from ekf_chi2_huber targeted_ramp log ──────────
ax1 = fig.add_subplot(gs[0, 0])
log = f"/tmp/byzantine_targeted_px4_2_targeted_ramp.csv"
if os.path.exists(log):
    df = pd.read_csv(log)
    ax1.plot(df["t_sec"], df["mahal_sq_estimate"], color="#2471a3", lw=1.8, label="mahal² (attack)")
    ax1.axhline(CHI2,   color="#E24B4A", lw=1.5, ls="--", label=f"χ² gate ({CHI2})")
    ax1.axhline(HUBER_D,color="#EF9F27", lw=1.2, ls=":",  label=f"Huber δ ({HUBER_D} m)")
    ax1.axvspan(0,  10, alpha=0.08, color="green",  label="warmup")
    ax1.axvspan(10, 50, alpha=0.08, color="orange", label="ramp")
    ax1.axvspan(50, 90, alpha=0.08, color="red",    label="sustained")
    ax1.fill_between(df["t_sec"], df["mahal_sq_estimate"], CHI2,
                     where=df["mahal_sq_estimate"]<CHI2,
                     alpha=0.12, color="#2471a3", label="gate not triggered")
    ax1.set_xlabel("time (s)", fontsize=11)
    ax1.set_ylabel("mahalanobis²", fontsize=11)
    ax1.set_title("A  Mahal² stays below χ² gate throughout", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9, ncol=2)
    ax1.set_ylim(bottom=0)
    peak = df["mahal_sq_estimate"].max()
    ax1.annotate(f"peak={peak:.3f}\n({peak/CHI2*100:.0f}% of gate)",
                 xy=(75, peak), fontsize=9, color="#2471a3",
                 arrowprops=dict(arrowstyle="->", color="#2471a3"))
else:
    ax1.text(0.5,0.5,"Run the targeted_ramp attack first\nto generate /tmp/byzantine_targeted_px4_2_targeted_ramp.csv",
             ha="center",va="center",transform=ax1.transAxes,fontsize=10,color="gray")
    ax1.set_title("A  Mahal² over time (data not yet collected)", fontsize=12, fontweight="bold")

# ── Panel B: mean error per approach under targeted_ramp vs byzantine ─────────
ax2 = fig.add_subplot(gs[0, 1])

def mean_err(app, attack):
    f1 = os.path.join(METRICS, f"{app}_{DRONE}_{attack}.csv")
    f2 = os.path.join(METRICS, f"{app}_px4_1_{attack}.csv")
    f3 = os.path.join(METRICS, f"{app}_{DRONE}.csv") if attack=="baseline" else None
    for candidate in [f1, f2, f3]:
        if candidate and os.path.exists(candidate):
            df = pd.read_csv(candidate)
            if {"x","y","z"}.issubset(df.columns):
                return np.sqrt(df.x**2 + df.y**2 + df.z**2).mean()
    return np.nan

tr_errors  = [mean_err(app, "targeted_ramp") for app in APPROACHES]
byz_errors = [mean_err(app, "byzantine")     for app in APPROACHES]

x = np.arange(len(APPROACHES))
w = 0.35
bars1 = ax2.bar(x-w/2, tr_errors,  w, label="targeted ramp (F4)", color="#2471a3", alpha=0.85)
bars2 = ax2.bar(x+w/2, byz_errors, w, label="byzantine (standard)", color="#16a085", alpha=0.85)
ax2.set_xticks(x); ax2.set_xticklabels(LABELS, rotation=30, ha="right", fontsize=9)
ax2.set_ylabel("mean error (m)", fontsize=11)
ax2.set_title("B  Targeted ramp vs standard Byzantine", fontsize=12, fontweight="bold")
ax2.legend(fontsize=9)
for bar in bars1:
    h = bar.get_height()
    if not np.isnan(h):
        ax2.text(bar.get_x()+bar.get_width()/2, h+0.01, f"{h:.3f}",
                 ha="center", va="bottom", fontsize=8, color="#2471a3")
for bar in bars2:
    h = bar.get_height()
    if not np.isnan(h):
        ax2.text(bar.get_x()+bar.get_width()/2, h+0.01, f"{h:.3f}",
                 ha="center", va="bottom", fontsize=8, color="#16a085")

# ── Panel C: degradation factor — targeted_ramp / baseline ───────────────────
ax3 = fig.add_subplot(gs[1, 0])
base_errors  = [mean_err(app, "baseline") for app in APPROACHES]
degradation  = []
for i, app in enumerate(APPROACHES):
    b  = base_errors[i]
    tr = tr_errors[i]
    if b and not np.isnan(b) and not np.isnan(tr) and b > 0:
        degradation.append(round(tr/b, 3))
    else:
        degradation.append(np.nan)

bars = ax3.bar(LABELS, degradation, color=COLORS, alpha=0.85, edgecolor="white")
ax3.axhline(1.0, color="gray", lw=1, ls="--", label="baseline (1×)")
ax3.set_ylabel("degradation factor (×)", fontsize=11)
ax3.set_title("C  Degradation factor under targeted ramp", fontsize=12, fontweight="bold")
ax3.set_xticklabels(LABELS, rotation=30, ha="right", fontsize=9)
ax3.legend(fontsize=9)
for bar, val in zip(bars, degradation):
    if not np.isnan(val):
        ax3.text(bar.get_x()+bar.get_width()/2, val+0.1, f"{val:.1f}×",
                 ha="center", va="bottom", fontsize=9)

# ── Panel D: time-series error — ekf_chi2_huber under targeted_ramp ──────────
ax4 = fig.add_subplot(gs[1, 1])
for app, label, color in zip(APPROACHES, LABELS, COLORS):
    f = os.path.join(METRICS, f"{app}_{DRONE}_targeted_ramp.csv")
    if not os.path.exists(f): continue
    df = pd.read_csv(f)
    if not {"t_sec","x","y","z"}.issubset(df.columns): continue
    err = np.sqrt(df.x**2+df.y**2+df.z**2)
    ax4.plot(df.t_sec, err, label=label, color=color, lw=1.5, alpha=0.85)

ax4.axvspan(0,  10, alpha=0.06, color="green")
ax4.axvspan(10, 50, alpha=0.06, color="orange")
ax4.axvspan(50, 90, alpha=0.06, color="red")
ax4.set_xlabel("time (s)", fontsize=11)
ax4.set_ylabel("localisation error (m)", fontsize=11)
ax4.set_title("D  Error time-series — all approaches", fontsize=12, fontweight="bold")
ax4.legend(fontsize=9, ncol=2)
ax4.text(2,  ax4.get_ylim()[1]*0.92 if ax4.get_ylim()[1]>0 else 0.5, "warmup", fontsize=8, color="green")
ax4.text(18, ax4.get_ylim()[1]*0.92 if ax4.get_ylim()[1]>0 else 0.5, "ramp",   fontsize=8, color="orange")
ax4.text(55, ax4.get_ylim()[1]*0.92 if ax4.get_ylim()[1]>0 else 0.5, "sustained",fontsize=8,color="red")

fig.suptitle("Finding F4 — Targeted EKF+χ²+Huber Exploit\n"
             "Max bias = 0.307 m < Huber δ (0.5 m) | Peak mahal² = 3.764 < χ² gate (7.815)",
             fontsize=13, fontweight="bold", y=1.01)

out = os.path.join(FIGURES, "fig6_finding_f4.png")
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
print(f"Saved → {out}")
plt.close()
