#!/usr/bin/env python3
"""
add_degradation_factor.py
==========================
Post-processes summary_table.csv (produced by analyse_dissertation.py or
analyse_all_approaches.py) to add a `degradation_factor` column:

    degradation_factor = attack_mean_err_m / baseline_mean_err_m

for the SAME approach. This answers "how many times worse does this
approach get under attack X, relative to its OWN no-attack accuracy" --
the normalised comparison needed because absolute mean_err_m values are
not comparable across approaches with very different baseline accuracy
(e.g. ekf_chi2_huber baseline=0.034m vs wls baseline=0.542m: a jump to
1.0m is a 30x degradation for the former but only a 1.8x degradation for
the latter, despite the latter's ABSOLUTE error being higher).

Also flags two specific anomalies worth checking before citing:
  - Any row where degradation_factor < 1.0 (attack made things BETTER than
    baseline) -- usually indicates either a measurement issue (attack did
    not fire -- see validate_attacks.py) or a genuinely interesting
    "attack within noise floor" result that needs its own caveat.
  - The baseline row itself (degradation_factor == 1.0 by definition,
    included for completeness / sanity-checking).

Usage:
    python3 add_degradation_factor.py
    python3 add_degradation_factor.py --summary-csv /path/to/summary_table.csv

Output:
    Overwrites summary_table.csv in place with the new column appended,
    and ALSO writes summary_table_with_degradation.csv as a separate copy
    (so the original analyse_dissertation.py output is never silently lost
    if you re-run the analyser afterwards and it overwrites the original).

    Prints a flagged-anomalies report to stdout.
"""
import argparse
import os
import pandas as pd
import numpy as np

DEFAULT_SUMMARY = os.path.expanduser(
    "~/Dissertation/evidence/metrics/summary_table.csv")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-csv", default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    if not os.path.exists(args.summary_csv):
        print(f"ERROR: {args.summary_csv} not found. "
              f"Run analyse_dissertation.py or analyse_all_approaches.py first.")
        return

    df = pd.read_csv(args.summary_csv)

    if "mean_err_m" not in df.columns or "approach" not in df.columns:
        print(f"ERROR: {args.summary_csv} missing expected columns "
              f"(approach, mean_err_m). Found: {list(df.columns)}")
        return

    df["mean_err_m"] = pd.to_numeric(df["mean_err_m"], errors="coerce")

    # Build approach -> baseline mean_err_m lookup
    baseline_rows = df[df["attack"] == "baseline"]
    baseline_lookup = dict(zip(baseline_rows["approach"], baseline_rows["mean_err_m"]))

    missing_baseline = set(df["approach"].unique()) - set(baseline_lookup.keys())
    if missing_baseline:
        print(f"WARNING: no baseline row found for approach(es): "
              f"{sorted(missing_baseline)}. degradation_factor will be blank "
              f"for these -- run baseline experiments for them first.")

    def compute_factor(row):
        base = baseline_lookup.get(row["approach"])
        if base is None or pd.isna(base) or base <= 0:
            return np.nan
        if pd.isna(row["mean_err_m"]):
            return np.nan
        return row["mean_err_m"] / base

    df["degradation_factor"] = df.apply(compute_factor, axis=1)

    # Round for readability
    df["degradation_factor"] = df["degradation_factor"].round(2)

    out_main = args.summary_csv
    out_copy = os.path.join(os.path.dirname(args.summary_csv),
                             "summary_table_with_degradation.csv")
    df.to_csv(out_main, index=False)
    df.to_csv(out_copy, index=False)
    print(f"Updated: {out_main}")
    print(f"Copy:    {out_copy}")

    # ── Anomaly report ──────────────────────────────────────────────────────
    print("\n=== Anomaly report ===")

    attack_rows = df[df["attack"] != "baseline"].copy()
    attack_rows = attack_rows.dropna(subset=["degradation_factor"])

    improved = attack_rows[attack_rows["degradation_factor"] < 1.0]
    if not improved.empty:
        print("\nRows where the attack APPEARED to improve accuracy "
              "(degradation_factor < 1.0) -- verify with validate_attacks.py "
              "before citing, as this often indicates the attack did not "
              "fire as intended in this run:")
        for _, row in improved.iterrows():
            print(f"  {row['approach']:<20} {row['attack']:<18} "
                  f"factor={row['degradation_factor']:.2f}  "
                  f"(baseline={baseline_lookup.get(row['approach']):.3f}m, "
                  f"attack={row['mean_err_m']:.3f}m)")
    else:
        print("\nNo degradation_factor < 1.0 rows found.")

    # Highlight the largest degradation per attack (the "worst hit" approach)
    print("\nLargest degradation_factor per attack (worst-affected approach):")
    for attack in attack_rows["attack"].unique():
        sub = attack_rows[attack_rows["attack"] == attack]
        if sub.empty:
            continue
        worst = sub.loc[sub["degradation_factor"].idxmax()]
        print(f"  {attack:<18} {worst['approach']:<20} "
              f"factor={worst['degradation_factor']:.2f}x "
              f"({baseline_lookup.get(worst['approach']):.3f}m -> "
              f"{worst['mean_err_m']:.3f}m)")

    # Highlight smallest degradation per attack (the "most robust" approach,
    # among those with a valid baseline)
    print("\nSmallest degradation_factor per attack (most robust approach):")
    for attack in attack_rows["attack"].unique():
        sub = attack_rows[attack_rows["attack"] == attack]
        if sub.empty:
            continue
        best = sub.loc[sub["degradation_factor"].idxmin()]
        print(f"  {attack:<18} {best['approach']:<20} "
              f"factor={best['degradation_factor']:.2f}x "
              f"({baseline_lookup.get(best['approach']):.3f}m -> "
              f"{best['mean_err_m']:.3f}m)")


if __name__ == "__main__":
    main()
