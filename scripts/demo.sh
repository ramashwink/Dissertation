#!/bin/bash
# demo.sh v2 — heartbeats launched as separate tmux windows, not splits

set +e

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
  [targeted_ramp]="byzantine_targeted_ekf"
)

declare -A ATTACK_ARGS=(
  [sybil]="3 px4_2"
  [replay]="delayed"
  [wormhole]="0.05"
  [sybil_consistent]=""
  [replay_gradual]=""
  [byzantine]="px4_2 0.8"
  [timesync]="ancient"
  [targeted_ramp]="px4_2 targeted_ramp"
)

SCRIPT=${SCRIPT_MAP[$APPROACH]}
if [ -z "$SCRIPT" ]; then echo "Unknown approach: $APPROACH"; exit 1; fi
SESSION="demo"

kill_demo_nodes() {
  MYPID=$$
  for pattern in "coop_loc" "ground_truth_demux" "inter_drone_ranging" \
                 "swarm_registry" "swarm_heartbeat" "sybil_registry" \
                 "sybil_consistent" "replay_attack" "wormhole_attack" \
                 "byzantine_insider" "timesync_attack"; do
    pgrep -f "$pattern" | grep -v "^${MYPID}$" | xargs -r kill -15 2>/dev/null || true
  done
}

ensure_viz() {
  if ! pgrep -f "swarm_viz" > /dev/null 2>&1; then
    echo "  [viz] Starting swarm_viz..."
    source /opt/ros/humble/setup.bash
    source "$WS/install/setup.bash"
    ros2 run swarm_discovery swarm_viz > /tmp/swarm_viz.log 2>&1 &
    sleep 3
  else
    echo "  [viz] swarm_viz already running ✓"
  fi
}

wait_for_registry() {
  echo -n "  [registry] Waiting for 5 members"
  for i in $(seq 1 40); do
    SEEN=$(ros2 topic echo /swarm/registry --once 2>/dev/null | grep "total_seen" | awk '{print $2}' || echo 0)
    if [ "${SEEN:-0}" -ge 5 ] 2>/dev/null; then
      echo " ✓ (total_seen=$SEEN)"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo ""
  echo "  [registry] TIMEOUT. Current state:"
  ros2 topic echo /swarm/registry --once 2>/dev/null | grep -E "total_seen|drone_id" || echo "  (no registry topic)"
  echo ""
  echo "  Trying to restart heartbeats directly..."
  source /opt/ros/humble/setup.bash
  source "$WS/install/setup.bash"
  pkill -f "swarm_heartbeat" 2>/dev/null || true
  sleep 1
  ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 > /tmp/hb1.log 2>&1 &
  sleep 0.3
  ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 > /tmp/hb2.log 2>&1 &
  sleep 0.3
  ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 > /tmp/hb3.log 2>&1 &
  sleep 0.3
  ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 > /tmp/hb4.log 2>&1 &
  sleep 0.3
  ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 > /tmp/hb5.log 2>&1 &
  echo -n "  [registry] Retrying"
  for i in $(seq 1 20); do
    SEEN=$(ros2 topic echo /swarm/registry --once 2>/dev/null | grep "total_seen" | awk '{print $2}' || echo 0)
    if [ "${SEEN:-0}" -ge 5 ] 2>/dev/null; then
      echo " ✓ (total_seen=$SEEN)"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo " STILL FAILING — check swarm_registry is running:"
  ros2 node list 2>/dev/null | grep registry || echo "  swarm_registry node not found!"
}

wait_for_estimates() {
  echo -n "  [localisation] Waiting for estimates"
  for i in $(seq 1 25); do
    COUNT=$(ros2 topic echo /swarm/viz/markers --once 2>/dev/null | grep -c "ns: estimate" 2>/dev/null || echo 0)
    if [ "${COUNT:-0}" -ge 1 ] 2>/dev/null; then
      echo " ✓ ($COUNT estimate markers visible)"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo " (still waiting — RViz may show partial results)"
}

