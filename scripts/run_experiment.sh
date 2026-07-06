#!/bin/bash
# run_experiment.sh — PATCHED for persistent RViz demo
# Changes vs original:
#   1. swarm_viz excluded from ALL kill lists
#   2. swarm_viz restarted at step 1 (before stack launches), not after teardown
#   3. tmux kill-server replaced with targeted session kill so swarm_viz persists

set -e

APPROACH=${1:-}
ATTACK=${2:-}

if [ -z "$APPROACH" ] || [ -z "$ATTACK" ]; then
  echo "Usage: bash run_experiment.sh <approach> <attack>"
  echo ""
  echo "Approaches: wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber"
  echo "Attacks:    baseline | sybil | replay | wormhole"
  exit 1
fi

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
CODE="$HOME/Dissertation/code"
METRICS="$HOME/Dissertation/evidence/metrics"
GT_DIR="$HOME/Dissertation/evidence/gt"
SCRIPTS="$HOME/Dissertation/scripts"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

WARMUP_SEC=12
EXPERIMENT_SEC=90
ATTACK_DELAY=5

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
  [baseline]=""
  [sybil]="sybil_registry_attack"
  [replay]="replay_attack"
  [wormhole]="wormhole_attack"
  [sybil_consistent]="sybil_consistent_attack"
  [replay_gradual]="replay_attack_gradual"
  [byzantine]="byzantine_insider_attack"
  [timesync]="timesync_attack"
  [targeted_ramp]="byzantine_targeted_ekf"
  [targeted_osc]="byzantine_targeted_ekf"
  [targeted_two_drone]="byzantine_targeted_ekf"
)

declare -A ATTACK_ARGS=(
  [baseline]=""
  [sybil]="3"
  [replay]="delayed"
  [wormhole]="0.05"
  [sybil_consistent]=""
  [replay_gradual]=""
  [byzantine]="px4_2 0.8"
  [timesync]="ancient"
  [targeted_ramp]="px4_2 targeted_ramp"
  [targeted_osc]="px4_2 targeted_osc"
  [targeted_two_drone]="px4_2 targeted_two_drone"
)

SCRIPT=${SCRIPT_MAP[$APPROACH]}
ATTACK_NODE=${ATTACK_NODE_MAP[$ATTACK]}
ATTACK_ARG=${ATTACK_ARGS[$ATTACK]}

if [ -z "$SCRIPT" ]; then
  echo "Unknown approach: '$APPROACH'"; exit 1
fi
if [ -z "${ATTACK_NODE_MAP[$ATTACK]+x}" ]; then
  echo "Unknown attack: '$ATTACK'"; exit 1
fi

SCRIPT_PATH="$PKG/$SCRIPT"
SESSION="exp_${APPROACH}_${ATTACK}"

# ── Helper: kill all experiment nodes but NOT swarm_viz ─────────────────────
kill_experiment_nodes() {
  pkill -f "coop_loc"             2>/dev/null || true
  pkill -f "ground_truth_demux"   2>/dev/null || true
  pkill -f "inter_drone_ranging"  2>/dev/null || true
  pkill -f "swarm_registry"       2>/dev/null || true
  pkill -f "swarm_heartbeat"      2>/dev/null || true
  pkill -f "extract_ground_truth" 2>/dev/null || true
  pkill -f "sybil_registry"       2>/dev/null || true
  pkill -f "replay_attack"        2>/dev/null || true
  pkill -f "wormhole_attack"      2>/dev/null || true
  pkill -f "sybil_consistent"     2>/dev/null || true
  pkill -f "byzantine_insider"    2>/dev/null || true
  pkill -f "timesync_attack"      2>/dev/null || true
  pkill -f "ekf_attack_logger"    2>/dev/null || true
  # swarm_viz is deliberately NOT killed here
}

echo ""
echo "════════════════════════════════════════════════════════"
echo "  EXPERIMENT: approach=$APPROACH  attack=$ATTACK"
echo "════════════════════════════════════════════════════════"

