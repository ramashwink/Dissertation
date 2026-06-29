#!/bin/bash
# demo.sh — Interactive demo launcher for viva/presentation
# Keeps RViz alive throughout. You control when attacks start.
#
# Usage:
#   bash demo.sh <approach> [attack]
#
# Examples:
#   bash demo.sh wls                    # baseline only, you press Enter to exit
#   bash demo.sh wls wormhole           # baseline first, press Enter to inject attack
#   bash demo.sh wls_tukey wormhole     # show the defence
#   bash demo.sh ekf_chi2_huber byzantine
#
# Approaches: wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber
# Attacks:    sybil | replay | wormhole | sybil_consistent | replay_gradual | byzantine | timesync

set -e

APPROACH=${1:-wls}
ATTACK=${2:-}

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

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
  [wls_huber]=""  [wls_tukey]=""  [ransac]=""  [ekf_chi2_huber]=""
)

declare -A ATTACK_NODE_MAP=(
  [sybil]="sybil_registry_attack"
  [replay]="replay_attack"
  [wormhole]="wormhole_attack"
  [sybil_consistent]="sybil_consistent_attack"
  [replay_gradual]="replay_attack_gradual"
  [byzantine]="byzantine_insider_attack"
  [timesync]="timesync_attack"
)

declare -A ATTACK_ARGS=(
  [sybil]="3"
  [replay]="delayed"
  [wormhole]="0.05"
  [sybil_consistent]=""
  [replay_gradual]=""
  [byzantine]="px4_2 0.8"
  [timesync]="ancient"
)

SCRIPT=${SCRIPT_MAP[$APPROACH]}
if [ -z "$SCRIPT" ]; then
  echo "Unknown approach: $APPROACH"; exit 1
fi

SESSION="demo"

# ── Helpers ──────────────────────────────────────────────────────────────────
kill_demo_nodes() {
  # Kill experiment nodes only — never touches swarm_viz
  pkill -f "coop_loc"             2>/dev/null || true
  pkill -f "ground_truth_demux"   2>/dev/null || true
  pkill -f "inter_drone_ranging"  2>/dev/null || true
  pkill -f "swarm_registry"       2>/dev/null || true
  pkill -f "swarm_heartbeat"      2>/dev/null || true
  pkill -f "sybil"                2>/dev/null || true
  pkill -f "replay_attack"        2>/dev/null || true
  pkill -f "wormhole_attack"      2>/dev/null || true
  pkill -f "byzantine_insider"    2>/dev/null || true
  pkill -f "timesync_attack"      2>/dev/null || true
}

ensure_viz() {
  if ! pgrep -f "swarm_viz" > /dev/null 2>&1; then
    echo "  [viz] Starting swarm_viz..."
    source /opt/ros/humble/setup.bash
    source "$WS/install/setup.bash"
    ros2 run swarm_discovery swarm_viz > /tmp/swarm_viz.log 2>&1 &
    sleep 2
    echo "  [viz] swarm_viz pid=$(pgrep -f swarm_viz)"
  else
    echo "  [viz] swarm_viz already running — RViz stays live ✓"
  fi
}

wait_for_registry() {
  echo -n "  [registry] Waiting for all 5 drones..."
  for i in $(seq 1 30); do
    COUNT=$(ros2 topic echo /swarm/registry --once 2>/dev/null | grep -c "drone_id" || echo 0)
    if [ "$COUNT" -ge 5 ] 2>/dev/null; then
      echo " ✓ ($COUNT members)"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo " TIMEOUT — registry has fewer than 5 members, continuing anyway"
}

wait_for_estimates() {
  echo -n "  [localisation] Waiting for estimates to converge..."
  for i in $(seq 1 20); do
    COUNT=$(ros2 topic echo /swarm/viz/markers --once 2>/dev/null | grep -c "ns: estimate" || echo 0)
    if [ "$COUNT" -ge 5 ] 2>/dev/null; then
      echo " ✓ ($COUNT estimate markers)"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo " (estimates may still be converging)"
}

# ═════════════════════════════════════════════════════════════════════════════
clear
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          DRONE SWARM LOCALISATION DEMO               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Algorithm : $APPROACH"
printf "║  Attack    : %-40s ║\n" "${ATTACK:-none (baseline only)}"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Clean previous demo nodes (not viz) ──────────────────────────────
echo "[1/4] Cleaning up previous experiment nodes..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
kill_demo_nodes
sleep 2
echo "  Done."

# ── Step 2: Ensure swarm_viz is alive ────────────────────────────────────────
echo ""
echo "[2/4] Ensuring RViz publisher (swarm_viz) is live..."
ensure_viz