# ═════════════════════════════════════════════════════════════════════════════
clear
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          DRONE SWARM LOCALISATION DEMO               ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Algorithm : %-39s║\n" "$APPROACH"
printf "║  Attack    : %-39s║\n" "${ATTACK:-none (baseline only)}"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

echo "[1/5] Cleaning up previous nodes (preserving swarm_viz)..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
kill_demo_nodes
sleep 2
echo "  Done."

echo ""
echo "[2/5] Ensuring swarm_viz is live..."
ensure_viz

echo ""
echo "[3/5] Launching ground truth + ranging..."
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"

tmux new-session -d -s $SESSION -x 240 -y 60 -n gt
tmux send-keys -t $SESSION:gt \
  "$SRC && python3 $HOME/Dissertation/code/ground_truth_demux.py" Enter

tmux new-window -t $SESSION -n ranging
tmux send-keys -t $SESSION:ranging \
  "$SRC && python3 $HOME/Dissertation/code/inter_drone_ranging.py" Enter

sleep 3
echo "  Ground truth + ranging started."

echo ""
echo "[4/5] Launching registry..."
tmux new-window -t $SESSION -n registry
tmux send-keys -t $SESSION:registry \
  "$SRC && ros2 run swarm_discovery swarm_registry" Enter
sleep 4  # give registry time to come up before heartbeats

echo "  Launching heartbeats (one per window for reliability)..."
tmux new-window -t $SESSION -n hb1
tmux send-keys -t $SESSION:hb1 \
  "$SRC && ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0" Enter
sleep 0.5
tmux new-window -t $SESSION -n hb2
tmux send-keys -t $SESSION:hb2 \
  "$SRC && ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0" Enter
sleep 0.5
tmux new-window -t $SESSION -n hb3
tmux send-keys -t $SESSION:hb3 \
  "$SRC && ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0" Enter
sleep 0.5
tmux new-window -t $SESSION -n hb4
tmux send-keys -t $SESSION:hb4 \
  "$SRC && ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0" Enter
sleep 0.5
tmux new-window -t $SESSION -n hb5
tmux send-keys -t $SESSION:hb5 \
  "$SRC && ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0" Enter

wait_for_registry

echo ""
echo "[5/5] Launching localisation algorithm: $APPROACH..."
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

sleep 4
wait_for_estimates

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✓ BASELINE LIVE — check RViz for yellow balls       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

if [ -z "$ATTACK" ]; then
  echo "  Press Enter to stop the demo."
  read -r
else
  ATTACK_NODE=${ATTACK_NODE_MAP[$ATTACK]}
  ATTACK_ARG=${ATTACK_ARGS[$ATTACK]}
  echo "  Attack ready: $ATTACK"
  echo "  ► Press Enter to INJECT attack..."
  read -r

  echo "  ⚠  INJECTING: $ATTACK"
  tmux new-window -t $SESSION -n attack
  tmux send-keys -t $SESSION:attack \
    "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARG}" Enter

  echo ""
  echo "╔══════════════════════════════════════════════════════╗"
  echo "║  ⚠  ATTACK ACTIVE — yellow balls drifting           ║"
  echo "╚══════════════════════════════════════════════════════╝"
  echo ""
  echo "  Press Enter to STOP attack and show recovery..."
  read -r

  tmux kill-window -t $SESSION:attack 2>/dev/null || true
  pkill -f "sybil_registry"    2>/dev/null || true
  pkill -f "sybil_consistent"  2>/dev/null || true
  pkill -f "replay_attack"     2>/dev/null || true
  pkill -f "wormhole_attack"   2>/dev/null || true
  pkill -f "byzantine_insider" 2>/dev/null || true
  pkill -f "timesync_attack"   2>/dev/null || true

  echo ""
  echo "╔══════════════════════════════════════════════════════╗"
  echo "║  ✓ ATTACK STOPPED — balls recovering                 ║"
  echo "╚══════════════════════════════════════════════════════╝"
  echo ""
  echo "  Press Enter to end demo..."
  read -r
fi

echo "  Shutting down (swarm_viz stays alive)..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
kill_demo_nodes
echo ""
echo "  Done. Run next demo:  bash demo.sh wls_tukey wormhole"
echo ""