# ── Step 0: Kill leftover experiment processes (NOT swarm_viz) ───────────────
echo ""
echo "[0/6] Cleaning up leftover processes (preserving swarm_viz)..."
# Kill only the previous experiment's tmux session, not the whole server
tmux kill-session -t "exp_"* 2>/dev/null || true
sleep 1
kill_experiment_nodes
sleep 2
echo "    Done."

# ── Step 1: Ensure swarm_viz is running before stack launches ────────────────
echo "[1/6] Checking swarm_viz is live for RViz..."
if ! pgrep -f "swarm_discovery.*swarm_viz" > /dev/null 2>&1; then
  echo "    swarm_viz not running — starting it now..."
  source /opt/ros/humble/setup.bash
  source "$WS/install/setup.bash"
  ros2 run swarm_discovery swarm_viz > /tmp/swarm_viz.log 2>&1 &
  VIZPID=$!
  sleep 2
  if kill -0 $VIZPID 2>/dev/null; then
    echo "    swarm_viz started (pid $VIZPID)"
  else
    echo "    WARNING: swarm_viz failed to start — check /tmp/swarm_viz.log"
  fi
else
  echo "    swarm_viz already running (pid $(pgrep -f "swarm_discovery.*swarm_viz")) — RViz will stay live"
fi

# ── Step 2: Launch sensing + discovery ───────────────────────────────────────
echo "[2/6] Starting sensing + discovery stack..."

tmux new-session -d -s $SESSION -x 220 -y 50 -n sensing
tmux send-keys -t $SESSION:sensing \
  "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION:sensing
tmux send-keys -t $SESSION:sensing \
  "$SRC && sleep 3 && python3 $CODE/inter_drone_ranging.py" Enter

tmux new-window -t $SESSION -n discovery
tmux send-keys -t $SESSION:discovery \
  "$SRC && ros2 run swarm_discovery swarm_registry" Enter
tmux split-window -v -t $SESSION:discovery
tmux send-keys -t $SESSION:discovery \
  "$SRC && sleep 4 && \
  ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & sleep 1 && \
  ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 & sleep 1 && \
  ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 & sleep 1 && \
  ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 & sleep 1 && \
  ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 & wait" Enter

echo "    Sensing + discovery started."

# ── Step 3: Launch localisation algorithm ────────────────────────────────────
echo "[3/6] Starting localisation algorithm: $APPROACH..."

tmux new-window -t $SESSION -n algorithm
ROS2_NODE=${ROS2_NODE_MAP[$APPROACH]}

if [ -n "$ROS2_NODE" ]; then
  tmux send-keys -t $SESSION:algorithm \
    "$SRC && sleep 6 && \
    ros2 run swarm_discovery ${ROS2_NODE} px4_1 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_2 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_3 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_4 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_5 & wait" Enter
else
  tmux send-keys -t $SESSION:algorithm \
    "export COOP_ATTACK_LABEL=$ATTACK && $SRC && sleep 6 && \
    python3 $SCRIPT_PATH px4_1 & \
    python3 $SCRIPT_PATH px4_2 & \
    python3 $SCRIPT_PATH px4_3 & \
    python3 $SCRIPT_PATH px4_4 & \
    python3 $SCRIPT_PATH px4_5 & wait" Enter
fi

echo "    Algorithm started. Waiting ${WARMUP_SEC}s for stabilisation..."

if [ "$APPROACH" = "wls" ] || [ "$APPROACH" = "ekf" ]; then
  echo "[3b] Starting external CSV logger for $APPROACH..."
  LOGGER_PATH="$WS/src/swarm_discovery/swarm_discovery/coop_loc_logger.py"
  tmux new-window -t $SESSION -n logger
  tmux send-keys -t $SESSION:logger \
    "$SRC && sleep 7 && \
    python3 $LOGGER_PATH $APPROACH px4_1 & \
    python3 $LOGGER_PATH $APPROACH px4_2 & \
    python3 $LOGGER_PATH $APPROACH px4_3 & \
    python3 $LOGGER_PATH $APPROACH px4_4 & \
    python3 $LOGGER_PATH $APPROACH px4_5 & wait" Enter
