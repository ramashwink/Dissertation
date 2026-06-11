#!/usr/bin/env python3
"""
analyse_dissertation.py
========================
Complete dissertation analysis — reads all available metrics CSVs,
computes error against ground truth, and produces publication-ready figures.

Works with whatever data exists — partial runs, missing attacks, missing
approaches — empty panels show "no data yet" rather than crashing.

Usage:
    python3 ~/Dissertation/analyse_dissertation.py

    # Custom GT file:
    python3 ~/Dissertation/analyse_dissertation.py --gt-csv ~/Dissertation/evidence/gt/gt_px4_1.csv

    # Single drone only:
    python3 ~/Dissertation/analyse_dissertation.py --drone px4_1

Output figures (~/Dissertation/evidence/figures/dissertation/):
    fig1_baseline_comparison.png    — 6-panel, all approaches at baseline
    fig2_attack_comparison.png      — per-attack 4-panel, all approaches overlaid
    fig3_rq2_tradeoff.png           — RQ2 trade-off: error vs compute cost
    fig4_solve_latency.png          — solve time over time (baseline)
    fig5_attack_degradation.png     — error increase under each attack vs baseline
    summary_table.csv               — full numeric results table
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# ── Config ────────────────────────────────────────────────────────────────────
METRICS_DIR = os.path.expanduser("~/Dissertation/evidence/metrics")
GT_DIR      = os.path.expanduser("~/Dissertation/evidence/gt")
OUT_DIR     = os.path.expanduser("~/Dissertation/evidence/figures/dissertation")

APPROACHES = {
    "wls":            {"label": "WLS",               "color": "#e74c3c", "ls": "-",  "marker": "o"},
    "ekf":            {"label": "EKF",               "color": "#e67e22", "ls": "--", "marker": "s"},
    "wls_huber":      {"label": "WLS + Huber",       "color": "#3498db", "ls": "-",  "marker": "^"},
    "wls_tukey":      {"label": "WLS + Tukey",       "color": "#9b59b6", "ls": "--", "marker": "D"},
    "ransac":         {"label": "RANSAC",            "color": "#1abc9c", "ls": "-.", "marker": "v"},
    "ekf_chi2_huber": {"label": "EKF+χ²+Huber ★",   "color": "#27ae60", "ls": "-",  "marker": "*"},
}

ATTACKS = ["baseline", "sybil", "replay", "wormhole"]
ATTACK_COLORS = {
    "baseline": "#7f8c8d",
    "sybil":    "#e74c3c",
    "replay":   "#e67e22",
    "wormhole": "#8e44ad",
}

DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "font.size":       11,
    "axes.titlesize":  12,
    "axes.labelsize":  11,
    "legend.fontsize": 9,
    "figure.dpi":      150,
})
# ─────────────────────────────────────────────────────────────────────────────


def load_csv(path):
    if not path or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        return df if len(df) > 2 else None
    except Exception:
        return None


def find_metrics_csv(approach, attack, drone):
    """Find metrics CSV for a given approach/attack/drone combination."""
    if attack == "baseline":
        candidates = [
            f"{approach}_{drone}.csv",
            f"{approach}_{drone}_baseline.csv",
        ]
    else:
        candidates = [
            f"{approach}_{drone}_{attack}.csv",
        ]
    for name in candidates:
        p = os.path.join(METRICS_DIR, name)
        if os.path.exists(p):
            return p
    return None


def find_gt_csv(drone, approach=None, attack=None):
    """Find the best available GT CSV for a drone."""
    candidates = []
    if approach and attack:
        candidates.append(os.path.join(GT_DIR, f"gt_{drone}_{approach}_{attack}.csv"))
    candidates += [
        os.path.join(GT_DIR, f"gt_{drone}_wls_baseline.csv"),
        os.path.join(GT_DIR, f"gt_{drone}.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def compute_error(df, gt_df):
    """Euclidean error vs ground truth using relative timestamps.
    Relative time (seconds since first row) allows CSVs from different
    sessions to be compared — GT hover position is valid across runs.
    """
    if gt_df is None:
        return None
    if "t_sec" not in df.columns:
        return None
    t_met = df["t_sec"].values - df["t_sec"].values[0]
    t_gt  = gt_df["t_sec"].values - gt_df["t_sec"].values[0]
    max_t = min(t_met[-1], t_gt[-1])
    mask  = t_met <= max_t
    t_met = t_met[mask]
    gt_x  = np.interp(t_met, t_gt, gt_df["x"].values)
    gt_y  = np.interp(t_met, t_gt, gt_df["y"].values)
    gt_z  = np.interp(t_met, t_gt, gt_df["z"].values)
    return np.sqrt((df["x"].values[mask] - gt_x)**2 +
                   (df["y"].values[mask] - gt_y)**2 +
                   (df["z"].values[mask] - gt_z)**2)


def err_stats(err):
    if err is None or len(err) == 0:
        return dict(mean=np.nan, peak=np.nan, rmse=np.nan, std=np.nan)
    return dict(
        mean = float(np.mean(err)),
        peak = float(np.max(err)),
        rmse = float(np.sqrt(np.mean(err**2))),
        std  = float(np.std(err)),
    )


def load_all_results(primary_drone):
    """Load all metrics and compute error for the primary drone."""
    gt_cache = {}

    def get_gt(approach, attack):
        key = f"{approach}_{attack}"
        if key not in gt_cache:
            gt_cache[key] = load_csv(find_gt_csv(primary_drone, approach, attack))
        return gt_cache[key]

    results = {}
    for ap in APPROACHES:
        results[ap] = {}
        for attack in ATTACKS:
            path = find_metrics_csv(ap, attack, primary_drone)
            df   = load_csv(path)
            if df is None:
                results[ap][attack] = None
                continue
            if "t_sec" not in df.columns and "timestamp" in df.columns:
                df = df.rename(columns={"timestamp": "t_sec"})

            if "t_sec" not in df.columns and "timestamp" in df.columns:
                df = df.rename(columns={"timestamp": "t_sec"})

            gt_df    = get_gt(ap, attack)
            err      = compute_error(df, gt_df)
            s        = err_stats(err)
            mean_ms  = float(df["solve_ms"].mean()) if "solve_ms" in df.columns else np.nan

            results[ap][attack] = {
                **s,
                "mean_solve_ms": mean_ms,
                "df":  df,
                "err": err,
            }

    return results


def no_data_panel(ax, msg="No data\n(run experiment first)"):
    ax.text(0.5, 0.5, msg, transform=ax.transAxes,
            ha="center", va="center", color="#aaa", fontsize=10,
            fontstyle="italic")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)


# ── Figure 1: Baseline comparison — all 6 approaches ─────────────────────────
def fig1_baseline_comparison(results, out_dir):
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("Positioning Error — Baseline (no attack), px4_1\nError vs Gazebo Ground Truth (m)",
                 fontsize=13, fontweight="bold", y=1.01)

    for idx, (ap, ap_meta) in enumerate(APPROACHES.items()):
        ax = axes.flatten()[idx]
        r  = results[ap].get("baseline")

        ax.set_title(ap_meta["label"], fontsize=12, fontweight="bold",
                     color=ap_meta["color"])
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Error vs GT (m)")
        ax.grid(True, alpha=0.3)

        if r is None or r["err"] is None:
            no_data_panel(ax)
            continue

        t_full = r["df"]["t_sec"].values
        t   = t_full - t_full[0]          # relative time
        err = r["err"]
        t   = t[:len(err)]                # match mask length
        ax.plot(t, err, color=ap_meta["color"], linewidth=1.2, alpha=0.85)
        ax.axhline(r["mean"], color=ap_meta["color"], linewidth=1,
                   linestyle="--", alpha=0.6, label=f"mean={r['mean']:.2f}m")

        # Annotate stats
        ax.text(0.97, 0.97,
                f"mean {r['mean']:.2f}m\npeak {r['peak']:.2f}m\nsolve {r['mean_solve_ms']:.1f}ms",
                transform=ax.transAxes, ha="right", va="top", fontsize=9,
                bbox=dict(facecolor="white", alpha=0.7, edgecolor="none"))
        ax.legend(fontsize=8)

    plt.tight_layout()
    out = os.path.join(out_dir, "fig1_baseline_comparison.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 1 -> {out}")


# ── Figure 2: Per-attack 4-panel — all approaches overlaid ───────────────────
def fig2_attack_comparison(results, out_dir):
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.suptitle("All Approaches Under Each Attack — px4_1\nError vs Gazebo Ground Truth (m)",
                 fontsize=13, fontweight="bold")

    for idx, attack in enumerate(ATTACKS):
        ax = axes.flatten()[idx]
        ax.set_title(f"Attack: {attack}", fontsize=12, fontweight="bold",
                     color=ATTACK_COLORS[attack])
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Error vs GT (m)")
        ax.grid(True, alpha=0.3)

        plotted = False
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

        if not plotted:
            no_data_panel(ax)
        else:
            ax.legend(fontsize=8, loc="upper right")

    plt.tight_layout()
    out = os.path.join(out_dir, "fig2_attack_comparison.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 2 -> {out}")


# ── Figure 3: RQ2 trade-off ───────────────────────────────────────────────────
def fig3_rq2_tradeoff(results, out_dir):
    fig = plt.figure(figsize=(16, 7))
    fig.suptitle("RQ2: Security–Accuracy–Compute Trade-off — px4_1",
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
        ax1.set_title("Accuracy — Mean Error (baseline / hover)")
        for bar, val in zip(bars, mean_errs):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                     f"{val:.2f}m", ha="center", va="bottom", fontsize=9)
    ax1.grid(True, axis="y", alpha=0.3)

    # ── Right: scatter — mean error vs solve time, all attacks ───────────────
    attack_markers = {"baseline": "o", "sybil": "s", "replay": "^", "wormhole": "D"}
    attack_sizes   = {"baseline": 100, "sybil": 120, "replay": 120, "wormhole": 120}
    handles = []

    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap].get(attack)
            if r is None or np.isnan(r.get("mean", np.nan)) or np.isnan(r.get("mean_solve_ms", np.nan)):
                continue
            sc = ax2.scatter(r["mean_solve_ms"], r["mean"],
                             color=ap_meta["color"],
                             marker=attack_markers[attack],
                             s=attack_sizes[attack],
                             alpha=0.85, zorder=5,
                             edgecolors="white", linewidths=0.5)

    # Legend: approaches by color
    for ap, ap_meta in APPROACHES.items():
        handles.append(mpatches.Patch(color=ap_meta["color"], label=ap_meta["label"]))
    # Legend: attacks by marker shape (text)
    for atk, mk in attack_markers.items():
        handles.append(plt.Line2D([0], [0], marker=mk, color="gray",
                                  linestyle="None", markersize=8,
                                  label=f"attack: {atk}"))

    ax2.set_xlabel("Mean Solve Time (ms)")
    ax2.set_ylabel("Mean Positioning Error (m)")
    ax2.set_title("Security–Compute Trade-off\n(bottom-left = best)")
    ax2.legend(handles=handles, fontsize=7, loc="upper left",
               bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax2.grid(True, alpha=0.3)

    # Annotate ideal quadrant
    ax2.annotate("ideal\nquadrant", xy=(0, 0), xytext=(0.05, 0.08),
                 textcoords="axes fraction", fontsize=8, color="#27ae60",
                 arrowprops=dict(arrowstyle="->", color="#27ae60", lw=0.8))

    plt.tight_layout()
    out = os.path.join(out_dir, "fig3_rq2_tradeoff.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 3 -> {out}")


# ── Figure 4: Solve latency over time ─────────────────────────────────────────
def fig4_solve_latency(results, out_dir):
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.suptitle("Solve Latency Over Time — px4_1 (baseline / hover)",
                 fontsize=12, fontweight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Solve Time (ms)")
    ax.grid(True, alpha=0.3)

    plotted = False
    for ap, ap_meta in APPROACHES.items():
        r = results[ap].get("baseline")
        if r is None or "solve_ms" not in r["df"].columns:
            continue
        df = r["df"]
        # Skip WLS/EKF — their solve_ms is 0 (logged externally)
        if df["solve_ms"].max() < 0.01:
            continue
        t_s = df["t_sec"].values; t_s = t_s - t_s[0]
        ax.plot(t_s, df["solve_ms"].values,
                label=ap_meta["label"], color=ap_meta["color"],
                linestyle=ap_meta["ls"], linewidth=1.0, alpha=0.8)
        plotted = True

    if plotted:
        ax.legend(fontsize=9)
        # Add mean annotations
        for ap, ap_meta in APPROACHES.items():
            r = results[ap].get("baseline")
            if r is None or np.isnan(r["mean_solve_ms"]) or r["mean_solve_ms"] < 0.01:
                continue
            ax.axhline(r["mean_solve_ms"], color=ap_meta["color"],
                       linewidth=0.7, linestyle=":", alpha=0.5)
    else:
        no_data_panel(ax, "No solve_ms data\n(WLS/EKF loggers have 0ms placeholder)")

    plt.tight_layout()
    out = os.path.join(out_dir, "fig4_solve_latency.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 4 -> {out}")


# ── Figure 5: Attack degradation bar chart ────────────────────────────────────
def fig5_attack_degradation(results, out_dir):
    """Shows how much each attack raises mean error above baseline for each approach."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle("Attack Impact — Mean Error Increase Above Baseline (m)\npx4_1",
                 fontsize=13, fontweight="bold")

    attack_list = ["sybil", "replay", "wormhole"]

    for col, attack in enumerate(attack_list):
        ax = axes[col]
        ax.set_title(f"Attack: {attack}", fontsize=12, fontweight="bold",
                     color=ATTACK_COLORS[attack])
        ax.set_ylabel("Error increase above baseline (m)")
        ax.grid(True, axis="y", alpha=0.3)

        ap_labels, deltas, bar_colors = [], [], []
        for ap, ap_meta in APPROACHES.items():
            r_base   = results[ap].get("baseline")
            r_attack = results[ap].get(attack)

            if r_base is None or r_attack is None:
                continue
            if np.isnan(r_base["mean"]) or np.isnan(r_attack["mean"]):
                continue

            delta = r_attack["mean"] - r_base["mean"]
            ap_labels.append(ap_meta["label"])
            deltas.append(delta)
            bar_colors.append(ap_meta["color"])

        if not ap_labels:
            no_data_panel(ax, f"No {attack} attack data yet")
            continue

        bars = ax.bar(range(len(ap_labels)), deltas,
                      color=bar_colors, alpha=0.85, edgecolor="white", width=0.6)
        ax.set_xticks(range(len(ap_labels)))
        ax.set_xticklabels(ap_labels, rotation=30, ha="right", fontsize=8)
        ax.axhline(0, color="black", linewidth=0.8, linestyle="-")

        for bar, val in zip(bars, deltas):
            color = "#c0392b" if val > 0 else "#27ae60"
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + (0.02 if val >= 0 else -0.12),
                    f"{val:+.2f}m", ha="center", va="bottom",
                    fontsize=9, color=color, fontweight="bold")

    plt.tight_layout()
    out = os.path.join(out_dir, "fig5_attack_degradation.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 5 -> {out}")


