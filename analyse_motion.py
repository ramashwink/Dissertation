#!/usr/bin/env python3
"""
analyse_motion.py
==================
Motion-experiment counterpart to analyse_dissertation.py — reads metrics CSVs
from evidence/metrics/motion (naming: {approach}_{drone}_{attack}_{pattern}.csv),
computes error against ground truth, and produces the same figure set used for
the static experiments, extended to cover all 11 motion attacks.

Works with whatever data exists — partial runs, missing attacks, missing
approaches — empty panels show "no data yet" rather than crashing.

Usage:
    python3 ~/Dissertation/analyse_motion.py
    python3 ~/Dissertation/analyse_motion.py --pattern hover
    python3 ~/Dissertation/analyse_motion.py --drone px4_1 --pattern hover

Output figures (~/Dissertation/evidence/figures/motion/):
    fig1_baseline_comparison.png    — 6-panel, all approaches at baseline
    fig2_attack_comparison.png      — per-attack panel grid, all approaches overlaid
    fig3_rq2_tradeoff.png           — RQ2 trade-off: error vs compute cost
    fig4_solve_latency.png          — solve time over time (baseline)
    fig5_attack_degradation.png     — error increase over baseline, per attack
    summary_table.csv               — full numeric results table
"""
import argparse
import itertools
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# ── Config ────────────────────────────────────────────────────────────────────
METRICS_DIR = os.path.expanduser("~/Dissertation/evidence/metrics/motion")
GT_DIR      = os.path.expanduser("~/Dissertation/evidence/gt/motion")
OUT_DIR     = os.path.expanduser("~/Dissertation/evidence/figures/motion")

APPROACHES = {
    "wls":            {"label": "WLS",               "color": "#e74c3c", "ls": "-",  "marker": "o"},
    "ekf":            {"label": "EKF",               "color": "#e67e22", "ls": "--", "marker": "s"},
    "wls_huber":      {"label": "WLS + Huber",       "color": "#3498db", "ls": "-",  "marker": "^"},
    "wls_tukey":      {"label": "WLS + Tukey",       "color": "#9b59b6", "ls": "--", "marker": "D"},
    "ransac":         {"label": "RANSAC",            "color": "#1abc9c", "ls": "-.", "marker": "v"},
    "ekf_chi2_huber": {"label": "EKF+chi2+Huber *",  "color": "#27ae60", "ls": "-",  "marker": "*"},
}

