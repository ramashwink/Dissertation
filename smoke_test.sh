#!/bin/bash
# smoke_test.sh
# =============
# Fast iteration harness for tuning attack parameters without paying the
# full ~110s (WARMUP_SEC + EXPERIMENT_SEC) cost of run_experiment.sh.
#
# Brings up sensing + discovery + ONE localisation approach (default:
# ekf_chi2_huber, since it's the dissertation's primary mitigation and
# exercises chi2 gating against every attack), then runs the chosen attack
# for a SHORT window using the SMOKE_* env var overrides added to each
# patched attack script.
#
# After the run, immediately invokes validate_attacks.py so you get a
# PASS/SUSPECT/FAIL verdict on whether the attack actually fired, without
# needing to inspect the CSV by hand.
#
# Usage:
#   bash smoke_test.sh <attack> [attack_args...]
#
# Examples:
#   bash smoke_test.sh wormhole 0.05
#   bash smoke_test.sh byzantine px4_2 0.8
#   bash smoke_test.sh sybil_consistent 3 px4_2
#   bash smoke_test.sh replay_gradual 0.1 30
#   bash smoke_test.sh timesync ancient
#   bash smoke_test.sh sybil 3 px4_2
#   bash smoke_test.sh replay delayed
#
# Optional overrides (env vars, all default to short values for smoke runs):
#   SMOKE_APPROACH=ekf_chi2_huber   # which of the 6 localisation approaches to run
#   SMOKE_WARMUP_SEC=5              # stack settle time before attack starts
#   SMOKE_ATTACK_SEC=20             # total attack-node runtime (incl. its own warmup)
#   SMOKE_RAMP_SEC=10               # ramp duration (sybil/byzantine/registry attacks)
#   SMOKE_DELAY_SEC=2               # replay delay (replay_attack only)
#
# Prerequisites: start_swarm.sh already running in a separate terminal.
#
# What this does NOT do (by design, for speed):
#   - Does not run extract_ground_truth.py (no GT-based error figures)
#   - Does not rename/archive CSVs -- they land at the normal /tmp/*_metrics.csv
#     and evidence/metrics/<approach>_pxN.csv paths, OVERWRITING any previous
#     smoke-test output. Run a full run_experiment.sh pass once you're happy
#     with parameters, to get a properly-archived result.

set -e

ATTACK=${1:-}
shift || true
ATTACK_ARGS="$@"

if [ -z "$ATTACK" ]; then
  echo "Usage: bash smoke_test.sh <attack> [attack_args...]"
  echo ""
  echo "Attacks: sybil | sybil_consistent | replay | replay_gradual | "
  echo "         wormhole | byzantine | timesync"
  exit 1
fi

# ── Config (overridable) ──────────────────────────────────────────────────────
SMOKE_APPROACH=${SMOKE_APPROACH:-ekf_chi2_huber}
export SMOKE_WARMUP_SEC=${SMOKE_WARMUP_SEC:-5}
export SMOKE_ATTACK_SEC=${SMOKE_ATTACK_SEC:-20}
export SMOKE_RAMP_SEC=${SMOKE_RAMP_SEC:-10}
export SMOKE_DELAY_SEC=${SMOKE_DELAY_SEC:-2}

# ── Map approach -> script (mitigation algos are direct python scripts) ────────
declare -A SCRIPT_MAP=(
  [wls]="cooperative_localisation_dynamic.py"
  [ekf]="cooperative_localisation_ekf.py"
  [wls_huber]="coop_loc_wls_huber.py"
  [wls_tukey]="coop_loc_wls_tukey.py"
  [ransac]="coop_loc_ransac.py"
  [ekf_chi2_huber]="coop_loc_ekf_chi2_huber.py"
)
declare -A ROS2_NODE_MAP=(
  [wls]="coop_loc_dynamic"
  [ekf]="coop_loc_ekf"
  [wls_huber]=""
  [wls_tukey]=""
  [ransac]=""
  [ekf_chi2_huber]=""
)
declare -A ATTACK_NODE_MAP=(
  [sybil]="sybil_registry_attack"
  [sybil_consistent]="sybil_consistent_attack"
  [replay]="replay_attack"
  [replay_gradual]="replay_attack_gradual"
  [wormhole]="wormhole_attack"
  [byzantine]="byzantine_insider_attack"
  [timesync]="timesync_attack"
)

# Key used to filter validate_attacks.py's CHECKS dict (must be specific
# enough not to also match unrelated attacks -- e.g. "sybil" alone matches
# sybil_registry, sybil_service AND sybil_consistent in validate_attacks.py,
# producing noisy MISSING lines for the other two).
declare -A VALIDATOR_KEY_MAP=(
  [sybil]="sybil_registry"
  [sybil_consistent]="sybil_consistent"
  [replay]="replay"                 # NOTE: also matches "replay_gradual" check
                                     # in validate_attacks.py (harmless -- both
                                     # are real attacks; the gradual one will
                                     # just show MISSING if not run)
  [replay_gradual]="replay_gradual"
  [wormhole]="wormhole"
  [byzantine]="byzantine"
  [timesync]="timesync"
)

ATTACK_NODE=${ATTACK_NODE_MAP[$ATTACK]}
if [ -z "$ATTACK_NODE" ]; then
  echo "Unknown attack: '$ATTACK'"
  echo "Choose from: ${!ATTACK_NODE_MAP[@]}"
  exit 1
fi
VALIDATOR_KEY=${VALIDATOR_KEY_MAP[$ATTACK]}

