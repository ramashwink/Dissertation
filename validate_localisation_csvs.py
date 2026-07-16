#!/usr/bin/env python3
"""
validate_localisation_csvs.py
==============================
Companion to validate_attacks.py. While validate_attacks.py checks whether
the ATTACK's own injected signal fired, this script checks whether the
LOCALISATION ALGORITHM's estimate CSV (wls_pxN_*.csv, ekf_pxN_*.csv,
wls_huber_pxN_*.csv, etc. in evidence/metrics/) shows signs of being a
"frozen at spawn" degenerate run rather than a live solve.

WHY THIS EXISTS:
  Some summary_table.csv rows show mean_err_m == peak_err_m == rmse_m with
  exact equality to 3 decimal places (e.g. wls/sybil: 0.013/0.013/0.013).
  This zero-variance signature is consistent with cooperative_localisation_
  dynamic.py's _tick() returning early forever because `ready` (neighbours
  with fresh range measurements) never becomes non-empty -- i.e. the
  /swarm/registry -> _on_registry -> _add_neighbour chain never completed
  within the experiment window, so self._estimate never moves from its
  initial SPAWN_POSITIONS value.

  A run in this state is NOT measuring "WLS under attack X" -- it's
  measuring "the static distance between spawn position and ground truth
  at whatever instant GT logging started", which is closer to a constant
  offset than a security result.

CHECKS PER CSV:
  1. position_variance: var(x) + var(y) + var(z) across all rows. Near-zero
     (< POS_VAR_THRESHOLD) indicates the estimate never moved.
  2. error_variance: var(error_m) computed against GT. Near-zero with
     mean far from the position_variance=0 case below is a different but
     related signal (estimate moves, but error magnitude doesn't --
     possible if GT itself isn't updating).
  3. row_count vs expected: a 90s run at PUBLISH_HZ should have roughly
     90*PUBLISH_HZ rows (e.g. ~900 for 10Hz). Far fewer suggests early
     termination or a logger that started late.

Usage:
    python3 validate_localisation_csvs.py
    python3 validate_localisation_csvs.py --metrics-dir ~/Dissertation/evidence/metrics
    python3 validate_localisation_csvs.py --drone px4_1
    python3 validate_localisation_csvs.py --approach wls --attack sybil
"""
import argparse
import glob
import os
import numpy as np
import pandas as pd

DEFAULT_METRICS_DIR = os.path.expanduser("~/Dissertation/evidence/metrics")
DEFAULT_GT_DIR      = os.path.expanduser("~/Dissertation/evidence/gt")

POS_VAR_THRESHOLD = 1e-6   # m^2 -- below this, position is "frozen"
EXPECTED_ROWS_PER_SEC = {
    "wls": 10, "ekf": 10,          # coop_loc_logger.py default
    "wls_huber": 10, "wls_tukey": 10, "ransac": 10, "ekf_chi2_huber": 10,
}
EXPERIMENT_SEC = 90  # from run_experiment.sh


def find_csvs(metrics_dir, approach=None, attack=None, drone=None):
    pattern = os.path.join(metrics_dir, "*_px4_*.csv")
    paths = glob.glob(pattern)
    results = []
    for p in paths:
        name = os.path.basename(p).replace(".csv", "")
        parts = name.split("_px4_")
        if len(parts) != 2:
            continue
        ap = parts[0]
        rest = parts[1]  # e.g. "1" or "1_sybil" or "1_replay_gradual"
        rest_parts = rest.split("_", 1)
        dr = f"px4_{rest_parts[0]}"
        atk = rest_parts[1] if len(rest_parts) > 1 else "baseline"

        if approach and ap != approach:
            continue
        if attack and atk != attack:
            continue
        if drone and dr != drone:
            continue
        results.append((ap, dr, atk, p))
    return sorted(results)


def check_csv(approach, drone, attack, path):
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return f"ERROR reading: {e}"

    if len(df) < 2:
        return f"TOO SHORT ({len(df)} rows)"

    if not all(c in df.columns for c in ["x", "y", "z"]):
        return f"MISSING x/y/z columns (cols: {list(df.columns)})"

    x = pd.to_numeric(df["x"], errors="coerce")
    y = pd.to_numeric(df["y"], errors="coerce")
    z = pd.to_numeric(df["z"], errors="coerce")

    pos_var = float(x.var(ddof=0) + y.var(ddof=0) + z.var(ddof=0))

    notes = []
    severity = "PASS"

    if pos_var < POS_VAR_THRESHOLD:
        severity = "FROZEN"
        notes.append(f"position_variance={pos_var:.2e} (<{POS_VAR_THRESHOLD:.0e}) "
                      f"-- estimate never moved from initial value "
                      f"(x={x.iloc[0]:.4f}, y={y.iloc[0]:.4f}, z={z.iloc[0]:.4f}). "
                      f"Likely _tick() returned early forever -- check "
                      f"/swarm/registry neighbour discovery completed.")
    else:
        notes.append(f"position_variance={pos_var:.4f}m^2")

    expected_hz = EXPECTED_ROWS_PER_SEC.get(approach, 10)
    expected_rows = EXPERIMENT_SEC * expected_hz
    actual_rows = len(df)
    ratio = actual_rows / expected_rows
    if ratio < 0.5:
        if severity == "PASS":
            severity = "SHORT"
        notes.append(f"only {actual_rows} rows (~{ratio*100:.0f}% of expected "
                      f"~{expected_rows} for a {EXPERIMENT_SEC}s run at "
                      f"{expected_hz}Hz) -- logger may have started late or "
                      f"node crashed early")
    else:
        notes.append(f"{actual_rows} rows (~{ratio*100:.0f}% of expected)")

    if "t_sec" in df.columns:
        t = pd.to_numeric(df["t_sec"], errors="coerce")
        duration = float(t.iloc[-1] - t.iloc[0])
        notes.append(f"duration={duration:.1f}s")
        if duration < EXPERIMENT_SEC * 0.5:
            if severity == "PASS":
                severity = "SHORT_DURATION"

    return f"{severity}  " + "; ".join(notes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR)
    parser.add_argument("--approach", default=None)
    parser.add_argument("--attack", default=None)
    parser.add_argument("--drone", default=None)
    args = parser.parse_args()

    rows = find_csvs(args.metrics_dir, args.approach, args.attack, args.drone)

    if not rows:
        print(f"No matching CSVs found in {args.metrics_dir} "
              f"(approach={args.approach}, attack={args.attack}, drone={args.drone})")
        return

    print(f"{'approach':<18} {'drone':<8} {'attack':<18} {'result'}")
    print("-" * 110)

    frozen_count = 0
    for ap, dr, atk, path in rows:
        result = check_csv(ap, dr, atk, path)
        print(f"{ap:<18} {dr:<8} {atk:<18} {result}")
        if result.startswith("FROZEN"):
            frozen_count += 1

    print("-" * 110)
    if frozen_count:
        print(f"\n{frozen_count} FROZEN run(s) detected. These CSVs report a "
              f"constant position estimate and should NOT be cited as "
              f"'<approach> under <attack>' results -- they measure the "
              f"static spawn-to-GT offset only. Re-run after confirming "
              f"/swarm/registry shows all 5 drones registered before the "
              f"attack phase begins (check the discovery tmux window for "
              f"'[REGISTRY] Live: [...]' with all 5 px4_N present).")
    else:
        print("\nNo frozen runs detected.")


if __name__ == "__main__":
    main()
