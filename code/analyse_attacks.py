#!/usr/bin/env python3
"""
Attack metrics analyser
Reads CSV logs from attack nodes and generates dissertation-ready plots.
Usage:
    python3 analyse_attacks.py sybil
    python3 analyse_attacks.py replay
    python3 analyse_attacks.py wormhole
    python3 analyse_attacks.py all
"""
import sys
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = os.path.expanduser("~/Dissertation/evidence/figures")
os.makedirs(OUT_DIR, exist_ok=True)

LOG_FILES = {
    "sybil":    "/tmp/sybil_registry_attack_metrics.csv",
    "replay":   "/tmp/replay_attack_metrics.csv",
    "wormhole": "/tmp/wormhole_attack_metrics.csv",
}

DARK   = "#1a1a2e"
ACCENT = "#e94560"
TEAL   = "#00b4d8"
AMBER  = "#ffd60a"
WHITE  = "#e0e0e0"


def style_ax(ax, title):
    ax.set_facecolor("#0f0f1a")
    ax.set_title(title, color=WHITE, fontsize=10, fontweight="bold", pad=8)
    ax.tick_params(colors=WHITE, labelsize=8)
    ax.xaxis.label.set_color(WHITE)
    ax.yaxis.label.set_color(WHITE)
    for sp in ax.spines.values():
        sp.set_edgecolor("#333355")
    ax.grid(True, alpha=0.15, color=WHITE)


def new_fig(title):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(f"{title}\nAshwin Kotharamath · 2678113 · COMSM0117",
                 color=WHITE, fontsize=13, fontweight="bold", y=0.98)
    return fig, axes


def error_panel(ax, t, err, label, color=ACCENT):
    ax.plot(t, err, color=color, linewidth=1.5, label=label)
    ax.fill_between(t, 0, err, color=color, alpha=0.15)
    peak   = err.max()
    peak_t = t[err.argmax()]
    ax.axhline(peak, color=AMBER, linewidth=0.8, linestyle="--", alpha=0.7)
    ax.annotate(f"Peak: {peak:.3f} m",
                xy=(peak_t, peak), xytext=(peak_t + 2, peak * 0.85),
                color=AMBER, fontsize=8,
                arrowprops=dict(arrowstyle="->", color=AMBER, lw=0.8))
    ax.set_xlabel("Time (s)", color=WHITE)
    ax.set_ylabel("WLS Error (m)", color=WHITE)
    ax.legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)


def summary_panel(ax, stats):
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    lines = [f"{'ATTACK SUMMARY':^38}", "─" * 38]
    for k, v in stats.items():
        lines.append(f"  {k:<26} {v}")
    ax.text(0.05, 0.95, "\n".join(lines),
            transform=ax.transAxes, fontsize=9,
            verticalalignment="top", fontfamily="monospace",
            color=WHITE,
            bbox=dict(facecolor="#0f0f1a", alpha=0.8,
                      edgecolor=ACCENT, boxstyle="round,pad=0.5"))


def analyse_sybil(path):
    print(f"[SYBIL] Reading {path}")
    df  = pd.read_csv(path)
    t   = df["t_s"].values
    e1  = pd.to_numeric(df.get("px4_1_error_m",  pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    e3  = pd.to_numeric(df.get("px4_3_error_m",  pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    ng  = pd.to_numeric(df.get("num_ghosts",      pd.Series([0]*len(df))), errors="coerce").fillna(0).values

    fig, axes = new_fig("Attack: Sybil / Ghost Drone Injection")

    ax = axes[0, 0]
    error_panel(ax, t, e1, "px4_1 WLS error")
    style_ax(ax, "px4_1 (honest) — localisation error vs time")

    ax = axes[0, 1]
    error_panel(ax, t, e3, "px4_3 WLS error", color=TEAL)
    style_ax(ax, "px4_3 (honest) — localisation error vs time")

    ax = axes[1, 0]
    ax.plot(t, e1, color=ACCENT, linewidth=1.2, label="px4_1 error")
    ax.plot(t, e3, color=TEAL,   linewidth=1.2, label="px4_3 error")
    ax.set_xlabel("Time (s)", color=WHITE)
    ax.set_ylabel("WLS Error (m)", color=WHITE)
    ax.legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)
    style_ax(ax, "Combined error — both honest drones")

    stats = {
        "Duration (s)":         f"{t[-1]:.1f}",
        "Num ghost drones":     f"{int(ng.max())}",
        "Peak px4_1 error (m)": f"{e1.max():.4f}",
        "Peak px4_3 error (m)": f"{e3.max():.4f}",
        "Mean px4_1 error (m)": f"{e1.mean():.4f}",
        "Mean px4_3 error (m)": f"{e3.mean():.4f}",
        "STRIDE":               "Spoofing · Tampering",
        "Reference":            "Newsome et al. IPSN 2004",
    }
    summary_panel(axes[1, 1], stats)
    style_ax(axes[1, 1], "Summary")

    out = os.path.join(OUT_DIR, "sybil_attack.png")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close(fig)
    print(f"[+] Saved: {out}")

    print(f"\n--- Sybil Attack Summary ---")
    print(f"Peak px4_1 error : {e1.max():.4f} m")
    print(f"Peak px4_3 error : {e3.max():.4f} m")
    print(f"Mean px4_1 error : {e1.mean():.4f} m")
    print(f"Duration         : {t[-1]:.1f} s")


def main():
    target  = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    targets = list(LOG_FILES.keys()) if target == "all" else [target]

    for name in targets:
        path = LOG_FILES.get(name)
        if not path:
            print(f"Unknown: {name}"); continue
        if not os.path.exists(path):
            print(f"[!] Log not found: {path} — run the attack first"); continue
        if name == "sybil":
            analyse_sybil(path)

    print(f"\n[+] Figures saved to {OUT_DIR}/")


if __name__ == "__main__":
    main()
