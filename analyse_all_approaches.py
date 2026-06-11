#!/usr/bin/env python3
"""
analyse_all_approaches.py  (v2 — works with or without ground truth)
======================================================================
Reads per-drone CSV logs from ~/Dissertation/evidence/metrics/ and
optionally a ground truth CSV, then produces:

  1. Summary table  (console + CSV)
  2. 6-panel error/position comparison figure
  3. Trade-off scatter  (mean error vs mean solve_ms)
  4. Solve-latency-over-time figure

WITHOUT ground truth (--gt-csv omitted):
  Error = displacement from spawn position (drift proxy).
  Solve-time figures still fully produced.

WITH ground truth:
  Error = Euclidean distance from Gazebo true position.

CSV naming supported:
  {approach}_{drone}.csv
  {approach}_{drone}_baseline.csv
  {approach}_{drone}_{attack}.csv

Usage:
  python3 analyse_all_approaches.py --drone px4_1
  python3 analyse_all_approaches.py --drone px4_1 \
      --gt-csv ~/Dissertation/evidence/gt/gt_px4_1.csv
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEFAULT_METRICS_DIR = os.path.expanduser("~/Dissertation/evidence/metrics")
DEFAULT_FIGURES_DIR = os.path.expanduser("~/Dissertation/evidence/figures")

SPAWN_POSITIONS = {
    "px4_1": np.array([0.0, 0.0, 0.0]),
    "px4_2": np.array([2.0, 0.0, 0.0]),
    "px4_3": np.array([4.0, 0.0, 0.0]),
    "px4_4": np.array([2.0, 2.0, 0.0]),
    "px4_5": np.array([4.0, 2.0, 0.0]),
}

APPROACHES = {
    "wls":            {"label": "WLS (baseline)",      "color": "#e74c3c", "ls": "-"},
    "ekf":            {"label": "EKF (baseline)",      "color": "#e67e22", "ls": "--"},
    "wls_huber":      {"label": "WLS + Huber",         "color": "#3498db", "ls": "-"},
    "wls_tukey":      {"label": "WLS + Tukey",         "color": "#9b59b6", "ls": "--"},
    "ransac":         {"label": "RANSAC",              "color": "#1abc9c", "ls": "-."},
    "ekf_chi2_huber": {"label": "EKF + chi2 + Huber", "color": "#2ecc71", "ls": "-"},
}

ATTACKS = ["baseline", "sybil", "replay", "wormhole"]
ATTACK_COLORS = {
    "baseline": "#7f8c8d",
    "sybil":    "#e74c3c",
    "replay":   "#e67e22",
    "wormhole": "#8e44ad",
}


def load_csv(path):
    if not path or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty or len(df) < 1:
            return None
        return df
    except Exception as e:
        print(f"  [warn] {path}: {e}")
        return None


def find_csv(metrics_dir, approach, attack, drone):
    if attack == "baseline":
        candidates = [
            f"{approach}_{drone}.csv",
            f"{approach}_{drone}_baseline.csv",
        ]
    else:
        candidates = [
            f"{approach}_{drone}_{attack}.csv",
            f"{approach}_{drone}_{attack}_run.csv",
        ]
    for stem in candidates:
        p = os.path.join(metrics_dir, stem)
        if os.path.exists(p):
            return p
    return None


def compute_error(df, gt_df, drone, use_spawn):
    x = df["x"].values
    y = df["y"].values
    z = df["z"].values

    if gt_df is not None:
        t    = df["t_sec"].values
        gt_x = np.interp(t, gt_df["t_sec"].values, gt_df["x"].values)
        gt_y = np.interp(t, gt_df["t_sec"].values, gt_df["y"].values)
        gt_z = np.interp(t, gt_df["t_sec"].values, gt_df["z"].values)
        return np.sqrt((x-gt_x)**2 + (y-gt_y)**2 + (z-gt_z)**2)

    if use_spawn and drone in SPAWN_POSITIONS:
        sp = SPAWN_POSITIONS[drone]
        return np.sqrt((x-sp[0])**2 + (y-sp[1])**2 + (z-sp[2])**2)

    return None


def stats(err):
    if err is None or len(err) == 0:
        return dict(mean=np.nan, peak=np.nan, rmse=np.nan)
    return dict(
        mean=float(np.mean(err)),
        peak=float(np.max(err)),
        rmse=float(np.sqrt(np.mean(err**2))),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drone",       default="px4_1")
    parser.add_argument("--gt-csv",      default=None)
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR)
    parser.add_argument("--figures-dir", default=DEFAULT_FIGURES_DIR)
    args = parser.parse_args()

    drone       = args.drone
    metrics_dir = args.metrics_dir
    figures_dir = args.figures_dir
    os.makedirs(figures_dir, exist_ok=True)

    gt_df = load_csv(args.gt_csv)
    if args.gt_csv and gt_df is None:
        if os.path.exists(args.gt_csv):
            print(f"[warn] GT CSV exists but has no data rows: {args.gt_csv}")
            print("[warn]  -> Did you run extract_ground_truth.py while SITL was running?")
            print("[warn]  -> Model names must match: Gazebo uses x500_1..x500_5")
        else:
            print(f"[warn] GT CSV not found: {args.gt_csv}")
        print("[warn] Falling back to spawn-position drift proxy")

    use_spawn   = gt_df is None
    error_label = "Error vs GT (m)" if gt_df is not None else "Drift from spawn (m) [proxy]"

    print(f"\nDrone:      {drone}")
    print(f"Metrics:    {metrics_dir}")
    print(f"Error mode: {'ground truth' if gt_df is not None else 'spawn-position drift proxy'}\n")

    # ── Load all results ──────────────────────────────────────────────────────
    results = {ap: {} for ap in APPROACHES}

    for ap in APPROACHES:
        for attack in ATTACKS:
            path = find_csv(metrics_dir, ap, attack, drone)
            df   = load_csv(path)
            if df is None:
                results[ap][attack] = None
                continue

            if "t_sec" not in df.columns and "timestamp" in df.columns:
                df = df.rename(columns={"timestamp": "t_sec"})

            err     = compute_error(df, gt_df, drone, use_spawn)
            s       = stats(err)
            mean_ms = float(df["solve_ms"].mean()) if "solve_ms" in df.columns else np.nan

            results[ap][attack] = {**s, "mean_solve_ms": mean_ms, "df": df, "err": err}
            print(f"  [{ap:20s}][{attack:10s}]  "
                  f"mean={s['mean']:6.3f}m  peak={s['peak']:7.3f}m  "
                  f"rmse={s['rmse']:6.3f}m  solve={mean_ms:6.2f}ms")

    # ── Summary CSV ──────────────────────────────────────────────────────────
    rows = []
    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap][attack]
            row = {"approach": ap_meta["label"], "attack": attack}
            if r:
                row.update({
                    "mean_err_m":    f"{r['mean']:.4f}",
                    "peak_err_m":    f"{r['peak']:.4f}",
                    "rmse_m":        f"{r['rmse']:.4f}",
                    "mean_solve_ms": f"{r['mean_solve_ms']:.3f}",
                })
            else:
                row.update({"mean_err_m":"","peak_err_m":"","rmse_m":"","mean_solve_ms":""})
            rows.append(row)

    summary_path = os.path.join(metrics_dir, "summary_table.csv")
    pd.DataFrame(rows).to_csv(summary_path, index=False)
    print(f"\nSummary table -> {summary_path}")

    # ── Figure 1: 6-panel approach comparison ────────────────────────────────
    fig1, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig1.suptitle(f"Positioning Error by Approach — {drone}\n({error_label})",
                  fontsize=13, fontweight="bold")

    for idx, (ap, ap_meta) in enumerate(APPROACHES.items()):
        ax = axes.flatten()[idx]
        ax.set_title(ap_meta["label"], fontsize=11, fontweight="bold",
                     color=ap_meta["color"])
        ax.set_xlabel("Time (s)", fontsize=9)
        ax.set_ylabel(error_label, fontsize=9)
        plotted = False
        for attack in ATTACKS:
            r = results[ap][attack]
            if r is None or r["err"] is None:
                continue
            ax.plot(r["df"]["t_sec"].values, r["err"],
                    label=attack, color=ATTACK_COLORS[attack],
                    linewidth=1.5, alpha=0.85)
            plotted = True
        if not plotted:
            ax.text(0.5, 0.5, "No data\n(run experiments first)",
                    transform=ax.transAxes, ha="center", va="center",
                    color="#bbb", fontsize=10)
        else:
            ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    p1 = os.path.join(figures_dir, f"approach_comparison_6panel_{drone}.png")
    fig1.savefig(p1, dpi=150, bbox_inches="tight")
    plt.close(fig1)
    print(f"Figure 1 -> {p1}")

    # ── Figure 2: RQ2 trade-off (solve time bar + scatter) ───────────────────
    fig2, axes2 = plt.subplots(1, 2, figsize=(14, 6))
    fig2.suptitle(f"RQ2 Trade-off Evidence — {drone}", fontsize=13, fontweight="bold")

    # Bar: mean solve time per approach (baseline condition)
    ap_labels, solve_times, bar_colors = [], [], []
    for ap, ap_meta in APPROACHES.items():
        r = results[ap].get("baseline")
        if r and not np.isnan(r["mean_solve_ms"]):
            ap_labels.append(ap_meta["label"])
            solve_times.append(r["mean_solve_ms"])
            bar_colors.append(ap_meta["color"])

    ax_bar = axes2[0]
    if ap_labels:
        bars = ax_bar.bar(range(len(ap_labels)), solve_times,
                          color=bar_colors, alpha=0.85, edgecolor="white")
        ax_bar.set_xticks(range(len(ap_labels)))
        ax_bar.set_xticklabels(ap_labels, rotation=35, ha="right", fontsize=8)
        ax_bar.set_ylabel("Mean Solve Time (ms)")
        ax_bar.set_title("Computational Cost (baseline / hover)")
        for bar, val in zip(bars, solve_times):
            ax_bar.text(bar.get_x() + bar.get_width()/2,
                        bar.get_height() + 0.02,
                        f"{val:.2f}ms", ha="center", va="bottom", fontsize=8)
    else:
        ax_bar.text(0.5, 0.5, "No baseline data yet",
                    transform=ax_bar.transAxes, ha="center", va="center", color="#bbb")
    ax_bar.grid(True, axis="y", alpha=0.3)

    # Scatter: mean error vs mean solve time
    ax_scat = axes2[1]
    ax_scat.set_xlabel("Mean Solve Time (ms)")
    ax_scat.set_ylabel(error_label)
    ax_scat.set_title("Security-Compute Trade-off")
    markers = {"baseline":"o", "sybil":"s", "replay":"^", "wormhole":"D"}
    scatter_done = False
    for ap, ap_meta in APPROACHES.items():
        for attack in ATTACKS:
            r = results[ap][attack]
            if r is None or np.isnan(r["mean"]) or np.isnan(r["mean_solve_ms"]):
                continue
            ax_scat.scatter(r["mean_solve_ms"], r["mean"],
                            color=ap_meta["color"], marker=markers[attack],
                            s=80, alpha=0.85, zorder=5)
            ax_scat.annotate(f"{ap}\n({attack})",
                             (r["mean_solve_ms"], r["mean"]),
                             fontsize=5, xytext=(3,2), textcoords="offset points")
            scatter_done = True
    if not scatter_done:
        ax_scat.text(0.5, 0.5, "Provide --gt-csv for\nerror vs solve-time scatter",
                     transform=ax_scat.transAxes, ha="center", va="center",
                     color="#bbb", fontsize=10)
    ax_scat.grid(True, alpha=0.3)

    plt.tight_layout()
    p2 = os.path.join(figures_dir, f"tradeoff_rq2_{drone}.png")
    fig2.savefig(p2, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print(f"Figure 2 -> {p2}")

    # ── Figure 3: Per-attack 4-panel (all approaches overlaid) ───────────────
    fig3, axes3 = plt.subplots(2, 2, figsize=(16, 10))
    fig3.suptitle(f"All Approaches Under Each Attack — {drone}\n({error_label})",
                  fontsize=13, fontweight="bold")

    for idx, attack in enumerate(ATTACKS):
        ax = axes3.flatten()[idx]
        ax.set_title(f"Attack: {attack}", fontsize=11, fontweight="bold",
                     color=ATTACK_COLORS[attack])
        ax.set_xlabel("Time (s)", fontsize=9)
        ax.set_ylabel(error_label, fontsize=9)
        plotted = False
        for ap, ap_meta in APPROACHES.items():
            r = results[ap][attack]
            if r is None or r["err"] is None:
                continue
            ax.plot(r["df"]["t_sec"].values, r["err"],
                    label=ap_meta["label"],
                    color=ap_meta["color"], linestyle=ap_meta["ls"],
                    linewidth=1.5, alpha=0.85)
            plotted = True
        if not plotted:
            ax.text(0.5, 0.5, "No data\n(run experiments first)",
                    transform=ax.transAxes, ha="center", va="center",
                    color="#bbb", fontsize=10)
        else:
            ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    p3 = os.path.join(figures_dir, f"per_attack_all_approaches_{drone}.png")
    fig3.savefig(p3, dpi=150, bbox_inches="tight")
    plt.close(fig3)
    print(f"Figure 3 -> {p3}")

    # ── Figure 4: Solve latency over time ────────────────────────────────────
    fig4, ax4 = plt.subplots(figsize=(14, 5))
    ax4.set_title(f"Solve Latency Over Time — {drone} (baseline)",
                  fontsize=12, fontweight="bold")
    ax4.set_xlabel("Time (s)")
    ax4.set_ylabel("Solve Time (ms)")
    plotted4 = False
    for ap, ap_meta in APPROACHES.items():
        r = results[ap].get("baseline")
        if r is None or "solve_ms" not in r["df"].columns:
            continue
        ax4.plot(r["df"]["t_sec"].values, r["df"]["solve_ms"].values,
                 label=ap_meta["label"],
                 color=ap_meta["color"], linestyle=ap_meta["ls"],
                 linewidth=1.2, alpha=0.8)
        plotted4 = True
    if plotted4:
        ax4.legend(fontsize=9)
    ax4.grid(True, alpha=0.3)
    plt.tight_layout()
    p4 = os.path.join(figures_dir, f"solve_latency_{drone}.png")
    fig4.savefig(p4, dpi=150, bbox_inches="tight")
    plt.close(fig4)
    print(f"Figure 4 -> {p4}")

    print("\nAll done.")
    if gt_df is None:
        print("\nNOTE: For accurate error stats, extract ground truth while running:")
        print("  python3 extract_ground_truth.py")
        print("Then re-run with:")
        print(f"  python3 analyse_all_approaches.py --drone {drone} \\")
        print(f"      --gt-csv ~/Dissertation/evidence/gt/gt_{drone}.csv")


if __name__ == "__main__":
    main()
