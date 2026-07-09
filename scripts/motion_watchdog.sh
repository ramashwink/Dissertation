#!/bin/bash
# motion_watchdog.sh
# ===================
# Supervises run_all_experiments_motion.sh for the overnight unattended run.
# The batch script's own swarm_alive() only checks that ROS topics exist, not
# that they're actively updating — so a frozen-but-still-connected Gazebo
# crash (SIGABRT under sustained load, a documented issue in this repo) can
# hang the batch indefinitely with no self-heal, as happened at 16:53 tonight.
#
# This watches wall-clock progress on the batch log: if it goes silent for
# too long, assume a hang, kill everything, reboot the swarm, and relaunch
# the batch (its own resume/skip logic picks up where it left off).
#
# Usage: bash motion_watchdog.sh <batch_logfile> <pattern>

set -u

LOGFILE=${1:-/tmp/run_all_motion_clean2.log}
PATTERN=${2:-hover}
STALL_SEC=480          # 8 minutes of no new log lines = assume hung
CHECK_INTERVAL=30
MAX_RESTARTS=12
WATCHDOG_LOG="$HOME/Dissertation/logs/motion_runs/watchdog_$(date +%Y%m%d).log"

mkdir -p "$(dirname "$WATCHDOG_LOG")"
wlog() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$WATCHDOG_LOG"; }

restarts=0
wlog "Watchdog started. Watching $LOGFILE (stall threshold ${STALL_SEC}s)"

while true; do
  sleep "$CHECK_INTERVAL"

  if [ ! -f "$LOGFILE" ]; then
    wlog "Log file missing — batch not running. Watchdog exiting."
    break
  fi

  now=$(date +%s)
  last_mod=$(stat -c %Y "$LOGFILE" 2>/dev/null || echo "$now")
  idle=$(( now - last_mod ))

  # Also check the batch script process is actually still alive
  batch_alive=$(pgrep -f "run_all_experiments_motion.sh" | wc -l)

  if grep -q "BATCH COMPLETE" "$LOGFILE"; then
    wlog "BATCH COMPLETE detected. Watchdog exiting cleanly."
    break
  fi

  if [ "$idle" -lt "$STALL_SEC" ] && [ "$batch_alive" -gt 0 ]; then
    continue
  fi

  # Stalled or the batch process died outright
  if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
    wlog "Hit MAX_RESTARTS ($MAX_RESTARTS) — giving up, leaving for manual review."
    break
  fi

  restarts=$(( restarts + 1 ))
  wlog "STALL DETECTED (idle=${idle}s, batch_alive=${batch_alive}). Restart #${restarts}/${MAX_RESTARTS}."
  wlog "  Last log lines before restart:"
  tail -5 "$LOGFILE" | while read -r l; do wlog "    $l"; done

  wlog "  Killing everything..."
  pkill -9 -f "run_all_experiments_motion.sh" 2>/dev/null
  pkill -9 -f "run_experiment_motion.sh" 2>/dev/null
  pkill -9 -f "bin/px4" 2>/dev/null
  pkill -9 -f "MicroXRCEAgent" 2>/dev/null
  pkill -9 -f "gz sim" 2>/dev/null
  pkill -9 -f "arm_all_drones" 2>/dev/null
  tmux kill-server 2>/dev/null
  sleep 5

  wlog "  Booting fresh swarm..."
  SWARM_LOG="/tmp/watchdog_swarm_restart_$(date +%s).log"
  bash "$HOME/Dissertation/scripts/start_swarm_motion.sh" > "$SWARM_LOG" 2>&1 &
  swarm_pid=$!

  waited=0
  while [ "$waited" -lt 90 ]; do
    if grep -q "SWARM READY" "$SWARM_LOG" 2>/dev/null; then
      break
    fi
    sleep 3
    waited=$(( waited + 3 ))
  done

  if ! grep -q "SWARM READY" "$SWARM_LOG" 2>/dev/null; then
    wlog "  Swarm failed to come up within 90s (see $SWARM_LOG). Will retry next cycle."
    continue
  fi
  wlog "  Swarm ready after ${waited}s."

  wlog "  Relaunching batch (resume logic will skip completed combos)..."
  nohup bash "$HOME/Dissertation/scripts/run_all_experiments_motion.sh" "$PATTERN" >> "$LOGFILE" 2>&1 &
  disown
  wlog "  Batch relaunched, PID $!."
  sleep 10
done

wlog "Watchdog stopped."