# ── Summary table ─────────────────────────────────────────────────────────────
def write_summary_table(results, out_dir):
    rows = []
    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap].get(attack)
            row = {"approach": ap_meta["label"], "attack": attack}
            if r:
                row.update({
                    "mean_err_m":    f"{r['mean']:.4f}" if not np.isnan(r['mean']) else "",
                    "peak_err_m":    f"{r['peak']:.4f}" if not np.isnan(r['peak']) else "",
                    "rmse_m":        f"{r['rmse']:.4f}" if not np.isnan(r['rmse']) else "",
                    "std_m":         f"{r['std']:.4f}"  if not np.isnan(r['std'])  else "",
                    "mean_solve_ms": f"{r['mean_solve_ms']:.3f}" if not np.isnan(r['mean_solve_ms']) else "",
                })
            else:
                row.update({"mean_err_m":"","peak_err_m":"","rmse_m":"","std_m":"","mean_solve_ms":""})
            rows.append(row)

    df = pd.DataFrame(rows)
    out = os.path.join(out_dir, "summary_table.csv")
    df.to_csv(out, index=False)
    print(f"  Summary table -> {out}")

    # Also print to console
    print("\n  === RESULTS SUMMARY ===")
    print(f"  {'Approach':<22} {'Attack':<10} {'Mean(m)':>8} {'Peak(m)':>8} {'RMSE(m)':>8} {'Solve(ms)':>10}")
    print(f"  {'-'*72}")
    for _, row in df.iterrows():
        if row["mean_err_m"]:
            print(f"  {row['approach']:<22} {row['attack']:<10} "
                  f"{row['mean_err_m']:>8} {row['peak_err_m']:>8} "
                  f"{row['rmse_m']:>8} {row['mean_solve_ms']:>10}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drone",      default="px4_1")
    parser.add_argument("--gt-csv",     default=None,
                        help="Override GT CSV path (default: auto-detect)")
    parser.add_argument("--out-dir",    default=OUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # Override GT if specified
    if args.gt_csv:
        # Patch find_gt_csv to always return this file
        import builtins
        _orig_find = globals()["find_gt_csv"]
        globals()["find_gt_csv"] = lambda drone, approach=None, attack=None: args.gt_csv

    print(f"\nDissertation Analysis")
    print(f"  Drone:      {args.drone}")
    print(f"  Metrics:    {METRICS_DIR}")
    print(f"  GT dir:     {GT_DIR}")
    print(f"  Output:     {args.out_dir}")
    print()

    print("Loading results...")
    results = load_all_results(args.drone)

    # Print what was found
    found = [(ap, atk) for ap in APPROACHES for atk in ATTACKS
             if results[ap].get(atk) is not None]
    print(f"  Found {len(found)} experiment records")
    for ap, atk in found:
        r = results[ap][atk]
        print(f"    {ap:<20} {atk:<10}  mean={r['mean']:.3f}m  "
              f"peak={r['peak']:.3f}m  solve={r['mean_solve_ms']:.2f}ms")

    print(f"\nGenerating figures -> {args.out_dir}/")

    fig1_baseline_comparison(results, args.out_dir)
    fig2_attack_comparison(results, args.out_dir)
    fig3_rq2_tradeoff(results, args.out_dir)
    fig4_solve_latency(results, args.out_dir)
    fig5_attack_degradation(results, args.out_dir)
    write_summary_table(results, args.out_dir)

    print("\nAll figures saved.")
    print(f"\nView figures:")
    print(f"  ls -lh {args.out_dir}/")
    print(f"\nNext: run attack experiments to fill in the missing panels:")
    missing = [(ap, atk) for ap in APPROACHES for atk in ATTACKS
               if results[ap].get(atk) is None]
    for ap, atk in missing[:8]:
        print(f"  bash ~/Dissertation/scripts/run_experiment.sh {ap} {atk}")
    if len(missing) > 8:
        print(f"  ... and {len(missing)-8} more")


if __name__ == "__main__":
    main()