SCRIPT=${SCRIPT_MAP[$SMOKE_APPROACH]}
if [ -z "$SCRIPT" ]; then
  echo "Unknown SMOKE_APPROACH: '$SMOKE_APPROACH'"
  echo "Choose from: ${!SCRIPT_MAP[@]}"
  exit 1
fi

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
CODE="$HOME/Dissertation/code"
SCRIPT_PATH="$PKG/$SCRIPT"
SESSION="smoke_${ATTACK}_${SMOKE_APPROACH}"

SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

echo ""
echo "============================================================"
echo "  SMOKE TEST: attack=$ATTACK ($ATTACK_NODE $ATTACK_ARGS)"
echo "              approach=$SMOKE_APPROACH"
echo "  SMOKE_WARMUP_SEC=$SMOKE_WARMUP_SEC  SMOKE_ATTACK_SEC=$SMOKE_ATTACK_SEC"
echo "  SMOKE_RAMP_SEC=$SMOKE_RAMP_SEC      SMOKE_DELAY_SEC=$SMOKE_DELAY_SEC"
echo "============================================================"
echo ""

# ── Cleanup any leftovers ────────────────────────────────────────────────────
echo "[0/4] Cleaning up leftover processes..."
tmux kill-session -t "$SESSION" 2>/dev/null || true
pkill -f "coop_loc"            2>/dev/null || true
pkill -f "ground_truth_demux"  2>/dev/null || true
pkill -f "inter_drone_ranging" 2>/dev/null || true
pkill -f "swarm_registry"      2>/dev/null || true
pkill -f "swarm_heartbeat"     2>/dev/null || true
pkill -f "${ATTACK_NODE}"      2>/dev/null || true
sleep 1
echo "    Done."

# ── Launch sensing + discovery + algorithm ───────────────────────────────────
echo "[1/4] Starting sensing + discovery + ${SMOKE_APPROACH}..."
tmux new-session -d -s "$SESSION" -x 220 -y 50 -n sensing
tmux send-keys -t "$SESSION:sensing" "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t "$SESSION:sensing"
tmux send-keys -t "$SESSION:sensing" "$SRC && sleep 2 && python3 $CODE/inter_drone_ranging.py" Enter

tmux new-window -t "$SESSION" -n discovery
tmux send-keys -t "$SESSION:discovery" "$SRC && ros2 run swarm_discovery swarm_registry" Enter
tmux split-window -v -t "$SESSION:discovery"
tmux send-keys -t "$SESSION:discovery" \
  "$SRC && sleep 2 && \
  ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 & wait" Enter

tmux new-window -t "$SESSION" -n algorithm
ROS2_NODE=${ROS2_NODE_MAP[$SMOKE_APPROACH]}
if [ -n "$ROS2_NODE" ]; then
  tmux send-keys -t "$SESSION:algorithm" \
    "$SRC && sleep 4 && \
    ros2 run swarm_discovery ${ROS2_NODE} px4_1 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_2 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_3 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_4 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_5 & wait" Enter
else
  tmux send-keys -t "$SESSION:algorithm" \
    "$SRC && sleep 4 && \
    python3 $SCRIPT_PATH px4_1 & \
    python3 $SCRIPT_PATH px4_2 & \
    python3 $SCRIPT_PATH px4_3 & \
    python3 $SCRIPT_PATH px4_4 & \
    python3 $SCRIPT_PATH px4_5 & wait" Enter
fi

echo "    Waiting ${SMOKE_WARMUP_SEC}s for stack to stabilise..."
sleep "$SMOKE_WARMUP_SEC"

# ── Inject attack (foreground, blocks until SMOKE_ATTACK_SEC elapses) ────────
echo "[2/4] Running attack node (~${SMOKE_ATTACK_SEC}s)..."
tmux new-window -t "$SESSION" -n attack
tmux send-keys -t "$SESSION:attack" \
  "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARGS}" Enter

# Wait for the attack's own ATTACK_SEC (it self-terminates and flushes its CSV)
# plus a small buffer for the CSV close() to land.
WAIT_TOTAL=$(( ${SMOKE_ATTACK_SEC%.*} + 3 ))
echo "    Waiting ${WAIT_TOTAL}s for attack node to self-terminate and flush CSV..."
sleep "$WAIT_TOTAL"

# ── Tear down ──────────────────────────────────────────────────────────────
echo "[3/4] Stopping stack..."
tmux kill-session -t "$SESSION" 2>/dev/null || true
pkill -f "coop_loc"            2>/dev/null || true
pkill -f "ground_truth_demux"  2>/dev/null || true
pkill -f "inter_drone_ranging" 2>/dev/null || true
pkill -f "swarm_registry"      2>/dev/null || true
pkill -f "swarm_heartbeat"     2>/dev/null || true
pkill -f "${ATTACK_NODE}"      2>/dev/null || true
sleep 1

# ── Validate ──────────────────────────────────────────────────────────────────
echo "[4/4] Validating attack CSV..."
echo ""
VALIDATOR="$HOME/Dissertation/validate_attacks.py"
if [ -f "$VALIDATOR" ]; then
  python3 "$VALIDATOR" "$VALIDATOR_KEY"
else
  echo "    (validate_attacks.py not found at $VALIDATOR -- skipping automated check)"
  echo "    Inspect /tmp/${ATTACK_NODE}_metrics.csv manually."
fi

echo ""
echo "============================================================"
echo "  SMOKE TEST DONE: $ATTACK / $SMOKE_APPROACH"
echo "  Raw CSV: /tmp/${ATTACK_NODE}_metrics.csv"
echo "  Re-run with different params:"
echo "    SMOKE_RAMP_SEC=5 bash smoke_test.sh $ATTACK $ATTACK_ARGS"
echo "============================================================"
