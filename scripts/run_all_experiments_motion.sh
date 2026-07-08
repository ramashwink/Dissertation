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

# gz sim's Ruby launcher has been observed to crash (SIGABRT) under sustained
# load, killing the physics server while PX4/DDS stay up — swarm_alive() alone
# won't catch that until topics drop out. Full cleanup + relaunch recovers it.
MAX_TOTAL_RESTARTS=60
RESTART_COUNT=0

restart_swarm() {
  RESTART_COUNT=$(( RESTART_COUNT + 1 ))
  if [ "$RESTART_COUNT" -gt "$MAX_TOTAL_RESTARTS" ]; then
    log "  [restart] Exceeded ${MAX_TOTAL_RESTARTS} total restarts — something is"
    log "  [restart] fundamentally broken. Refusing to restart again."
    return 1
  fi

  log "  [restart] (${RESTART_COUNT}/${MAX_TOTAL_RESTARTS}) Killing stale processes..."
  tmux kill-server 2>/dev/null || true
  pkill -9 -f "bin/px4" 2>/dev/null || true
  pkill -9 -f "MicroXRCEAgent" 2>/dev/null || true
  pkill -9 -f "gz sim" 2>/dev/null || true
  pkill -9 -f "swarm_viz" 2>/dev/null || true
  pkill -9 -f "formation_flight" 2>/dev/null || true
  pkill -9 -f "coop_loc" 2>/dev/null || true
  pkill -9 -f "ground_truth_demux" 2>/dev/null || true
  pkill -9 -f "inter_drone_ranging" 2>/dev/null || true
  pkill -9 -f "swarm_registry" 2>/dev/null || true
  pkill -9 -f "swarm_heartbeat" 2>/dev/null || true
  sleep 3
  rm -rf /tmp/px4_* /tmp/px4-sock-* /tmp/px4_lock-* 2>/dev/null

  local restart_log="/tmp/swarm_restart_$(date +%s).log"
  log "  [restart] Launching start_swarm_motion.sh (log: $restart_log)..."
  nohup bash "$SCRIPTS/start_swarm_motion.sh" > "$restart_log" 2>&1 &

  local waited=0
  while [ "$waited" -lt 150 ]; do
    if grep -q "RC-PARAMS\] Done" "$restart_log" 2>/dev/null; then
      log "  [restart] Swarm ready after ${waited}s."
      return 0
    fi
    sleep 3
    waited=$(( waited + 3 ))
  done

  log "  [restart] TIMEOUT waiting for swarm to become ready (${restart_log})."
  return 1
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

      # Full swarm restart before every run. Gazebo pose-teleport alone
      # (reset_swarm_poses) doesn't reset PX4's own EKF/control state, so a
      # drone that drifted during a previous run keeps fighting the physical
      # teleport in the next one — a fresh PX4+Gazebo boot is the only way to
      # guarantee both correct spawn pose and a clean flight-control state.
      log "  Restarting swarm for a clean run..."
      if ! restart_swarm; then
        log "  ERROR: Swarm restart failed. Aborting batch."
        RESULT[$KEY]="fail"
        FAILED=$(( FAILED + 1 ))
        break 3
      fi

      # Run the experiment — retry once if the swarm crashes mid-run
      COMBO_STATUS="fail"
      for ATTEMPT in 1 2; do
        log "  → RUNNING (attempt ${ATTEMPT})..."
        bash "$SCRIPTS/run_experiment_motion.sh" "$APPROACH" "$ATTACK" "$PATTERN" \
          >> "$LOGFILE" 2>&1
        EXIT_CODE=$?

        if [ $EXIT_CODE -eq 0 ] && all_csvs_exist "$APPROACH" "$ATTACK" "$PATTERN"; then
          COMBO_STATUS="pass"
          break
        fi

        if ! swarm_alive; then
          log "  Swarm died mid-run (attempt ${ATTEMPT}) — auto-restarting..."
          if ! restart_swarm; then
            log "  ERROR: Swarm auto-restart failed after mid-run crash."
            break
          fi
          log "  Swarm restarted — retrying this combination."
        else
          log "  Run failed but swarm still alive — not a crash, not retrying."
          break
        fi
      done

      if [ "$COMBO_STATUS" = "pass" ]; then
        log "  → PASS"
        RESULT[$KEY]="pass"
        PASSED=$(( PASSED + 1 ))
      else
        log "  → FAIL (see $LOGFILE)"
        RESULT[$KEY]="fail"
        FAILED=$(( FAILED + 1 ))
      fi

      # PX4 console logs in /tmp grow fast under retry/failsafe spam (observed
      # ~30MB/min) — truncate in place between runs to keep disk usage bounded
      # over a long unattended batch. Safe on an open fd: writes continue from
      # the process's current offset, the file just becomes sparse up to there.
      truncate -s 0 /tmp/px4_1.log /tmp/px4_2.log /tmp/px4_3.log /tmp/px4_4.log /tmp/px4_5.log 2>/dev/null || true

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
