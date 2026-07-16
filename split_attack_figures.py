#!/usr/bin/env python3
"""
split_attack_figures.py
========================
Generates cleaner versions of fig2_attack_comparison.png /
per_attack_all_approaches_pxN.png by splitting attacks into two groups
based on error magnitude, so each figure uses an appropriate y-axis range.

PROBLEM: plotting all 6 approaches for wormhole (0-250m) and sybil (0-1m)
on the same y-axis range makes the sybil panel's lines collapse into a
flat smear near y=0, indistinguishable from each other.

FIX: two separate figures:
  - fig2a_catastrophic_attacks.png: wormhole, byzantine, sybil_consistent
    (y-axis spans the full 0-250m range these attacks produce)
  - fig2b_moderate_attacks.png: sybil, replay, replay_gradual, timesync
    (y-axis capped at ~1.5m, where all 6 approaches' differences are
    actually visible)

Each figure keeps the existing per-attack-panel grid layout but with a
SHARED y-axis scale appropriate to its group, AND each panel additionally
gets a y-axis ZOOM INSET for the low-error approaches (ekf_chi2_huber,
wls_tukey for non-byzantine) so their behaviour is visible even in the
catastrophic group's wide-range panels.

Usage:
    python3 split_attack_figures.py --drone px4_1
    python3 split_attack_figures.py --drone px4_1 \\
        --gt-csv ~/Dissertation/evidence/gt/gt_px4_1_wls_baseline.csv

This re-uses the data-loading logic from analyse_dissertation.py (import
it directly -- this script assumes it sits alongside analyse_dissertation.py
in ~/Dissertation/).
"""
import argparse
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# NOTE: deliberately NOT using mpl_toolkits.axes_grid1.inset_locator here.
# On systems with a mixed system/pip matplotlib install, mpl_toolkits can
# resolve to an old system copy incompatible with a newer matplotlib core
# (ImportError: cannot import name 'docstring' from 'matplotlib'). The zoom
# inset below is built with plain fig.add_axes() instead, which has no
# mpl_toolkits dependency and works with any matplotlib >= 3.x.

# Import shared config/loading from analyse_dissertation.py
sys.path.insert(0, os.path.expanduser("~/Dissertation"))
from analyse_dissertation import (
    APPROACHES, ATTACKS, load_all_results, _atk_color, no_data_panel, OUT_DIR
)

CATASTROPHIC_ATTACKS = ["wormhole", "byzantine", "sybil_consistent"]
MODERATE_ATTACKS     = [a for a in ATTACKS if a not in CATASTROPHIC_ATTACKS
                        and a != "baseline"]

# Approaches considered "low-error" for the zoom inset in catastrophic panels
ZOOM_APPROACHES = ["ekf_chi2_huber", "wls_tukey", "ransac"]


def plot_group(results, attacks, title, out_path, y_max=None, add_inset=False):
    n = len(attacks)
    cols = min(n, 3)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 5.5, rows * 4.8), squeeze=False)
    fig.suptitle(title, fontsize=13, fontweight="bold")
    ax_list = [axes[r][c] for r in range(rows) for c in range(cols)]

    panel_zoom_data = {}  # idx -> zoom_data, filled during main loop

    for idx, attack in enumerate(attacks):
        ax = ax_list[idx]
        ax.set_title(f"Attack: {attack}", fontsize=12, fontweight="bold",
                     color=_atk_color(attack))
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Error vs GT (m)")
        ax.grid(True, alpha=0.3)

        plotted = False
        zoom_data = []  # (t, err, color, ls, label) for inset

        for ap, ap_meta in APPROACHES.items():
            r = results[ap].get(attack)
            if r is None or r["err"] is None:
                continue
            t_full = r["df"]["t_sec"].values
            t = (t_full - t_full[0])[:len(r["err"])]
            ax.plot(t, r["err"], label=ap_meta["label"],
                    color=ap_meta["color"], linestyle=ap_meta["ls"],
                    linewidth=1.5, alpha=0.85)
            plotted = True
            if ap in ZOOM_APPROACHES:
                zoom_data.append((t, r["err"], ap_meta["color"], ap_meta["ls"], ap_meta["label"]))

        if not plotted:
            no_data_panel(ax)
            continue

        if y_max is not None:
            ax.set_ylim(0, y_max)

        ax.legend(fontsize=7, loc="upper right")

        if add_inset and zoom_data:
            panel_zoom_data[idx] = zoom_data

    for j in range(n, len(ax_list)):
        ax_list[j].axis("off")

    plt.tight_layout()

    # ADDED: zoom inset for low-error approaches in catastrophic panels.
    # Added AFTER tight_layout() so we use final axes positions -- adding
    # axes via fig.add_axes() before tight_layout() would have its
    # coordinates invalidated by the relayout. Built with plain
    # fig.add_axes() (no mpl_toolkits dependency, unlike inset_axes) --
    # avoids the system/pip matplotlib mpl_toolkits version conflict.
    for idx, zoom_data in panel_zoom_data.items():
        ax = ax_list[idx]
        bbox = ax.get_position()  # figure-fraction coords, post-layout
        inset_w = bbox.width * 0.40
        inset_h = bbox.height * 0.35
        inset_x = bbox.x0 + bbox.width * 0.55
        inset_y = bbox.y0 + bbox.height * 0.08
        axins = fig.add_axes([inset_x, inset_y, inset_w, inset_h])
        for t, err, color, ls, label in zoom_data:
            axins.plot(t, err, color=color, linestyle=ls, linewidth=1.2, alpha=0.9)
        axins.set_title("zoom: low-error approaches", fontsize=7)
        axins.tick_params(labelsize=6)
        axins.grid(True, alpha=0.2)
        axins.set_facecolor("white")
        axins.patch.set_alpha(0.9)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drone", default="px4_1")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    results = load_all_results(args.drone)

    plot_group(
        results, CATASTROPHIC_ATTACKS,
        f"Catastrophic Attacks - {args.drone}\n(wormhole, byzantine, sybil_consistent - "
        f"full error range, zoom inset for robust approaches)",
        os.path.join(args.out_dir, f"fig2a_catastrophic_attacks_{args.drone}.png"),
        y_max=None,  # let matplotlib auto-scale per panel (ranges differ a lot)
        add_inset=True,
    )

    plot_group(
        results, MODERATE_ATTACKS,
        f"Moderate Attacks - {args.drone}\n(sybil, replay, replay_gradual, timesync - "
        f"capped at 1.5m where approach differences are visible)",
        os.path.join(args.out_dir, f"fig2b_moderate_attacks_{args.drone}.png"),
        y_max=1.5,
        add_inset=False,
    )


if __name__ == "__main__":
    main()
