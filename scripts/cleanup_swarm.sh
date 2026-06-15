#!/bin/bash
# cleanup_swarm.sh
# ================
# Hardened process cleanup for the dissertation experiment pipeline.
#
# PROBLEM THIS FIXES:
#   run_experiment.sh's step 0 / step 6 cleanup does `tmux kill-server`
#   followed by a list of `pkill -f <pattern>` calls. When tmux panes run
#   `cmd1 & cmd2 & cmd3 & wait`, killing the tmux server SIGHUPs the pane's
#   shell -- but the backgrounded children (cmd1/cmd2/cmd3) can be reparented
#   to PID 1 and SURVIVE as orphans if they don't also receive SIGHUP/SIGTERM
#   (depends on job control settings / whether `set -m` or `disown` is in
#   effect, and on timing races between tmux's kill and the shell's own exit).
#
#   Symptom: in a long run_all_experiments.sh matrix, the FIRST 1-2 runs
#   produce populated CSVs (wls_pxN_sybil.csv: 35KB), but every SUBSEQUENT
#   run produces 0-byte CSVs (wls_pxN_replay.csv, wls_pxN_wormhole.csv, ...)
#   -- because an orphaned coop_loc_logger.py / coop_loc_dynamic / etc. from
#   run N is still alive when run N+1 starts, causing file-truncation races
#   and/or topic-subscription conflicts that result in zero rows logged.
#
# WHAT THIS SCRIPT DOES:
#   1. tmux kill-server (as before)
#   2. pkill -f for every known long-lived node pattern (as before)
#   3. NEW: a verification pass that lists any surviving matches, and a
#      SIGKILL (-9) escalation if processes are still alive after the
#      normal pkill (which sends SIGTERM and can be ignored/slow to land).
#   4. NEW: prints a clear PASS/FAIL so you can spot a leak immediately
#      instead of discovering it 90 seconds into the next experiment.
#
# USAGE:
#   bash cleanup_swarm.sh           # run cleanup, print verification
#   bash cleanup_swarm.sh --check   # ONLY check, do not kill anything
#
# Call this in place of (or in addition to) the existing cleanup blocks in
# run_experiment.sh, both at step [0/6] (before launching) and step [6/6]
# (after data collection).

PATTERNS=(
  "coop_loc"
  "ground_truth_demux"
  "inter_drone_ranging"
  "swarm_registry"
  "swarm_heartbeat"
  "swarm_client"
  "extract_ground_truth"
  "sybil_registry_attack"
  "sybil_service_attack"
  "sybil_consistent_attack"
  "replay_attack"
  "replay_attack_gradual"
  "wormhole_attack"
  "byzantine_insider_attack"
  "timesync_attack"
  "ekf_attack_logger"
  "swarm_viz"
)

CHECK_ONLY=0
if [ "$1" == "--check" ]; then
  CHECK_ONLY=1
fi

count_matches() {
  local pattern="$1"
  pgrep -f "$pattern" 2>/dev/null | wc -l
}

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "=== Process check (no killing) ==="
  any=0
  for p in "${PATTERNS[@]}"; do
    n=$(count_matches "$p")
    if [ "$n" -gt 0 ]; then
      any=1
      echo "  LEAK  $p : $n process(es)"
      pgrep -af "$p"
    fi
  done
  if [ "$any" -eq 0 ]; then
    echo "  clean -- no matching processes found"
  fi
  echo ""
  echo "=== tmux sessions ==="
  tmux list-sessions 2>/dev/null || echo "  (none)"
  exit 0
fi

echo "[cleanup] Killing tmux server..."
tmux kill-server 2>/dev/null || true
sleep 1

echo "[cleanup] First pass: pkill (SIGTERM)..."
for p in "${PATTERNS[@]}"; do
  pkill -f "$p" 2>/dev/null || true
done
sleep 2

echo "[cleanup] Verification pass..."
leaked=0
for p in "${PATTERNS[@]}"; do
  n=$(count_matches "$p")
  if [ "$n" -gt 0 ]; then
    leaked=1
    echo "  STILL ALIVE  $p : $n process(es) -- escalating to SIGKILL"
    pkill -9 -f "$p" 2>/dev/null || true
  fi
done

if [ "$leaked" -eq 1 ]; then
  sleep 1
  echo "[cleanup] Final verification after SIGKILL..."
  still_bad=0
  for p in "${PATTERNS[@]}"; do
    n=$(count_matches "$p")
    if [ "$n" -gt 0 ]; then
      still_bad=1
      echo "  FAIL  $p : $n process(es) survived SIGKILL -- manual intervention needed"
      pgrep -af "$p"
    fi
  done
  if [ "$still_bad" -eq 0 ]; then
    echo "[cleanup] PASS (after SIGKILL escalation) -- previous run had orphans, now clean"
  else
    echo "[cleanup] FAIL -- some processes survived SIGKILL. Check for zombie/D-state:"
    echo "          ps aux | grep -E '$(IFS=\|; echo "${PATTERNS[*]}")'"
    exit 1
  fi
else
  echo "[cleanup] PASS -- clean on first pass, no orphans detected"
fi

echo ""
echo "=== tmux sessions remaining ==="
tmux list-sessions 2>/dev/null || echo "  (none)"
