#!/bin/bash
# motion_validate_and_rerun.sh
# =============================
# Runs after run_all_experiments_motion.sh + motion_watchdog.sh finish. The
# batch script's own pass/fail check is lenient (>10 rows) and does not retry
# a combo that completed without crashing but produced thin data (e.g. 8-10
# rows over a 90s window) — it just moves on and marks it FAIL forever. This
# script closes that gap: it runs validate_motion_csvs.py's stricter
# time-span/density check, deletes the CSVs for any combo that fails it, and
# re-runs just those combos (each with a full clean swarm restart first, same
# as the main batch), looping until everything passes or MAX_PASSES is hit.
#
# Usage: bash motion_validate_and_rerun.sh [pattern] [max_passes]

set -u

PATTERN=${1:-hover}
MAX_PASSES=${2:-3}

SCRIPTS="$HOME/Dissertation/scripts"
METRICS="$HOME/Dissertation/evidence/metrics/motion"
GT="$HOME/Dissertation/evidence/gt/motion"
METRICS_THIN="$HOME/Dissertation/evidence/metrics/motion_thin_backup"
GT_THIN="$HOME/Dissertation/evidence/gt/motion_thin_backup"
VALIDATE="$HOME/Dissertation/validate_motion_csvs.py"
LOGFILE="$HOME/Dissertation/logs/motion_runs/validate_rerun_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$METRICS_THIN" "$GT_THIN"

mkdir -p "$(dirname "$LOGFILE")"
log() { echo "$*" | tee -a "$LOGFILE"; }

log ""
log "╔═══════════════════════════════════════════════════════════════╗"
log "║        MOTION CSV VALIDATE + AUTO-RERUN                       ║"
log "╚═══════════════════════════════════════════════════════════════╝"
log "  Started : $(date)"
log "  Pattern : $PATTERN"
log "  Max passes: $MAX_PASSES"
log ""

restart_swarm() {
  log "    [restart] Killing stale processes..."
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

  local restart_log="/tmp/validate_rerun_swarm_$(date +%s).log"
  log "    [restart] Launching start_swarm_motion.sh (log: $restart_log)..."
  nohup bash "$SCRIPTS/start_swarm_motion.sh" > "$restart_log" 2>&1 &

  local waited=0
  while [ "$waited" -lt 150 ]; do
    if grep -q "RC-PARAMS\] Done" "$restart_log" 2>/dev/null; then
      log "    [restart] Swarm ready after ${waited}s."
      return 0
    fi
    sleep 3
    waited=$(( waited + 3 ))
  done
  log "    [restart] TIMEOUT waiting for swarm (${restart_log})."
  return 1
}

swarm_alive() {
  source /opt/ros/humble/setup.bash > /dev/null 2>&1
  source "$HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash" > /dev/null 2>&1
  export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
  local count
  count=$(ros2 topic list 2>/dev/null | grep -c "px4_[1-5]/fmu/out/vehicle_local_position")
  [ "${count}" -ge 5 ]
}

# One "approach attack" pair per line, deduped across drones.
get_bad_combos() {
  python3 "$VALIDATE" --pattern "$PATTERN" --combos-only 2>/dev/null
}

PASS_NUM=0
while [ "$PASS_NUM" -lt "$MAX_PASSES" ]; do
  PASS_NUM=$(( PASS_NUM + 1 ))
  log "──────────────────────────────────────────────────────────────"
  log "  Validation pass ${PASS_NUM}/${MAX_PASSES} ($(date +%H:%M:%S))"

  mapfile -t BAD_COMBOS < <(get_bad_combos)

  if [ "${#BAD_COMBOS[@]}" -eq 0 ]; then
    log "  All combos pass the stricter validation check. Done."
    break
  fi

  log "  ${#BAD_COMBOS[@]} combo(s) need a rerun:"
  for combo in "${BAD_COMBOS[@]}"; do
    log "    - $combo"
  done

  for combo in "${BAD_COMBOS[@]}"; do
    APPROACH=$(echo "$combo" | awk '{print $1}')
    ATTACK=$(echo "$combo" | awk '{print $2}')
    [ -z "$APPROACH" ] || [ -z "$ATTACK" ] && continue

    log ""
    log "  Rerunning ${APPROACH}/${ATTACK}/${PATTERN}..."

    # Move (never delete) the existing thin/bad CSVs into a backup folder,
    # tagged with the pass number so repeated attempts at the same combo don't
    # overwrite each other — if every rerun still comes out thin, the original
    # and every intermediate attempt are still there to fall back on.
    for i in 1 2 3 4 5; do
      mf="$METRICS/${APPROACH}_px4_${i}_${ATTACK}_${PATTERN}.csv"
      gf="$GT/gt_px4_${i}_${APPROACH}_${ATTACK}_${PATTERN}.csv"
      [ -f "$mf" ] && mv "$mf" "$METRICS_THIN/pass${PASS_NUM}_$(basename "$mf")"
      [ -f "$gf" ] && mv "$gf" "$GT_THIN/pass${PASS_NUM}_$(basename "$gf")"
    done

    if ! swarm_alive; then
      log "  Swarm not alive before rerun — restarting..."
      restart_swarm || { log "  ERROR: swarm restart failed, skipping this combo this pass."; continue; }
    else
      log "  Restarting swarm for a clean rerun..."
      restart_swarm || { log "  ERROR: swarm restart failed, skipping this combo this pass."; continue; }
    fi

    for ATTEMPT in 1 2; do
      log "  → RUNNING (attempt ${ATTEMPT})..."
      bash "$SCRIPTS/run_experiment_motion.sh" "$APPROACH" "$ATTACK" "$PATTERN" >> "$LOGFILE" 2>&1
      EXIT_CODE=$?

      if [ $EXIT_CODE -eq 0 ]; then
        break
      fi

      if ! swarm_alive; then
        log "  Swarm died mid-rerun (attempt ${ATTEMPT}) — restarting..."
        restart_swarm || { log "  ERROR: swarm restart failed."; break; }
      else
        log "  Rerun exited non-zero but swarm alive — not retrying further this pass."
        break
      fi
    done

    truncate -s 0 /tmp/px4_1.log /tmp/px4_2.log /tmp/px4_3.log /tmp/px4_4.log /tmp/px4_5.log 2>/dev/null || true
    log "  Settling 20s..."
    sleep 20
  done
done

if [ "$PASS_NUM" -ge "$MAX_PASSES" ]; then
  mapfile -t REMAINING < <(get_bad_combos)
  if [ "${#REMAINING[@]}" -gt 0 ]; then
    log ""
    log "  Hit MAX_PASSES (${MAX_PASSES}) with ${#REMAINING[@]} combo(s) still failing validation:"
    for combo in "${REMAINING[@]}"; do
      log "    - $combo"
    done
    log "  Leaving these for manual review — see $LOGFILE"
  fi
fi

log ""
log "╔═══════════════════════════════════════════════════════════════╗"
log "║  VALIDATE + RERUN COMPLETE  $(date +'%H:%M:%S %d-%b-%Y')"
log "╚═══════════════════════════════════════════════════════════════╝"
