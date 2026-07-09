#!/usr/bin/env python3
"""
validate_motion_csvs.py
========================
Stricter quality check for the motion experiment matrix than run_all_experiments_motion.sh's
own resume logic (which only checks row count > 10). This checks actual *time-span coverage*
of each CSV — a file can have >10 rows and still only span 20-30s of a 90s collection window
if data was sparse or the run was cut short.

Usage:
    python3 ~/Dissertation/validate_motion_csvs.py
    python3 ~/Dissertation/validate_motion_csvs.py --pattern hover --min-span 60
"""
import argparse
import os
import sys
import pandas as pd

METRICS_DIR = os.path.expanduser("~/Dissertation/evidence/metrics/motion")
GT_DIR      = os.path.expanduser("~/Dissertation/evidence/gt/motion")

APPROACHES = ["wls", "ekf", "wls_huber", "wls_tukey", "ransac", "ekf_chi2_huber"]
ATTACKS = [
    "baseline", "sybil", "replay", "wormhole", "sybil_consistent",
    "replay_gradual", "byzantine", "timesync",
    "targeted_ramp", "targeted_osc", "targeted_two_drone",
]
DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]


def span_and_rows(path):
    if not os.path.exists(path):
        return None, None
    try:
        df = pd.read_csv(path)
    except Exception:
        return 0, 0
    if df.empty or "t_sec" not in df.columns:
        return len(df), 0.0
    return len(df), float(df["t_sec"].max() - df["t_sec"].min())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", default="hover")
    parser.add_argument("--min-span", type=float, default=60.0,
                         help="Minimum acceptable time span in seconds (default 60 of a 90s window)")
    parser.add_argument("--min-rows", type=int, default=10)
    parser.add_argument("--min-density", type=float, default=0.5,
                         help="Minimum acceptable rows per second of span (default 0.5, i.e. >=1 sample per 2s)")
    args = parser.parse_args()

    bad = []
    missing = []
    ok = []

    for ap in APPROACHES:
        for atk in ATTACKS:
            for drone in DRONES:
                mpath = os.path.join(METRICS_DIR, f"{ap}_{drone}_{atk}_{args.pattern}.csv")
                gpath = os.path.join(GT_DIR, f"gt_{drone}_{ap}_{atk}_{args.pattern}.csv")

                mrows, mspan = span_and_rows(mpath)
                grows, gspan = span_and_rows(gpath)

                key = f"{ap:16s} {atk:20s} {drone}"

                if mrows is None or grows is None:
                    missing.append((key, "metrics" if mrows is None else "gt"))
                    continue

                mdensity = (mrows / mspan) if mspan and mspan > 0 else 0.0

                reasons = []
                if mrows < args.min_rows:
                    reasons.append(f"metrics rows={mrows}<{args.min_rows}")
                if mspan is not None and mspan < args.min_span:
                    reasons.append(f"metrics span={mspan:.1f}s<{args.min_span}s")
                if mspan is not None and mspan >= args.min_span and mdensity < args.min_density:
                    reasons.append(f"metrics density={mdensity:.2f} rows/s<{args.min_density} (rows={mrows} over {mspan:.1f}s)")
                if grows < args.min_rows:
                    reasons.append(f"gt rows={grows}")
                if gspan is not None and gspan < args.min_span:
                    reasons.append(f"gt span={gspan:.1f}s<{args.min_span}s")

                if reasons:
                    bad.append((key, "; ".join(reasons)))
                else:
                    ok.append((key, mrows, mspan, grows, gspan))

    total = len(APPROACHES) * len(ATTACKS) * len(DRONES)
    print(f"\nMotion CSV validation — pattern={args.pattern}  min_span={args.min_span}s  min_rows={args.min_rows}")
    print(f"  Total expected: {total}")
    print(f"  OK:             {len(ok)}")
    print(f"  Missing:        {len(missing)}")
    print(f"  Thin/bad:       {len(bad)}")

    if missing:
        print(f"\n=== MISSING ({len(missing)}) ===")
        for key, which in missing:
            print(f"  [{which}] {key}")

    if bad:
        print(f"\n=== THIN / BELOW THRESHOLD ({len(bad)}) ===")
        for key, reason in bad:
            print(f"  {key}  ->  {reason}")

    if not missing and not bad:
        print("\nAll combos pass the stricter time-span check.")

    sys.exit(1 if (missing or bad) else 0)


if __name__ == "__main__":
    main()