# ── Step 3: Launch sensing + discovery + algorithm in ONE tmux session ────────
echo ""
echo "[3/4] Launching stack..."

tmux new-session -d -s $SESSION -x 240 -y 60 -n sensing

# Sensing pane (ground truth + ranging)
tmux send-keys -t $SESSION:sensing \
  "$SRC && python3 $HOME/Dissertation/code/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION:sensing
tmux send-keys -t $SESSION:sensing \
  "$SRC && sleep 2 && python3 $HOME/Dissertation/code/inter_drone_ranging.py" Enter

# Registry + heartbeats
tmux new-window -t $SESSION -n registry
tmux send-keys -t $SESSION:registry \
  "$SRC && ros2 run swarm_discovery swarm_registry" Enter
tmux split-window -v -t $SESSION:registry
tmux send-keys -t $SESSION:registry \
  "$SRC && sleep 3 && \
   ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & sleep 0.5 && \
   ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 & sleep 0.5 && \
   ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 & sleep 0.5 && \
   ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 & sleep 0.5 && \
   ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 & wait" Enter

echo "  Sensing + registry started. Waiting 8s for stack to settle..."
sleep 8

# Wait for full registry
wait_for_registry

# Launch localisation algorithm
tmux new-window -t $SESSION -n algorithm
ROS2_NODE=${ROS2_NODE_MAP[$APPROACH]}

if [ -n "$ROS2_NODE" ]; then
  tmux send-keys -t $SESSION:algorithm \
    "$SRC && \
     ros2 run swarm_discovery ${ROS2_NODE} px4_1 & \
     ros2 run swarm_discovery ${ROS2_NODE} px4_2 & \
     ros2 run swarm_discovery ${ROS2_NODE} px4_3 & \
     ros2 run swarm_discovery ${ROS2_NODE} px4_4 & \
     ros2 run swarm_discovery ${ROS2_NODE} px4_5 & wait" Enter
else
  tmux send-keys -t $SESSION:algorithm \
    "$SRC && \
     python3 $PKG/$SCRIPT px4_1 & \
     python3 $PKG/$SCRIPT px4_2 & \
     python3 $PKG/$SCRIPT px4_3 & \
     python3 $PKG/$SCRIPT px4_4 & \
     python3 $PKG/$SCRIPT px4_5 & wait" Enter
fi

echo "  Algorithm ($APPROACH) started. Waiting for estimates..."
sleep 5
wait_for_estimates

# ── Step 4: Interactive attack control ───────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✓ BASELINE RUNNING — yellow balls visible in RViz   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Algorithm : $APPROACH"
echo "  Status    : BASELINE (no attack)"
echo "  RViz      : teal = ground truth, yellow = estimated"
echo ""

if [ -z "$ATTACK" ]; then
  echo "  No attack configured. Press Enter to stop the demo."
  read -r
else
  ATTACK_NODE=${ATTACK_NODE_MAP[$ATTACK]}
  ATTACK_ARG=${ATTACK_ARGS[$ATTACK]}

  echo "  Attack ready: $ATTACK"
  echo ""
  echo "  ► Press Enter to INJECT the $ATTACK attack..."
  read -r

  echo ""
  echo "  ⚠  INJECTING $ATTACK ATTACK..."
  tmux new-window -t $SESSION -n attack
  tmux send-keys -t $SESSION:attack \
    "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARG}" Enter

  echo ""
  echo "╔══════════════════════════════════════════════════════╗"
  echo "║  ⚠  ATTACK ACTIVE — watch yellow balls drift         ║"
  echo "╚══════════════════════════════════════════════════════╝"
  echo ""
  echo "  Press Enter to STOP the attack and watch recovery..."
  read -r

  echo "  Stopping attack..."
  tmux kill-window -t $SESSION:attack 2>/dev/null || true
  pkill -f "$ATTACK_NODE"  2>/dev/null || true
  pkill -f "replay_attack" 2>/dev/null || true
  pkill -f "wormhole"      2>/dev/null || true
  pkill -f "byzantine"     2>/dev/null || true
  pkill -f "timesync"      2>/dev/null || true
  pkill -f "sybil"         2>/dev/null || true

  echo ""
  echo "╔══════════════════════════════════════════════════════╗"
  echo "║  ✓ ATTACK STOPPED — watch yellow balls recover       ║"
  echo "╚══════════════════════════════════════════════════════╝"
  echo ""
  echo "  Press Enter to end the demo..."
  read -r
fi

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo ""
echo "  Shutting down experiment nodes (swarm_viz stays alive)..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
kill_demo_nodes

echo ""
echo "  Demo complete. RViz still open for next demo."
echo "  Run again:  bash demo.sh wls_tukey wormhole"
echo ""
