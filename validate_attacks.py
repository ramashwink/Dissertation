#!/usr/bin/env python3
"""
validate_attacks.py
====================
Post-hoc sanity check for the attack metrics CSVs written to /tmp by each
attack node. Run this immediately after each attack (or after the full
run_all_experiments.sh matrix) to catch silent no-op runs BEFORE investing
time in the WLS/EKF/RANSAC comparison figures.

Each check answers: "did the attack's OWN injected signal actually move,
independent of whatever the localisation algorithm did with it?"
A PASS here does not mean the attack degraded localisation -- it means the
attack itself fired as intended, so a flat error_m elsewhere is attributable
to the mitigation, not a misfire.

Usage:
    python3 validate_attacks.py            # check all known attacks
    python3 validate_attacks.py wormhole    # check one attack by keyword
"""
import sys
import os
import pandas as pd
import numpy as np


def _load(path):
    if not os.path.exists(path):
        return None, f"MISSING ({path} not found -- run the attack first)"
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return None, f"ERROR reading CSV: {e}"
    if len(df) < 2:
        return None, f"EMPTY/TOO SHORT ({len(df)} rows -- attack likely killed before writing data)"
    return df, None


def check_sybil_registry(path="/tmp/sybil_registry_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    attack = df[df["phase"] == "attack"]
    if attack.empty:
        return "FAIL: no rows with phase=='attack' -- attack phase never reached"
    e1 = attack["px4_1_error_m"].astype(float)
    if e1.dropna().empty:
        return "SUSPECT: px4_1_error_m all NaN -- honest drone est/gt never both populated"
    peak = e1.max()
    return f"PASS  peak px4_1_error_m={peak:.4f}m" if peak > 0.01 \
        else f"SUSPECT: peak px4_1_error_m={peak:.4f}m (<=1cm) -- ghosts may not be perturbing WLS"


def check_replay(path="/tmp/replay_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    attack = df[df["phase"] == "attack"]
    if attack.empty:
        return "FAIL: no rows with phase=='attack'"
    age = attack["msg_age_s"].astype(float)
    peak_age = age.max()
    mode = df["mode"].iloc[0] if "mode" in df.columns else "unknown"
    expected_min = 1.0  # any replay should show >1s staleness well before DELAY_SEC=5
    return (f"PASS  mode={mode} peak_msg_age_s={peak_age:.2f}s"
            if peak_age > expected_min else
            f"SUSPECT: mode={mode} peak_msg_age_s={peak_age:.2f}s "
            f"(<{expected_min}s) -- buffer may be empty, check _buffer population")


def check_replay_gradual(path="/tmp/replay_attack_gradual_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    delay = df["current_delay_s"].astype(float)
    peak_delay = delay.max()
    # Check it actually RAMPS, not just jumps to max or sits at 0
    nonzero = (delay > 0).sum()
    is_monotonic_ish = delay.is_monotonic_increasing or (delay.diff().fillna(0) >= -1e-6).mean() > 0.9
    if peak_delay <= 0.01:
        return "FAIL: current_delay_s never exceeds ~0 -- ramp not firing"
    if not is_monotonic_ish:
        return f"SUSPECT: peak={peak_delay:.2f}s but delay is not monotonically increasing"
    return f"PASS  delay ramped 0 -> {peak_delay:.2f}s across {nonzero} attack ticks"


def check_wormhole(path="/tmp/wormhole_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    attack = df[df["phase"] == "attack"]
    if attack.empty:
        return "FAIL: no rows with phase=='attack'"
    true_d = attack["true_dist_m"].astype(float)
    rep_d  = attack["reported_dist_m"].astype(float)
    scale  = df["scale"].iloc[0] if "scale" in df.columns else None
    if true_d.max() <= 0.05:
        return ("FAIL: true_dist_m never exceeds 0.05m during attack phase -- "
                "px4_1<->px4_5 range pair likely never populated (see WARMUP_SEC fix). "
                "This run's est_separation_m / error figures are NOT TRUSTWORTHY.")
    # Check the shrink ratio roughly matches `scale`
    nz = true_d > 0.05
    if nz.any() and scale is not None:
        ratio = (rep_d[nz] / true_d[nz]).mean()
        ratio_ok = abs(ratio - float(scale)) < 0.02
        return (f"{'PASS' if ratio_ok else 'SUSPECT'}  "
                f"true_dist peak={true_d.max():.2f}m, mean reported/true ratio="
                f"{ratio:.4f} (expected scale={scale})")
    return f"PASS  true_dist peak={true_d.max():.2f}m"


def check_byzantine(path="/tmp/byzantine_insider_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    bias = df["bias_m"].astype(float)
    peak_bias = bias.max()
    if peak_bias <= 0.01:
        return "FAIL: bias_m never exceeds ~0 -- ramp never reached BIAS_MAX"

    notes = [f"peak bias_m={peak_bias:.3f}m"]

    if "true_pos_received" in df.columns:
        received_during_ramp = df[df["phase"] != "warmup"]["true_pos_received"].astype(int)
        if not received_during_ramp.empty and received_during_ramp.max() == 0:
            return (f"SUSPECT: bias ramped to {peak_bias:.3f}m but "
                    f"true_pos_received==0 throughout ramp/sustained phases -- "
                    f"bias was injected against frozen SPAWN_POSITIONS, not a "
                    f"live self_estimate. Check {df['t_s'].iloc[0]} onward for "
                    f"coop_loc_* startup ordering.")
        notes.append("true_pos_received=1 confirmed during attack")

    comp_col_x = None
    for col in df.columns:
        if col.endswith("_is_compromised"):
            drone = col.replace("_is_compromised", "")
            if df[col].iloc[0] == 1:
                comp_col_x = drone
                break
    if comp_col_x:
        err_col = f"{comp_col_x}_error_m"
        if err_col in df.columns:
            comp_err = pd.to_numeric(df[err_col], errors="coerce")
            if comp_err.dropna().empty:
                notes.append(f"{comp_col_x}_error_m all NaN")
            else:
                notes.append(f"{comp_col_x} (compromised) peak error={comp_err.max():.3f}m")

    return "PASS  " + ", ".join(notes)


def check_timesync(path="/tmp/timesync_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    attack = df[df["phase"] == "attack"]
    if attack.empty:
        return "FAIL: no rows with phase=='attack'"
    stamps = attack["injected_stamp_sec"].astype(float)
    mode = df["mode"].iloc[0] if "mode" in df.columns else "unknown"
    now_approx = attack["t_s"].astype(float).max() + 1.7e9  # rough epoch sanity bound

    if mode == "ancient":
        ok = (stamps.max() < 10.0) and (stamps.max() > 0)
        return (f"PASS  mode=ancient injected_stamp~{stamps.iloc[-1]:.2f}s (near epoch)"
                if ok else f"SUSPECT: mode=ancient but injected_stamp max={stamps.max():.2f} "
                            f"-- expected ~1.0 (epoch+1s)")
    elif mode == "future":
        ok = stamps.max() > 1e9  # should be a real future unix timestamp
        return (f"PASS  mode=future injected_stamp~{stamps.iloc[-1]:.0f} (unix future ts)"
                if ok else f"SUSPECT: mode=future injected_stamp max={stamps.max():.2f} "
                            f"looks too small to be a future epoch timestamp")
    elif mode == "jitter":
        spread = stamps.max() - stamps.min()
        return (f"PASS  mode=jitter stamp spread={spread:.2f}s across attack window"
                if spread > 0.5 else f"SUSPECT: mode=jitter but spread only {spread:.2f}s")
    return f"PASS (mode={mode}) stamps range {stamps.min():.2f}-{stamps.max():.2f}"


def check_sybil_consistent(path="/tmp/sybil_consistent_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    attack = df[df["phase"] == "attack"]
    if attack.empty:
        return "FAIL: no rows with phase=='attack'"

    notes = []
    if "evil_est_received" in df.columns:
        received = attack["evil_est_received"].astype(int)
        frac_received = received.mean()
        if frac_received < 0.5:
            return (f"SUSPECT: evil_est_received==1 for only {frac_received*100:.0f}% "
                    f"of attack ticks -- consistent ranges were computed against "
                    f"EVIL_SPAWN (stale) for most of the run, weakening the "
                    f"'consistent' premise of this attack")
        notes.append(f"evil_est_received=1 for {frac_received*100:.0f}% of attack ticks")

    alpha = attack["alpha"].astype(float)
    if alpha.max() < 0.99:
        notes.append(f"alpha never reached 1.0 (max={alpha.max():.2f}) -- "
                      f"ramp may not have completed within ATTACK_SEC")
    else:
        notes.append(f"alpha reached {alpha.max():.2f}")

    return "PASS  " + ", ".join(notes)


def check_sybil_service(path="/tmp/sybil_service_attack_metrics.csv"):
    df, err = _load(path)
    if err:
        return err
    n = len(df)
    ghosts = df[df["attempt_type"] == "ghost"]
    imperson = df[df["attempt_type"] == "impersonation"]
    notes = [f"{n} attempts logged"]
    if not ghosts.empty:
        all_rejected = (~ghosts["accepted"].astype(bool)).all()
        notes.append(f"ghosts all_rejected={all_rejected}")
        if not all_rejected:
            return ("SUSPECT: at least one ghost was ACCEPTED -- allowlist in "
                    "swarm_registry_service.py may be misconfigured. " + ", ".join(notes))
    if not imperson.empty:
        accepted = imperson["accepted"].astype(bool).any()
        notes.append(f"impersonation_accepted={accepted}")
        if not accepted:
            notes.append("(NOTE: docstring expects px4_2 impersonation to be "
                          "ACCEPTED -- this is the documented allowlist gap, "
                          "not a failure)")
    return "PASS  " + ", ".join(notes)


CHECKS = {
    "sybil_registry":    check_sybil_registry,
    "sybil_service":     check_sybil_service,
    "sybil_consistent":  check_sybil_consistent,
    "replay":            check_replay,
    "replay_gradual":    check_replay_gradual,
    "wormhole":          check_wormhole,
    "byzantine":         check_byzantine,
    "timesync":          check_timesync,
}


def main():
    filt = sys.argv[1].lower() if len(sys.argv) > 1 else None

    print(f"{'ATTACK':<20} {'RESULT'}")
    print("-" * 90)
    for name, fn in CHECKS.items():
        if filt and filt not in name:
            continue
        try:
            result = fn()
        except Exception as e:
            result = f"ERROR running check: {e}"
        print(f"{name:<20} {result}")


if __name__ == "__main__":
    main()
