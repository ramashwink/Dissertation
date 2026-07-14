#!/bin/bash
# motion_overnight_chain.sh
# ==========================
# Waits for a running motion_watchdog.sh (supervising run_all_experiments_motion.sh)
# to reach a terminal state, then kicks off motion_validate_and_rerun.sh so the
# whole night is: sweep -> (stall/crash auto-recovery via watchdog) -> stricter
# CSV validation -> auto-rerun any combo that's missing or thin -> re-validate,
# looping until clean or a rerun-pass cap is hit.
#
# Usage: bash motion_overnight_chain.sh <watchdog_pid> <pattern>

set -u

WATCHDOG_PID=$1
PATTERN=${2:-hover}
CHAINLOG="$HOME/Dissertation/logs/motion_runs/overnight_chain_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$(dirname "$CHAINLOG")"
clog() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$CHAINLOG"; }

clog "Chain started. Waiting for watchdog PID $WATCHDOG_PID to exit..."

while kill -0 "$WATCHDOG_PID" 2>/dev/null; do
  sleep 30
done

clog "Watchdog (PID $WATCHDOG_PID) has exited — sweep reached a terminal state."
clog "Starting validate-and-rerun pass..."

bash "$HOME/Dissertation/scripts/motion_validate_and_rerun.sh" "$PATTERN" 3 >> "$CHAINLOG" 2>&1

clog "Validate-and-rerun finished. Chain complete."
