#!/bin/bash
# run_experiment.sh
# =================
# Runs ONE complete experiment: launch stack → wait → inject attack →
# wait → kill everything → rename CSVs with correct labels.
#
# Usage:
#   bash run_experiment.sh <approach> <attack>
#
# Approaches:  wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber
# Attacks:     baseline | sybil | replay | wormhole
#
# Examples:
#   bash run_experiment.sh wls baseline
#   bash run_experiment.sh ekf baseline
#   bash run_experiment.sh wls_huber sybil
#   bash run_experiment.sh ekf_chi2_huber wormhole
#
# What this script does:
#   1. Kills any leftover sessions/nodes from a previous run
#   2. Launches the correct stack (sensing + discovery + algorithm)
#   3. Waits WARMUP_SEC for everything to stabilise
#   4. Starts the attack node (if attack != baseline)
#   5. Starts ground truth logging simultaneously
#   6. Waits EXPERIMENT_SEC for data collection
#   7. Kills everything cleanly
#   8. Renames CSVs from generic names to approach_drone_attack.csv
#   9. Prints a summary of rows collected
#
# Prerequisites: start_swarm.sh already running in a separate terminal.

set -e

# ── Args ─────────────────────────────────────────────────────────────────────
APPROACH=${1:-}
ATTACK=${2:-}

if [ -z "$APPROACH" ] || [ -z "$ATTACK" ]; then
  echo "Usage: bash run_experiment.sh <approach> <attack>"
  echo ""
  echo "Approaches: wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber"
  echo "Attacks:    baseline | sybil | replay | wormhole"
  exit 1
fi

# ── Paths ────────────────────────────────────────────────────────────────────
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
CODE="$HOME/Dissertation/code"
METRICS="$HOME/Dissertation/evidence/metrics"
GT_DIR="$HOME/Dissertation/evidence/gt"
SCRIPTS="$HOME/Dissertation/scripts"

SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

# ── Timing ───────────────────────────────────────────────────────────────────
WARMUP_SEC=12      # time for sensing + discovery + algorithm to stabilise
EXPERIMENT_SEC=90  # data collection window
ATTACK_DELAY=5     # seconds after algorithm is stable before injecting attack

# ── Validate approach ────────────────────────────────────────────────────────
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
)

declare -A ATTACK_ARGS=(
  [baseline]=""
  [sybil]="3"
  [replay]="delayed"
  [wormhole]="0.05"
)

SCRIPT=${SCRIPT_MAP[$APPROACH]}
ATTACK_NODE=${ATTACK_NODE_MAP[$ATTACK]}
ATTACK_ARG=${ATTACK_ARGS[$ATTACK]}

if [ -z "$SCRIPT" ]; then
  echo "Unknown approach: '$APPROACH'"
  echo "Choose from: ${!SCRIPT_MAP[@]}"
  exit 1
fi

if [ -z "${ATTACK_NODE_MAP[$ATTACK]+x}" ]; then
  echo "Unknown attack: '$ATTACK'"
  echo "Choose from: ${!ATTACK_NODE_MAP[@]}"
  exit 1
fi

SCRIPT_PATH="$PKG/$SCRIPT"
SESSION="exp_${APPROACH}_${ATTACK}"

# ── Step 0: Kill any leftover processes ──────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  EXPERIMENT: approach=$APPROACH  attack=$ATTACK"
echo "════════════════════════════════════════════════════════"
echo ""
echo "[0/6] Cleaning up leftover processes..."

tmux kill-server 2>/dev/null || true
sleep 1
pkill -f "coop_loc"            2>/dev/null || true
pkill -f "ground_truth_demux"  2>/dev/null || true
pkill -f "inter_drone_ranging" 2>/dev/null || true
pkill -f "swarm_registry"      2>/dev/null || true
pkill -f "swarm_heartbeat"     2>/dev/null || true
pkill -f "extract_ground_truth" 2>/dev/null || true
pkill -f "sybil_registry"      2>/dev/null || true
pkill -f "replay_attack"       2>/dev/null || true
pkill -f "wormhole_attack"     2>/dev/null || true
pkill -f "ekf_attack_logger"   2>/dev/null || true
sleep 2
echo "    Done."

# ── Step 1: Launch sensing + discovery ───────────────────────────────────────
echo "[1/6] Starting sensing + discovery stack..."

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
  ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 & wait" Enter

echo "    Sensing + discovery started."

# ── Step 2: Launch localisation algorithm ────────────────────────────────────
echo "[2/6] Starting localisation algorithm: $APPROACH..."

tmux new-window -t $SESSION -n algorithm

ROS2_NODE=${ROS2_NODE_MAP[$APPROACH]}

