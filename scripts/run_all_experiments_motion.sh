#!/bin/bash
# run_all_experiments_motion.sh
# ==============================
# Runs the full motion experiment matrix: 6 approaches × 11 attacks × pattern.
# Delegates each combination to run_experiment_motion.sh.
# Designed to produce results comparable with run_all_experiments.sh (static).
#
# Usage:
#   bash run_all_experiments_motion.sh [pattern]
#
#   pattern: hover | square | circle | all  (default: hover)
#            "all" expands to hover + square + circle for every combination.
#
# Examples:
#   bash run_all_experiments_motion.sh          # 66 runs, hover only
#   bash run_all_experiments_motion.sh hover    # same
#   bash run_all_experiments_motion.sh circle   # 66 runs, circle only
#   bash run_all_experiments_motion.sh all      # 198 runs across all patterns
#
# Resume: any combination whose 5 output CSVs already exist is skipped.
# Log:    /tmp/run_all_motion_<timestamp>.log
#
# Prerequisites:
#   start_swarm_motion.sh must already be running (swarm stays up between runs).

set +e

PATTERN_ARG=${1:-hover}

# ── Experiment matrix ─────────────────────────────────────────────────────────

APPROACHES=(
  wls
  ekf
  wls_huber
  wls_tukey
  ransac
  ekf_chi2_huber
)

# Core attacks — same as static scenario for direct comparison
ATTACKS_CORE=(
  baseline
  sybil
  replay
  wormhole
  sybil_consistent
  replay_gradual
  byzantine
  timesync
)

# Targeted EKF attacks — motion-specific additions
ATTACKS_TARGETED=(
  targeted_ramp
  targeted_osc
  targeted_two_drone
)

ATTACKS=( "${ATTACKS_CORE[@]}" "${ATTACKS_TARGETED[@]}" )

if [ "$PATTERN_ARG" = "all" ]; then
  PATTERNS=(hover square circle)
else
  PATTERNS=("$PATTERN_ARG")
fi

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPTS="$HOME/Dissertation/scripts"
METRICS="$HOME/Dissertation/evidence/metrics/motion"
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
LOGFILE="/tmp/run_all_motion_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$METRICS"

# ── Helpers ───────────────────────────────────────────────────────────────────

log() { echo "$*" | tee -a "$LOGFILE"; }

all_csvs_exist() {
  local approach=$1 attack=$2 pattern=$3
  for i in 1 2 3 4 5; do
    if [ "$attack" = "baseline" ]; then
      f="$METRICS/${approach}_px4_${i}_baseline_${pattern}.csv"
    else
      f="$METRICS/${approach}_px4_${i}_${attack}_${pattern}.csv"
    fi
    [ -f "$f" ] && [ "$(wc -l < "$f")" -gt 10 ] || return 1
  done
  return 0
}

swarm_alive() {
  source /opt/ros/humble/setup.bash > /dev/null 2>&1
  source "$WS/install/setup.bash" > /dev/null 2>&1
  local count
  count=$(ros2 topic list 2>/dev/null | grep -c "px4_[1-5]/fmu/out/vehicle_local_position" || echo 0)
  [ "${count}" -ge 5 ]
}

# ── Pre-flight check ──────────────────────────────────────────────────────────

log ""
log "╔═══════════════════════════════════════════════════════════════╗"
log "║        MOTION EXPERIMENT BATCH RUNNER                        ║"
log "╚═══════════════════════════════════════════════════════════════╝"
log ""
log "  Started : $(date)"
log "  Patterns: ${PATTERNS[*]}"
log "  Log     : $LOGFILE"
log ""

