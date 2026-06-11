#!/bin/bash
# launch_mitigation.sh  (mitigation-experiments branch)
# =======================================================
# Launches the full stack for any of the 4 new mitigation algorithms.
# Handles sensing, discovery, GT logging, and the chosen algorithm.
#
# Usage:
#   bash scripts/launch_mitigation.sh wls_huber
#   bash scripts/launch_mitigation.sh wls_tukey
#   bash scripts/launch_mitigation.sh ransac
#   bash scripts/launch_mitigation.sh ekf_chi2_huber
#
# Optional second arg = attack label (appended to CSV filenames):
#   bash scripts/launch_mitigation.sh wls_huber sybil
#   bash scripts/launch_mitigation.sh ekf_chi2_huber wormhole
#
# Prerequisites: start_swarm.sh already running

set -e

APPROACH=${1:-wls_huber}
ATTACK_LABEL=${2:-baseline}

# Map approach → script filename in swarm_discovery package
declare -A SCRIPT_MAP=(
  [wls_huber]="coop_loc_wls_huber.py"
  [wls_tukey]="coop_loc_wls_tukey.py"
  [ransac]="coop_loc_ransac.py"
  [ekf_chi2_huber]="coop_loc_ekf_chi2_huber.py"
)

SCRIPT=${SCRIPT_MAP[$APPROACH]}
if [ -z "$SCRIPT" ]; then
  echo "Unknown approach: '$APPROACH'"
  echo "Choose from: ${!SCRIPT_MAP[@]}"
  exit 1
fi

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
CODE="$HOME/Dissertation/code"
SESSION="swarm_${APPROACH}_${ATTACK_LABEL}"

SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"
SCRIPT_PATH="$PKG/$SCRIPT"

if [ ! -f "$SCRIPT_PATH" ]; then
  echo "ERROR: Script not found: $SCRIPT_PATH"
  echo "Make sure the mitigation scripts are in the swarm_discovery package."
  echo "Run: colcon build --packages-select swarm_discovery"
  exit 1
fi

echo "=== Launching: approach=$APPROACH  attack=$ATTACK_LABEL ==="
echo "    Script: $SCRIPT_PATH"
echo "    Session: $SESSION"

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50 -n sensing

# ── Window 0: Sensing ────────────────────────────────────────────────────────
tmux send-keys -t $SESSION:sensing "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION:sensing
tmux send-keys -t $SESSION:sensing "$SRC && sleep 3 && python3 $CODE/inter_drone_ranging.py" Enter

# ── Window 1: Discovery (Design A) ──────────────────────────────────────────
tmux new-window -t $SESSION -n discovery
tmux send-keys -t $SESSION:discovery "$SRC && ros2 run swarm_discovery swarm_registry" Enter
tmux split-window -v -t $SESSION:discovery
tmux send-keys -t $SESSION:discovery \
  "$SRC && sleep 3 && \
  ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 & wait" Enter

# ── Window 2: Ground truth logger ───────────────────────────────────────────
tmux new-window -t $SESSION -n gt_logger
tmux send-keys -t $SESSION:gt_logger \
  "$SRC && sleep 4 && python3 ~/Dissertation/extract_ground_truth.py" Enter

# ── Window 3: Mitigation algorithm × 5 ─────────────────────────────────────
tmux new-window -t $SESSION -n algorithm
tmux send-keys -t $SESSION:algorithm \
  "export COOP_ATTACK_LABEL=$ATTACK_LABEL && $SRC && sleep 6 && \
  python3 $SCRIPT_PATH px4_1 & \
  python3 $SCRIPT_PATH px4_2 & \
  python3 $SCRIPT_PATH px4_3 & \
  python3 $SCRIPT_PATH px4_4 & \
  python3 $SCRIPT_PATH px4_5 & wait" Enter

# ── Window 4: Attack + analysis prompt ──────────────────────────────────────
tmux new-window -t $SESSION -n attacks
tmux send-keys -t $SESSION:attacks "$SRC" Enter
tmux send-keys -t $SESSION:attacks "# === Attack commands ===" Enter
tmux send-keys -t $SESSION:attacks "# Sybil:    ros2 run swarm_discovery sybil_registry_attack 3" Enter
tmux send-keys -t $SESSION:attacks "# Replay:   ros2 run swarm_discovery replay_attack delayed" Enter
tmux send-keys -t $SESSION:attacks "# Wormhole: ros2 run swarm_discovery wormhole_attack 0.05" Enter
tmux send-keys -t $SESSION:attacks "# === After experiment (Ctrl-C all windows first) ===" Enter
tmux send-keys -t $SESSION:attacks "# python3 ~/Dissertation/analyse_all_approaches.py --drone px4_1 --gt-csv ~/Dissertation/evidence/gt/gt_px4_1.csv" Enter

echo ""
echo "[+] $APPROACH stack launched in session '$SESSION'"
echo "    tmux attach -t $SESSION"
echo ""
echo "Windows:"
echo "  0 sensing    — ground_truth_demux + inter_drone_ranging"
echo "  1 discovery  — swarm_registry + 5 heartbeats"
echo "  2 gt_logger  — extract_ground_truth.py (x500_N -> px4_N)"
echo "  3 algorithm  — $SCRIPT × 5 drones"
echo "  4 attacks    — attack commands ready to run"
echo ""
echo "CSV metrics: ~/Dissertation/evidence/metrics/${APPROACH}_px4_N.csv"
echo "GT data:     ~/Dissertation/evidence/gt/gt_px4_N.csv"