# Same order run_all_experiments_motion.sh uses: core attacks (comparable to
# the static matrix) followed by the motion-only targeted EKF attacks.
ATTACKS = [
    "baseline", "sybil", "replay", "wormhole", "sybil_consistent",
    "replay_gradual", "byzantine", "timesync",
    "targeted_ramp", "targeted_osc", "targeted_two_drone",
]
ATTACK_COLORS = {
    "baseline":          "#7f8c8d",
    "sybil":             "#e74c3c",
    "replay":            "#e67e22",
    "wormhole":          "#8e44ad",
    "sybil_consistent":  "#c0392b",
    "replay_gradual":    "#d35400",
    "byzantine":         "#2c3e50",
    "timesync":          "#16a085",
    "targeted_ramp":     "#f39c12",
    "targeted_osc":      "#8e44ad",
    "targeted_two_drone":"#2980b9",
}
ATTACK_MARKERS = {
    a: m for a, m in zip(ATTACKS, itertools.cycle(["o", "s", "^", "D", "v", "P", "X", "*", "h", "<", ">"]))
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


def find_metrics_csv(approach, attack, drone, pattern):
    p = os.path.join(METRICS_DIR, f"{approach}_{drone}_{attack}_{pattern}.csv")
    return p if os.path.exists(p) else None


def find_gt_csv(drone, approach, attack, pattern):
    candidates = [
        os.path.join(GT_DIR, f"gt_{drone}_{approach}_{attack}_{pattern}.csv"),
        os.path.join(GT_DIR, f"gt_{drone}_wls_baseline_{pattern}.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def compute_error(df, gt_df):
    """Euclidean error vs ground truth, interpolated to metrics timestamps."""
    if gt_df is None:
        return None
    if "t_sec" not in df.columns:
        return None
    t    = df["t_sec"].values
    gt_x = np.interp(t, gt_df["t_sec"].values, gt_df["x"].values)
    gt_y = np.interp(t, gt_df["t_sec"].values, gt_df["y"].values)
    gt_z = np.interp(t, gt_df["t_sec"].values, gt_df["z"].values)
    return np.sqrt((df["x"].values - gt_x)**2 +
                   (df["y"].values - gt_y)**2 +
                   (df["z"].values - gt_z)**2)


def err_stats(err):
    if err is None or len(err) == 0:
        return dict(mean=np.nan, peak=np.nan, rmse=np.nan, std=np.nan)
    return dict(
        mean = float(np.mean(err)),
        peak = float(np.max(err)),
        rmse = float(np.sqrt(np.mean(err**2))),
        std  = float(np.std(err)),
    )


def load_all_results(primary_drone, pattern):
    gt_cache = {}

    def get_gt(approach, attack):
        key = f"{approach}_{attack}"
        if key not in gt_cache:
            gt_cache[key] = load_csv(find_gt_csv(primary_drone, approach, attack, pattern))
        return gt_cache[key]

    results = {}
    for ap in APPROACHES:
        results[ap] = {}
        for attack in ATTACKS:
            path = find_metrics_csv(ap, attack, primary_drone, pattern)
            df   = load_csv(path)
            if df is None:
                results[ap][attack] = None
                continue

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
def fig1_baseline_comparison(results, out_dir, drone, pattern):
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(f"Positioning Error — Baseline (no attack), {drone}, {pattern}\nError vs Gazebo Ground Truth (m)",
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

        t   = r["df"]["t_sec"].values
        err = r["err"]
        ax.plot(t, err, color=ap_meta["color"], linewidth=1.2, alpha=0.85)
        ax.axhline(r["mean"], color=ap_meta["color"], linewidth=1,
                   linestyle="--", alpha=0.6, label=f"mean={r['mean']:.2f}m")

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


# ── Figure 2: Per-attack panel grid — all approaches overlaid ────────────────
def fig2_attack_comparison(results, out_dir, drone, pattern):
    attacks = [a for a in ATTACKS if a != "baseline"]
    ncols = 5
    nrows = -(-len(attacks) // ncols)  # ceil
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4.2 * nrows))
    fig.suptitle(f"All Approaches Under Each Attack — {drone}, {pattern}\nError vs Gazebo Ground Truth (m)",
                 fontsize=14, fontweight="bold")
    axes_flat = axes.flatten()

    for idx, attack in enumerate(attacks):
        ax = axes_flat[idx]
        ax.set_title(attack, fontsize=11, fontweight="bold",
                     color=ATTACK_COLORS.get(attack, "#333"))
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Error vs GT (m)")
        ax.grid(True, alpha=0.3)

        plotted = False
        for ap, ap_meta in APPROACHES.items():
            r = results[ap].get(attack)
            if r is None or r["err"] is None:
                continue
            t = r["df"]["t_sec"].values
            ax.plot(t, r["err"], label=ap_meta["label"],
                    color=ap_meta["color"], linestyle=ap_meta["ls"],
                    linewidth=1.5, alpha=0.85)
            plotted = True

        if not plotted:
            no_data_panel(ax)
        else:
            ax.legend(fontsize=7, loc="upper right")

    # Hide unused trailing axes
    for j in range(len(attacks), len(axes_flat)):
        axes_flat[j].axis("off")

    plt.tight_layout()
    out = os.path.join(out_dir, "fig2_attack_comparison.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 2 -> {out}")


# ── Figure 3: RQ2 trade-off ───────────────────────────────────────────────────
def fig3_rq2_tradeoff(results, out_dir, drone, pattern):
    fig = plt.figure(figsize=(17, 7))
    fig.suptitle(f"RQ2: Security-Accuracy-Compute Trade-off — {drone}, {pattern}",
                 fontsize=13, fontweight="bold")

    gs  = GridSpec(1, 2, figure=fig, wspace=0.4)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])

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
        ax1.set_title(f"Accuracy — Mean Error (baseline / {pattern})")
        for bar, val in zip(bars, mean_errs):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                     f"{val:.2f}m", ha="center", va="bottom", fontsize=9)
    else:
        no_data_panel(ax1)
    ax1.grid(True, axis="y", alpha=0.3)

    handles = []
    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap].get(attack)
            if r is None or np.isnan(r.get("mean", np.nan)) or np.isnan(r.get("mean_solve_ms", np.nan)):
                continue
            ax2.scatter(r["mean_solve_ms"], r["mean"],
                        color=ap_meta["color"],
                        marker=ATTACK_MARKERS[attack],
                        s=90, alpha=0.85, zorder=5,
                        edgecolors="white", linewidths=0.5)

    for ap, ap_meta in APPROACHES.items():
        handles.append(mpatches.Patch(color=ap_meta["color"], label=ap_meta["label"]))
    for atk in ATTACKS:
        handles.append(plt.Line2D([0], [0], marker=ATTACK_MARKERS[atk], color="gray",
                                  linestyle="None", markersize=7,
                                  label=f"attack: {atk}"))

    ax2.set_xlabel("Mean Solve Time (ms)")
    ax2.set_ylabel("Mean Positioning Error (m)")
    ax2.set_title("Security-Compute Trade-off\n(bottom-left = best)")
    ax2.legend(handles=handles, fontsize=6.5, loc="upper left",
               bbox_to_anchor=(1.01, 1), borderaxespad=0, ncol=1)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out = os.path.join(out_dir, "fig3_rq2_tradeoff.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 3 -> {out}")