TOTAL=$(( ${#APPROACHES[@]} * ${#ATTACKS[@]} * ${#PATTERNS[@]} ))
log "  Matrix  : ${#APPROACHES[@]} approaches × ${#ATTACKS[@]} attacks × ${#PATTERNS[@]} pattern(s) = $TOTAL runs"
log ""

if ! swarm_alive; then
  log "  ERROR: Swarm is not running (px4 topics not found)."
  log "  Start it first: bash ~/Dissertation/scripts/start_swarm_motion.sh"
  exit 1
fi
log "  Swarm   : OK (all 5 drone topics active)"
log ""

# ── Main loop ─────────────────────────────────────────────────────────────────

declare -A RESULT
RUN_NUM=0
SKIPPED=0
PASSED=0
FAILED=0

for PATTERN in "${PATTERNS[@]}"; do
  for APPROACH in "${APPROACHES[@]}"; do
    for ATTACK in "${ATTACKS[@]}"; do

      RUN_NUM=$(( RUN_NUM + 1 ))
      KEY="${APPROACH}/${ATTACK}/${PATTERN}"

      log "──────────────────────────────────────────────────────────────"
      log "  [${RUN_NUM}/${TOTAL}]  ${KEY}  ($(date +%H:%M:%S))"

      # Skip if output already exists
      if all_csvs_exist "$APPROACH" "$ATTACK" "$PATTERN"; then
        log "  → SKIP (all 5 CSVs already present)"
        RESULT[$KEY]="skip"
        SKIPPED=$(( SKIPPED + 1 ))
        continue
      fi

      # Swarm health check before each run
      if ! swarm_alive; then
        log "  ERROR: Swarm died before run ${RUN_NUM}. Aborting batch."
        log "  Restart swarm then re-run — completed runs will be skipped."
        RESULT[$KEY]="fail"
        FAILED=$(( FAILED + 1 ))
        break 3
      fi

      # Run the experiment
      log "  → RUNNING..."
      bash "$SCRIPTS/run_experiment_motion.sh" "$APPROACH" "$ATTACK" "$PATTERN" \
        >> "$LOGFILE" 2>&1
      EXIT_CODE=$?

      # Validate output
      if [ $EXIT_CODE -eq 0 ] && all_csvs_exist "$APPROACH" "$ATTACK" "$PATTERN"; then
        log "  → PASS"
        RESULT[$KEY]="pass"
        PASSED=$(( PASSED + 1 ))
      else
        log "  → FAIL (exit=$EXIT_CODE — see $LOGFILE)"
        RESULT[$KEY]="fail"
        FAILED=$(( FAILED + 1 ))
      fi

      # Let drones settle before next run
      log "  Settling 20s..."
      sleep 20

    done
  done
done

# ── Summary ───────────────────────────────────────────────────────────────────

log ""
log "╔═══════════════════════════════════════════════════════════════╗"
log "║  BATCH COMPLETE  $(date +'%H:%M:%S %d-%b-%Y')"
log "║  Passed: $PASSED   Skipped: $SKIPPED   Failed: $FAILED   Total: $TOTAL"
log "╚═══════════════════════════════════════════════════════════════╝"
log ""

for PATTERN in "${PATTERNS[@]}"; do
  log "  Pattern=$PATTERN"
  log ""

  # Header row
  printf "    %-16s" "" | tee -a "$LOGFILE"
  for ATTACK in "${ATTACKS[@]}"; do
    printf " %-16s" "$ATTACK" | tee -a "$LOGFILE"
  done
  echo "" | tee -a "$LOGFILE"

  for APPROACH in "${APPROACHES[@]}"; do
    printf "    %-16s" "$APPROACH" | tee -a "$LOGFILE"
    for ATTACK in "${ATTACKS[@]}"; do
      STATUS="${RESULT[${APPROACH}/${ATTACK}/${PATTERN}]:-?}"
      case $STATUS in
        pass) printf " %-16s" "pass" ;;
        skip) printf " %-16s" "skip" ;;
        fail) printf " %-16s" "FAIL" ;;
        *)    printf " %-16s" "?" ;;
      esac | tee -a "$LOGFILE"
    done
    echo "" | tee -a "$LOGFILE"
  done
  echo "" | tee -a "$LOGFILE"
done

log "  CSVs : $METRICS/"
log "  Log  : $LOGFILE"
log ""

if [ $FAILED -gt 0 ]; then
  log "  Some runs failed. Fix the issue and re-run — passing runs are skipped."
fi