if [ -n "$ROS2_NODE" ]; then
  # WLS and EKF have ros2 run entry points
  tmux send-keys -t $SESSION:algorithm \
    "$SRC && sleep 6 && \
    ros2 run swarm_discovery ${ROS2_NODE} px4_1 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_2 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_3 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_4 & \
    ros2 run swarm_discovery ${ROS2_NODE} px4_5 & wait" Enter
else
  # Mitigation algorithms run as direct python scripts
  tmux send-keys -t $SESSION:algorithm \
    "export COOP_ATTACK_LABEL=$ATTACK && $SRC && sleep 6 && \
    python3 $SCRIPT_PATH px4_1 & \
    python3 $SCRIPT_PATH px4_2 & \
    python3 $SCRIPT_PATH px4_3 & \
    python3 $SCRIPT_PATH px4_4 & \
    python3 $SCRIPT_PATH px4_5 & wait" Enter
fi

echo "    Algorithm started. Waiting ${WARMUP_SEC}s for stabilisation..."
sleep $WARMUP_SEC

# ── Step 3: Start ground truth logger ────────────────────────────────────────
echo "[3/6] Starting ground truth logger..."

tmux new-window -t $SESSION -n gt_logger
tmux send-keys -t $SESSION:gt_logger \
  "$SRC && python3 ~/Dissertation/extract_ground_truth.py" Enter

sleep 2
echo "    GT logger started."

# ── Step 4: Inject attack (if not baseline) ──────────────────────────────────
if [ -n "$ATTACK_NODE" ]; then
  echo "[4/6] Injecting attack: $ATTACK (waiting ${ATTACK_DELAY}s first)..."
  sleep $ATTACK_DELAY

  tmux new-window -t $SESSION -n attack
  tmux send-keys -t $SESSION:attack \
    "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARG}" Enter

  echo "    Attack '$ATTACK' running."
else
  echo "[4/6] No attack (baseline run)."
fi

# ── Step 5: Collect data ─────────────────────────────────────────────────────
echo "[5/6] Collecting data for ${EXPERIMENT_SEC}s..."
echo "      tmux attach -t $SESSION  (to watch live, Ctrl-B D to detach)"
echo ""

# Progress bar
for i in $(seq 1 $EXPERIMENT_SEC); do
  sleep 1
  if [ $((i % 10)) -eq 0 ]; then
    # Show live CSV row counts
    ROWS=$(wc -l $METRICS/${APPROACH}_px4_1*.csv 2>/dev/null | tail -1 | awk '{print $1}')
    echo "      t=${i}s  rows written so far: ${ROWS:-0}"
  fi
done

# ── Step 6: Kill everything and rename CSVs ──────────────────────────────────
echo ""
echo "[6/6] Stopping experiment and renaming CSVs..."

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 2
pkill -f "coop_loc"            2>/dev/null || true
pkill -f "ground_truth_demux"  2>/dev/null || true
pkill -f "inter_drone_ranging" 2>/dev/null || true
pkill -f "swarm_registry"      2>/dev/null || true
pkill -f "swarm_heartbeat"     2>/dev/null || true
pkill -f "extract_ground_truth" 2>/dev/null || true
pkill -f "sybil_registry"      2>/dev/null || true
pkill -f "replay_attack"       2>/dev/null || true
pkill -f "wormhole_attack"     2>/dev/null || true
sleep 2

# Rename metrics CSVs: {approach}_px4_N.csv → {approach}_px4_N_{attack}.csv
# (baseline runs keep the plain name for backwards compat with analyser)
mkdir -p $METRICS

RENAMED=0
for i in 1 2 3 4 5; do
  SRC_CSV="$METRICS/${APPROACH}_px4_${i}.csv"
  if [ "$ATTACK" = "baseline" ]; then
    DST_CSV="$SRC_CSV"   # keep as-is for baseline
  else
    DST_CSV="$METRICS/${APPROACH}_px4_${i}_${ATTACK}.csv"
    if [ -f "$SRC_CSV" ]; then
      mv "$SRC_CSV" "$DST_CSV"
      RENAMED=$((RENAMED + 1))
    fi
  fi
done

# Copy GT CSV with experiment label
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
    echo "    px4_${i}: FILE NOT FOUND — check algorithm started correctly"
  fi
done

echo ""
echo "  GT files: ${GT_DIR}/gt_px4_N_${APPROACH}_${ATTACK}.csv"
echo ""
echo "  Analyse with:"
echo "    python3 ~/Dissertation/analyse_all_approaches.py \\"
echo "        --drone px4_1 \\"
echo "        --gt-csv ${GT_DIR}/gt_px4_1_${APPROACH}_${ATTACK}.csv"
echo ""
echo "  Ready for next experiment."
