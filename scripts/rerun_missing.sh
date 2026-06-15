#!/bin/bash
# rerun_missing.sh
# ================
# Re-runs ONLY the (approach, attack) combinations that produced 0-byte
# CSVs in the original matrix, for wls and ekf (the two approaches affected
# -- wls_huber, wls_tukey, ransac, ekf_chi2_huber all completed successfully
# for every attack per the analyser output, so they are NOT re-run here).
#
# Also runs `baseline` for ALL SIX approaches, since none currently exist
# (fig3's "No baseline data yet" panel) and your README's baseline table
# numbers come from an earlier branch -- you need fresh baseline runs
# consistent with the current EKF-loop-closure-fixed / spawn-position-fixed
# code for a like-for-like comparison.
#
# Runs cleanup_swarm.sh --check after EVERY run and ABORTS if a leak is
# detected, so you catch a regression immediately instead of silently
# corrupting the next run's CSV (the bug this whole session has been about).
#
# Usage:
#   bash rerun_missing.sh
#
# Prerequisites: start_swarm.sh already running in a separate terminal.
#                 cleanup_swarm.sh present in the same directory as
#                 run_experiment.sh (~/Dissertation/scripts/).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN="bash $SCRIPT_DIR/run_experiment.sh"
CHECK="bash $SCRIPT_DIR/cleanup_swarm.sh --check"

# (approach, attack) pairs that were 0 bytes in the original run
MISSING_RUNS=(
  "wls replay"
  "wls wormhole"
  "wls replay_gradual"
  "wls byzantine"
  "wls timesync"
  "ekf replay"
  "ekf wormhole"
  "ekf replay_gradual"
  "ekf byzantine"
  "ekf timesync"
)

# baseline runs -- none exist yet for any approach
BASELINE_RUNS=(
  "wls baseline"
  "ekf baseline"
  "wls_huber baseline"
  "wls_tukey baseline"
  "ransac baseline"
  "ekf_chi2_huber baseline"
)

ALL_RUNS=("${MISSING_RUNS[@]}" "${BASELINE_RUNS[@]}")
TOTAL=${#ALL_RUNS[@]}

echo ""
echo "============================================================"
echo "  RE-RUN PLAN: $TOTAL experiments"
echo "============================================================"
COUNT=1
for run in "${ALL_RUNS[@]}"; do
  echo "  [$COUNT/$TOTAL] $run"
  COUNT=$((COUNT + 1))
done
echo ""
echo "Estimated time: ~$((TOTAL * 2)) minutes"
echo ""

read -p "Proceed? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

PASS=0
FAIL=0
FAILED_RUNS=()
COUNT=1

for run in "${ALL_RUNS[@]}"; do
  approach=$(echo "$run" | awk '{print $1}')
  attack=$(echo "$run" | awk '{print $2}')

  echo ""
  echo "▶ [$COUNT/$TOTAL] $approach / $attack  ($(date '+%H:%M:%S'))"

  # Pre-flight check: abort early if a previous leak wasn't caught
  echo "  Pre-flight process check..."
  if ! $CHECK | grep -q "clean"; then
    echo "  WARNING: leaked processes detected before this run started."
    echo "  Running full cleanup before proceeding..."
    bash "$SCRIPT_DIR/cleanup_swarm.sh"
  fi

  if $RUN "$approach" "$attack"; then
    PASS=$((PASS + 1))
    echo "✓ [$COUNT/$TOTAL] $approach / $attack — PASSED"
  else
    FAIL=$((FAIL + 1))
    FAILED_RUNS+=("$approach/$attack")
    echo "✗ [$COUNT/$TOTAL] $approach / $attack — FAILED"
  fi

  # Post-run check: this is the critical regression guard. If this fires,
  # the SAME bug that caused the original 0-byte CSVs is recurring, and
  # the NEXT run in this loop would be corrupted too.
  echo "  Post-run process check..."
  POST_CHECK_OUT=$($CHECK)
  if echo "$POST_CHECK_OUT" | grep -q "LEAK"; then
    echo "  *** LEAK DETECTED AFTER $approach/$attack ***"
    echo "$POST_CHECK_OUT"
    echo ""
    echo "  This is the bug that caused the original 0-byte CSVs."
    echo "  cleanup_swarm.sh's escalation should have caught it inside"
    echo "  run_experiment.sh -- if you see this, run_experiment.sh has"
    echo "  NOT been patched with the cleanup_swarm.sh integration yet."
    echo "  ABORTING remaining runs to avoid corrupting them."
    break
  fi

  COUNT=$((COUNT + 1))

  if [ $COUNT -le $((TOTAL + 1)) ]; then
    echo "  Pausing 5s before next run..."
    sleep 5
  fi
done

echo ""
echo "============================================================"
echo "  RE-RUN COMPLETE"
echo "  Passed: $PASS / $TOTAL"
echo "  Failed: $FAIL"
echo "============================================================"

if [ ${#FAILED_RUNS[@]} -gt 0 ]; then
  echo ""
  echo "Failed runs:"
  for r in "${FAILED_RUNS[@]}"; do
    echo "  $r"
  done
fi

echo ""
echo "Verify with:"
echo "  ls -la ~/Dissertation/evidence/metrics/wls_px4_1*.csv"
echo "  ls -la ~/Dissertation/evidence/metrics/ekf_px4_1*.csv"
echo "  (all should now be >0 bytes)"
echo ""
echo "Then re-run the analyser:"
echo "  python3 ~/Dissertation/analyse_all_approaches.py --drone px4_1 \\"
echo "      --gt-csv ~/Dissertation/evidence/gt/gt_px4_1_wls_baseline.csv"
