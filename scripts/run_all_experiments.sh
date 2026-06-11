#!/bin/bash
# run_all_experiments.sh
# ======================
# Runs all 6 approaches × 4 conditions sequentially using run_experiment.sh.
# Each run is fully isolated — separate tmux session, CSVs renamed after each.
#
# Total time: ~24 runs × ~2 min each = ~48 minutes unattended.
#
# Usage:
#   # Full matrix (all 24):
#   bash scripts/run_all_experiments.sh
#
#   # Single approach only (4 conditions):
#   bash scripts/run_all_experiments.sh wls_huber
#
#   # Single approach + single attack:
#   bash scripts/run_all_experiments.sh wls_huber sybil
#
# Prerequisites:
#   - start_swarm.sh already running in a separate terminal
#   - XRCE-DDS agent running
#   - Workspace built and sourced

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN="bash $SCRIPT_DIR/run_experiment.sh"

FILTER_APPROACH=${1:-}
FILTER_ATTACK=${2:-}

APPROACHES=("wls" "ekf" "wls_huber" "wls_tukey" "ransac" "ekf_chi2_huber")
ATTACKS=("baseline" "sybil" "replay" "wormhole")

# Build list of runs to execute
RUNS=()
for approach in "${APPROACHES[@]}"; do
  for attack in "${ATTACKS[@]}"; do
    # Apply filters if provided
    if [ -n "$FILTER_APPROACH" ] && [ "$approach" != "$FILTER_APPROACH" ]; then
      continue
    fi
    if [ -n "$FILTER_ATTACK" ] && [ "$attack" != "$FILTER_ATTACK" ]; then
      continue
    fi
    RUNS+=("$approach $attack")
  done
done

TOTAL=${#RUNS[@]}
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         DISSERTATION EXPERIMENT MATRIX               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Total runs: $TOTAL"
echo "║  Estimated time: ~$((TOTAL * 2)) minutes"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Planned runs:"
COUNT=1
for run in "${RUNS[@]}"; do
  echo "  [$COUNT/$TOTAL] $run"
  COUNT=$((COUNT + 1))
done
echo ""

# Confirm before starting
read -p "Start all $TOTAL experiments? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# ── Execute all runs ──────────────────────────────────────────────────────────
PASS=0
FAIL=0
FAILED_RUNS=()

START_ALL=$(date +%s)
COUNT=1

for run in "${RUNS[@]}"; do
  approach=$(echo $run | awk '{print $1}')
  attack=$(echo $run | awk '{print $2}')

  echo ""
  echo "▶ [$COUNT/$TOTAL] Starting: $approach / $attack  ($(date '+%H:%M:%S'))"
  echo ""

  if $RUN "$approach" "$attack"; then
    PASS=$((PASS + 1))
    echo "✓ [$COUNT/$TOTAL] $approach / $attack — PASSED"
  else
    FAIL=$((FAIL + 1))
    FAILED_RUNS+=("$approach/$attack")
    echo "✗ [$COUNT/$TOTAL] $approach / $attack — FAILED (continuing)"
  fi

  COUNT=$((COUNT + 1))

  # Brief pause between runs to let OS settle
  if [ $COUNT -le $TOTAL ]; then
    echo "  Pausing 5s before next run..."
    sleep 5
  fi
done

END_ALL=$(date +%s)
ELAPSED=$(( (END_ALL - START_ALL) / 60 ))

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              ALL EXPERIMENTS COMPLETE                ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Total:   $TOTAL runs"
echo "║  Passed:  $PASS"
echo "║  Failed:  $FAIL"
echo "║  Time:    ~${ELAPSED} minutes"
echo "╚══════════════════════════════════════════════════════╝"

if [ ${#FAILED_RUNS[@]} -gt 0 ]; then
  echo ""
  echo "Failed runs (re-run individually):"
  for r in "${FAILED_RUNS[@]}"; do
    ap=$(echo $r | cut -d/ -f1)
    at=$(echo $r | cut -d/ -f2)
    echo "  bash scripts/run_experiment.sh $ap $at"
  done
fi

echo ""
echo "Run analyser for all drones:"
GT="$HOME/Dissertation/evidence/gt"
for drone in px4_1 px4_2 px4_3 px4_4 px4_5; do
  echo "  python3 ~/Dissertation/analyse_all_approaches.py \\"
  echo "      --drone $drone \\"
  echo "      --gt-csv ${GT}/gt_${drone}_wls_baseline.csv"
done