fi

sleep $WARMUP_SEC

# ── Step 4: Start ground truth logger ────────────────────────────────────────
echo "[4/6] Starting ground truth logger..."
tmux new-window -t $SESSION -n gt_logger
tmux send-keys -t $SESSION:gt_logger \
  "$SRC && python3 ~/Dissertation/extract_ground_truth.py" Enter
sleep 2

# ── Step 5: Inject attack ────────────────────────────────────────────────────
if [ -n "$ATTACK_NODE" ]; then
  echo "[5/6] Injecting attack: $ATTACK (waiting ${ATTACK_DELAY}s first)..."
  sleep $ATTACK_DELAY
  tmux new-window -t $SESSION -n attack
  tmux send-keys -t $SESSION:attack \
    "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARG}" Enter
  echo "    Attack '$ATTACK' running."
else
  echo "[5/6] No attack (baseline run)."
fi

# ── Step 6: Collect data ─────────────────────────────────────────────────────
echo "[6/6] Collecting data for ${EXPERIMENT_SEC}s..."
echo "      tmux attach -t $SESSION  (to watch live)"
echo ""

for i in $(seq 1 $EXPERIMENT_SEC); do
  sleep 1
  if [ $((i % 10)) -eq 0 ]; then
    ROWS=$(wc -l $METRICS/${APPROACH}_px4_1*.csv 2>/dev/null | tail -1 | awk '{print $1}')
    echo "      t=${i}s  rows written so far: ${ROWS:-0}"
  fi
done

# ── Teardown: kill only the experiment session, swarm_viz stays ──────────────
echo ""
echo "[*] Stopping experiment (swarm_viz preserved)..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 2
kill_experiment_nodes
sleep 2

# ── Rename CSVs ──────────────────────────────────────────────────────────────
mkdir -p $METRICS
RENAMED=0
for i in 1 2 3 4 5; do
  SRC_CSV="$METRICS/${APPROACH}_px4_${i}.csv"
  if [ "$ATTACK" = "baseline" ]; then
    DST_CSV="$SRC_CSV"
  else
    DST_CSV="$METRICS/${APPROACH}_px4_${i}_${ATTACK}.csv"
    if [ -f "$SRC_CSV" ]; then
      mv "$SRC_CSV" "$DST_CSV"
      RENAMED=$((RENAMED + 1))
    fi
  fi
done

for i in 1 2 3 4 5; do
  GT_SRC="$GT_DIR/gt_px4_${i}.csv"
  GT_DST="$GT_DIR/gt_px4_${i}_${APPROACH}_${ATTACK}.csv"
  if [ -f "$GT_SRC" ]; then
    cp "$GT_SRC" "$GT_DST"
  fi
done

echo ""
echo "════════════════════════════════════════════════════════"
echo "  DONE: $APPROACH / $ATTACK"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Metrics files:"
for i in 1 2 3 4 5; do
  if [ "$ATTACK" = "baseline" ]; then
    F="$METRICS/${APPROACH}_px4_${i}.csv"
  else
    F="$METRICS/${APPROACH}_px4_${i}_${ATTACK}.csv"
  fi
  if [ -f "$F" ]; then
    ROWS=$(wc -l < "$F")
    echo "    px4_${i}: $ROWS rows  →  $(basename $F)"
  else
    echo "    px4_${i}: FILE NOT FOUND"
  fi
done

echo ""
echo "  swarm_viz still running: pid=$(pgrep -f "swarm_discovery.*swarm_viz" || echo 'NOT FOUND — restart manually')"
echo "  RViz2 markers should still be live."
echo ""
echo "  Ready for next experiment."
