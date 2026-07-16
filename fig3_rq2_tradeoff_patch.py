#!/usr/bin/env python3
"""
PATCH: fig3_rq2_tradeoff -- selective labeling to fix annotation clutter
==========================================================================
Drop-in replacement for fig3_rq2_tradeoff() in analyse_dissertation.py.

PROBLEM: the original annotates EVERY (approach, attack) point with a text
label. With 6 approaches x 8 attacks = 48 points, most clustered in the
0-5ms / 0-2m corner, the labels overlap into illegible mush.

FIX: only annotate points that are OUTLIERS on either axis:
  - mean_solve_ms > LABEL_SOLVE_THRESHOLD (expensive), OR
  - mean error_m > LABEL_ERROR_THRESHOLD (inaccurate)
Everything else is plotted as an unlabeled marker -- the dense cluster of
"well-behaved" combinations doesn't need individual labels; exact values
are in summary_table.csv / summary_table_with_degradation.csv.

Also adds a light "cluster" annotation pointing at the dense region so
the figure doesn't look incomplete.

USAGE: replace the body of fig3_rq2_tradeoff() in analyse_dissertation.py
with this version (same function signature, same imports already present
in that file: numpy as np, matplotlib.pyplot as plt, matplotlib.patches as
mpatches, GridSpec from matplotlib.gridspec).
"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# Tune these two thresholds to your data. Defaults chosen for the dataset
# discussed: byzantine/wormhole outliers for wls/wls_huber/wls_tukey/ekf sit
# at >4ms (wls_tukey baseline solve) is NOT what we're filtering on here --
# we're filtering on ERROR and SOLVE TIME of the (approach, attack) point
# itself. With ekf/wls baseline solve~0ms and wormhole/byzantine errors in
# the 4-95m range, ERROR_THRESHOLD=1.0 cleanly separates "interesting/bad"
# points from the well-behaved cluster (everything else is <1m).
LABEL_SOLVE_THRESHOLD = 5.0   # ms -- RANSAC baseline (~13-15ms) gets labeled
LABEL_ERROR_THRESHOLD = 1.0   # m  -- wormhole/byzantine outliers get labeled


def fig3_rq2_tradeoff(results, out_dir, APPROACHES, ATTACKS, _atk_marker):
    fig = plt.figure(figsize=(16, 7))
    fig.suptitle("RQ2: Security-Accuracy-Compute Trade-off - px4_1",
                 fontsize=13, fontweight="bold")

    gs  = GridSpec(1, 2, figure=fig, wspace=0.35)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])

    # ── Left: bar chart of mean error per approach (baseline) ────────────────
    ap_labels, mean_errs, bar_colors = [], [], []
    for ap, ap_meta in APPROACHES.items():
        r = results[ap].get("baseline")
        if r and not np.isnan(r["mean"]):
            ap_labels.append(ap_meta["label"])
            mean_errs.append(r["mean"])
            bar_colors.append(ap_meta["color"])

    if ap_labels:
        bars = ax1.bar(range(len(ap_labels)), mean_errs,
                       color=bar_colors, alpha=0.85, edgecolor="white", width=0.6)
        ax1.set_xticks(range(len(ap_labels)))
        ax1.set_xticklabels(ap_labels, rotation=30, ha="right", fontsize=9)
        ax1.set_ylabel("Mean Positioning Error (m)")
        ax1.set_title("Accuracy - Mean Error (baseline / hover)")
        for bar, val in zip(bars, mean_errs):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                     f"{val:.3f}m", ha="center", va="bottom", fontsize=9)
    ax1.grid(True, axis="y", alpha=0.3)

    # ── Right: scatter - mean error vs solve time, all attacks ──────────────
    # CHANGED: collect points first, then decide which get text labels.
    cluster_count = 0
    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap].get(attack)
            if r is None or np.isnan(r.get("mean", np.nan)) or np.isnan(r.get("mean_solve_ms", np.nan)):
                continue

            x, y = r["mean_solve_ms"], r["mean"]
            ax2.scatter(x, y,
                        color=ap_meta["color"],
                        marker=_atk_marker(attack),
                        s=110, alpha=0.85, zorder=5,
                        edgecolors="white", linewidths=0.5)

            # CHANGED: only annotate outliers
            is_outlier = (x > LABEL_SOLVE_THRESHOLD) or (y > LABEL_ERROR_THRESHOLD)
            if is_outlier:
                # Manual nudge: ransac/wormhole sits almost on top of
                # ransac/baseline at this scale -- offset it down-left
                # instead of the default up-right to avoid overlap.
                xytext = (5, 5)
                if ap == "ransac" and attack == "wormhole":
                    xytext = (-65, -15)
                ax2.annotate(f"{ap}\n({attack})", (x, y),
                             fontsize=7, xytext=xytext, textcoords="offset points",
                             bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                                       edgecolor="none", alpha=0.7))
            else:
                cluster_count += 1

    handles = []
    for ap, ap_meta in APPROACHES.items():
        handles.append(mpatches.Patch(color=ap_meta["color"], label=ap_meta["label"]))
    for atk in ATTACKS:
        handles.append(plt.Line2D([0], [0], marker=_atk_marker(atk), color="gray",
                                  linestyle="None", markersize=8,
                                  label=f"attack: {atk}"))

    ax2.set_xlabel("Mean Solve Time (ms)")
    ax2.set_ylabel("Mean Positioning Error (m)")
    ax2.set_title("Security-Compute Trade-off\n(bottom-left = best)")
    ax2.legend(handles=handles, fontsize=7, loc="upper left",
               bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax2.grid(True, alpha=0.3)

    # ADDED: single combined caption below the axes instead of in-plot
    # annotations. This avoids ALL collision with data points/labels --
    # the dense cluster sits right in the bottom-left corner where an
    # in-plot annotation would have to compete for space.
    fig.text(0.5, -0.02,
             f"Bottom-left = ideal (low error, low compute). "
             f"{cluster_count} combinations with solve<{LABEL_SOLVE_THRESHOLD:.0f}ms, "
             f"error<{LABEL_ERROR_THRESHOLD:.0f}m cluster near origin "
             f"(see summary table for exact values).",
             ha="center", va="top", fontsize=8.5, color="#555555", style="italic",
             wrap=True)

    plt.tight_layout()
    out = f"{out_dir}/fig3_rq2_tradeoff.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 3 -> {out}")
