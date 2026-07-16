#!/usr/bin/env python3
"""
EKF vs WLS comparison analyser
================================
Reads /tmp/ekf_vs_wls_comparison.csv produced by ekf_attack_logger
and generates a dissertation-ready comparison figure showing:
  - WLS error vs time (per honest drone)
  - EKF error vs time (per honest drone)
  - EKF covariance trace vs time (uncertainty grows under attack)
  - Summary table: peak and mean error for both algorithms

Usage:
    python3 analyse_ekf_comparison.py
    python3 analyse_ekf_comparison.py sybil     # add attack name to title
    python3 analyse_ekf_comparison.py replay
    python3 analyse_ekf_comparison.py wormhole
"""
import sys
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG_FILE = "/tmp/ekf_vs_wls_comparison.csv"
OUT_DIR  = os.path.expanduser("~/Dissertation/evidence/figures")
os.makedirs(OUT_DIR, exist_ok=True)

DARK   = "#1a1a2e"
WLS_C  = "#e94560"    # red    — WLS
EKF_C  = "#00b4d8"    # teal   — EKF
COV_C  = "#ffd60a"    # amber  — covariance
WHITE  = "#e0e0e0"
HONEST = ["px4_1", "px4_3", "px4_4"]


def style_ax(ax, title):
    ax.set_facecolor("#0f0f1a")
    ax.set_title(title, color=WHITE, fontsize=10, fontweight="bold", pad=8)
    ax.tick_params(colors=WHITE, labelsize=8)
    ax.xaxis.label.set_color(WHITE)
    ax.yaxis.label.set_color(WHITE)
    for sp in ax.spines.values():
        sp.set_edgecolor("#333355")
    ax.grid(True, alpha=0.15, color=WHITE)


def col(df, name):
    if name not in df.columns:
        return np.zeros(len(df))
    return pd.to_numeric(df[name], errors="coerce").fillna(0).values


def main():
    attack_name = sys.argv[1].capitalize() if len(sys.argv) > 1 else "Attack"

    if not os.path.exists(LOG_FILE):
        print(f"[!] Log not found: {LOG_FILE}")
        print("    Run: ros2 run swarm_discovery ekf_attack_logger")
        return

    print(f"[EKF vs WLS] Reading {LOG_FILE}")
    df = pd.read_csv(LOG_FILE)
    t  = df["t_s"].values

    # ── Figure: 3 rows × 2 cols ──────────────────────────────────────
    fig, axes = plt.subplots(3, 2, figsize=(14, 12))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(
        f"EKF vs WLS — {attack_name} Attack\n"
        f"Ashwin Kotharamath · 2678113 · COMSM0117",
        color=WHITE, fontsize=13, fontweight="bold", y=0.98)

    for row_idx, drone in enumerate(HONEST):
        wls_err = col(df, f"{drone}_wls_err")
        ekf_err = col(df, f"{drone}_ekf_err")
        cov_tr  = col(df, f"{drone}_cov_trace")

        ax_left  = axes[row_idx, 0]
        ax_right = axes[row_idx, 1]

        # Left panel — error comparison
        ax_left.plot(t, wls_err, color=WLS_C, linewidth=1.2,
                     label="WLS error", alpha=0.9)
        ax_left.plot(t, ekf_err, color=EKF_C, linewidth=1.2,
                     label="EKF error", alpha=0.9)
        ax_left.fill_between(t, 0, wls_err, color=WLS_C, alpha=0.08)
        ax_left.fill_between(t, 0, ekf_err, color=EKF_C, alpha=0.08)
        ax_left.set_xlabel("Time (s)", color=WHITE)
        ax_left.set_ylabel("WLS/EKF Error (m)", color=WHITE)
        ax_left.legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)
        style_ax(ax_left, f"{drone} — WLS vs EKF error")

        # Right panel — covariance trace
        ax_right.plot(t, cov_tr, color=COV_C, linewidth=1.2,
                      label="EKF cov trace")
        ax_right.fill_between(t, 0, cov_tr, color=COV_C, alpha=0.12)
        ax_right.set_xlabel("Time (s)", color=WHITE)
        ax_right.set_ylabel("Covariance trace (m²)", color=WHITE)
        ax_right.legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)
        style_ax(ax_right, f"{drone} — EKF uncertainty (covariance trace)")

    # ── Summary stats ─────────────────────────────────────────────────
    print(f"\n{'='*52}")
    print(f"  EKF vs WLS — {attack_name} Attack")
    print(f"{'='*52}")
    print(f"  {'Drone':<8} {'WLS peak':>10} {'EKF peak':>10} "
          f"{'WLS mean':>10} {'EKF mean':>10} {'Cov peak':>10}")
    print(f"  {'-'*58}")

    for drone in HONEST:
        wls_err = col(df, f"{drone}_wls_err")
        ekf_err = col(df, f"{drone}_ekf_err")
        cov_tr  = col(df, f"{drone}_cov_trace")
        print(f"  {drone:<8} "
              f"{wls_err.max():>10.3f} "
              f"{ekf_err.max():>10.3f} "
              f"{wls_err.mean():>10.3f} "
              f"{ekf_err.mean():>10.3f} "
              f"{cov_tr.max():>10.4f}")

    print(f"{'='*52}")

    better = []
    worse  = []
    for drone in HONEST:
        wls_mean = col(df, f"{drone}_wls_err").mean()
        ekf_mean = col(df, f"{drone}_ekf_err").mean()
        if ekf_mean < wls_mean:
            better.append(drone)
        else:
            worse.append(drone)

    if better:
        print(f"\n  EKF BETTER than WLS on: {better}")
    if worse:
        print(f"  EKF WORSE  than WLS on: {worse}")
    print()

    out = os.path.join(OUT_DIR, f"ekf_vs_wls_{attack_name.lower()}.png")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close(fig)
    print(f"[+] Saved: {out}")


if __name__ == "__main__":
    main()