# ── Figure 4: Solve latency over time ─────────────────────────────────────────
def fig4_solve_latency(results, out_dir, drone, pattern):
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.suptitle(f"Solve Latency Over Time — {drone} (baseline / {pattern})",
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
        if df["solve_ms"].max() < 0.01:
            continue
        ax.plot(df["t_sec"].values, df["solve_ms"].values,
                label=ap_meta["label"], color=ap_meta["color"],
                linestyle=ap_meta["ls"], linewidth=1.0, alpha=0.8)
        plotted = True

    if plotted:
        ax.legend(fontsize=9)
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
def fig5_attack_degradation(results, out_dir, drone, pattern):
    attack_list = [a for a in ATTACKS if a != "baseline"]
    ncols = 5
    nrows = -(-len(attack_list) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 5 * nrows))
    fig.suptitle(f"Attack Impact — Mean Error Increase Above Baseline (m)\n{drone}, {pattern}",
                 fontsize=13, fontweight="bold")
    axes_flat = axes.flatten()

    for col, attack in enumerate(attack_list):
        ax = axes_flat[col]
        ax.set_title(attack, fontsize=11, fontweight="bold",
                     color=ATTACK_COLORS.get(attack, "#333"))
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
            no_data_panel(ax, f"No {attack}\ndata yet")
            continue

        bars = ax.bar(range(len(ap_labels)), deltas,
                      color=bar_colors, alpha=0.85, edgecolor="white", width=0.6)
        ax.set_xticks(range(len(ap_labels)))
        ax.set_xticklabels(ap_labels, rotation=35, ha="right", fontsize=7)
        ax.axhline(0, color="black", linewidth=0.8, linestyle="-")

        for bar, val in zip(bars, deltas):
            color = "#c0392b" if val > 0 else "#27ae60"
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + (0.02 if val >= 0 else -0.12),
                    f"{val:+.2f}", ha="center", va="bottom",
                    fontsize=7, color=color, fontweight="bold")

    for j in range(len(attack_list), len(axes_flat)):
        axes_flat[j].axis("off")

    plt.tight_layout()
    out = os.path.join(out_dir, "fig5_attack_degradation.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Fig 5 -> {out}")


# ── Summary table ─────────────────────────────────────────────────────────────
def write_summary_table(results, out_dir, pattern):
    rows = []
    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap].get(attack)
            row = {"approach": ap_meta["label"], "attack": attack, "pattern": pattern}
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

    print("\n  === RESULTS SUMMARY ===")
    print(f"  {'Approach':<22} {'Attack':<20} {'Mean(m)':>8} {'Peak(m)':>8} {'RMSE(m)':>8} {'Solve(ms)':>10}")
    print(f"  {'-'*84}")
    for _, row in df.iterrows():
        if row["mean_err_m"]:
            print(f"  {row['approach']:<22} {row['attack']:<20} "
                  f"{row['mean_err_m']:>8} {row['peak_err_m']:>8} "
                  f"{row['rmse_m']:>8} {row['mean_solve_ms']:>10}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drone",   default="px4_1")
    parser.add_argument("--pattern", default="hover")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    out_dir = os.path.join(args.out_dir, args.pattern) if args.pattern != "hover" else args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    print(f"\nMotion Experiment Analysis")
    print(f"  Drone:      {args.drone}")
    print(f"  Pattern:    {args.pattern}")
    print(f"  Metrics:    {METRICS_DIR}")
    print(f"  GT dir:     {GT_DIR}")
    print(f"  Output:     {out_dir}")
    print()

    print("Loading results...")
    results = load_all_results(args.drone, args.pattern)

    found = [(ap, atk) for ap in APPROACHES for atk in ATTACKS
             if results[ap].get(atk) is not None]
    print(f"  Found {len(found)}/{len(APPROACHES) * len(ATTACKS)} experiment records")
    for ap, atk in found:
        r = results[ap][atk]
        print(f"    {ap:<16} {atk:<20}  mean={r['mean']:.3f}m  "
              f"peak={r['peak']:.3f}m  solve={r['mean_solve_ms']:.2f}ms")

    missing = [(ap, atk) for ap in APPROACHES for atk in ATTACKS
               if results[ap].get(atk) is None]
    if missing:
        print(f"\n  Missing {len(missing)} record(s):")
        for ap, atk in missing:
            print(f"    {ap} / {atk}")

    print(f"\nGenerating figures -> {out_dir}/")

    fig1_baseline_comparison(results, out_dir, args.drone, args.pattern)
    fig2_attack_comparison(results, out_dir, args.drone, args.pattern)
    fig3_rq2_tradeoff(results, out_dir, args.drone, args.pattern)
    fig4_solve_latency(results, out_dir, args.drone, args.pattern)
    fig5_attack_degradation(results, out_dir, args.drone, args.pattern)
    write_summary_table(results, out_dir, args.pattern)

    print("\nAll figures saved.")


if __name__ == "__main__":
    main()
