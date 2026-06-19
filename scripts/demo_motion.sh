#!/bin/bash
# demo_motion.sh
# ==============
# Interactive viva demo — MOTION variant.
# Drones fly a coordinated pattern while you demonstrate attacks live.
# RViz stays live between runs (swarm_viz never killed).
#
# Usage:
#   bash demo_motion.sh <approach> [attack] [pattern]
#
# Examples:
#   bash demo_motion.sh ekf_chi2_huber                         # baseline hover
#   bash demo_motion.sh wls wormhole square                    # wormhole, square pattern
#   bash demo_motion.sh ekf_chi2_huber targeted_ramp hover     # F4 while hovering
#   bash demo_motion.sh ransac byzantine circle                 # Byzantine, circle
#
# Patterns: hover | square | circle  (default: hover)

set +e

APPROACH=${1:-ekf_chi2_huber}
ATTACK=${2:-}
PATTERN=${3:-hover}

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"
SESSION="demo_motion"

declare -A SCRIPT_MAP=(
  [wls]="cooperative_localisation_dynamic.py"
  [ekf]="cooperative_localisation_ekf.py"
  [wls_huber]="coop_loc_wls_huber.py"
  [wls_tukey]="coop_loc_wls_tukey.py"
  [ransac]="coop_loc_ransac.py"
  [ekf_chi2_huber]="coop_loc_ekf_chi2_huber.py"
)

declare -A ROS2_NODE_MAP=(
  [wls]="coop_loc_dynamic"   [ekf]="coop_loc_ekf"
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
  [targeted_osc]="byzantine_targeted_ekf"
  [targeted_two_drone]="byzantine_targeted_ekf"
)

declare -A ATTACK_ARGS=(
  [sybil]="3 px4_2"   [replay]="delayed"   [wormhole]="0.05"
  [sybil_consistent]=""   [replay_gradual]=""
  [byzantine]="px4_2 0.8"   [timesync]="ancient"
  [targeted_ramp]="px4_2 targeted_ramp"
  [targeted_osc]="px4_2 targeted_osc"
  [targeted_two_drone]="px4_2 targeted_two_drone"
)

SCRIPT=${SCRIPT_MAP[$APPROACH]}
[ -z "$SCRIPT" ] && echo "Unknown approach: $APPROACH" && exit 1

kill_motion_nodes() {
  MYPID=$$
  for pat in "coop_loc" "ground_truth_demux" "inter_drone_ranging" \
             "swarm_registry" "swarm_heartbeat" "formation_flight" \
             "sybil_registry" "sybil_consistent" "replay_attack" \
             "wormhole_attack" "byzantine_insider" "byzantine_targeted" \
             "timesync_attack"; do
    pgrep -f "$pat" | grep -v "^${MYPID}$" | xargs -r kill -15 2>/dev/null || true
  done
}

clear
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║        DRONE SWARM DEMO — MOTION EXPERIMENT            ║"
echo "╠════════════════════════════════════════════════════════╣"
printf "║  Algorithm : %-43s║\n" "$APPROACH"
printf "║  Attack    : %-43s║\n" "${ATTACK:-none (baseline only)}"
printf "║  Pattern   : %-43s║\n" "$PATTERN"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

echo "[1/6] Cleaning up (preserving swarm_viz)..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1; kill_motion_nodes; sleep 2
echo "  Done."

echo "[2/6] Ensuring swarm_viz is live..."
if ! pgrep -f "swarm_viz" > /dev/null 2>&1; then
  source /opt/ros/humble/setup.bash; source "$WS/install/setup.bash"
  ros2 run swarm_discovery swarm_viz > /tmp/swarm_viz.log 2>&1 &
  sleep 2; echo "  Started (pid $(pgrep -f swarm_viz))"
else
  echo "  Already running ✓"
fi

echo "[3/6] Starting sensing + registry (dynamic heartbeats)..."
source /opt/ros/humble/setup.bash; source "$WS/install/setup.bash"

tmux new-session -d -s $SESSION -x 240 -y 60 -n gt
tmux send-keys -t $SESSION:gt "$SRC && python3 $HOME/Dissertation/code/ground_truth_demux.py" Enter
tmux new-window -t $SESSION -n ranging
tmux send-keys -t $SESSION:ranging "$SRC && python3 $HOME/Dissertation/code/inter_drone_ranging.py" Enter
sleep 3

tmux new-window -t $SESSION -n registry
tmux send-keys -t $SESSION:registry "$SRC && ros2 run swarm_discovery swarm_registry" Enter
sleep 4

for i in 1 2 3 4 5; do
  tmux new-window -t $SESSION -n "hb${i}"
  tmux send-keys -t $SESSION:hb${i} "$SRC && ros2 run swarm_discovery swarm_heartbeat_dynamic px4_${i}" Enter
  sleep 0.3
done

echo "  Waiting for registry (dynamic heartbeats)..."
for j in $(seq 1 30); do
  SEEN=$(ros2 topic echo /swarm/registry --once 2>/dev/null | grep "total_seen" | awk '{print $2}' || echo 0)
  [ "${SEEN:-0}" -ge 5 ] 2>/dev/null && echo "  Registry ready (total_seen=$SEEN) ✓" && break
  echo -n "."; sleep 1
done

echo "[4/6] Starting formation flight (pattern=$PATTERN)..."
tmux new-window -t $SESSION -n flight
tmux send-keys -t $SESSION:flight "$SRC && ros2 run swarm_discovery formation_flight $PATTERN" Enter
echo "  Monitor drones in QGC (ports 18570-18574)"
echo "  Waiting 25s for drones to arm and reach altitude..."
sleep 25

echo "[5/6] Starting localisation: $APPROACH..."
tmux new-window -t $SESSION -n algorithm
ROS2_NODE=${ROS2_NODE_MAP[$APPROACH]}
if [ -n "$ROS2_NODE" ]; then
  tmux send-keys -t $SESSION:algorithm "$SRC && \
   ros2 run swarm_discovery ${ROS2_NODE} px4_1 & \
   ros2 run swarm_discovery ${ROS2_NODE} px4_2 & \
   ros2 run swarm_discovery ${ROS2_NODE} px4_3 & \
   ros2 run swarm_discovery ${ROS2_NODE} px4_4 & \
   ros2 run swarm_discovery ${ROS2_NODE} px4_5 & wait" Enter
else
  tmux send-keys -t $SESSION:algorithm "$SRC && \
   python3 $PKG/$SCRIPT px4_1 & python3 $PKG/$SCRIPT px4_2 & \
   python3 $PKG/$SCRIPT px4_3 & python3 $PKG/$SCRIPT px4_4 & \
   python3 $PKG/$SCRIPT px4_5 & wait" Enter
fi

sleep 12

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✓ DRONES FLYING — yellow balls tracking teal GT       ║"
echo "║  Check RViz: balls should follow moving drones         ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

if [ -z "$ATTACK" ]; then
  echo "  Press Enter to land and stop demo."
  read -r
else
  ATTACK_NODE=${ATTACK_NODE_MAP[$ATTACK]}
  ATTACK_ARG=${ATTACK_ARGS[$ATTACK]}
  echo "  Attack ready: $ATTACK"
  echo "  ► Press Enter to INJECT attack while drones are in motion..."
  read -r

  tmux new-window -t $SESSION -n attack
  tmux send-keys -t $SESSION:attack "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARG}" Enter
  echo ""
  echo "╔════════════════════════════════════════════════════════╗"
  echo "║  ⚠  ATTACK ACTIVE on moving swarm                     ║"
  echo "╚════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Press Enter to STOP attack..."
  read -r

  tmux kill-window -t $SESSION:attack 2>/dev/null || true
  pkill -f "sybil_registry" 2>/dev/null || true
  pkill -f "replay_attack" 2>/dev/null || true
  pkill -f "wormhole_attack" 2>/dev/null || true
  pkill -f "byzantine_insider" 2>/dev/null || true
  pkill -f "byzantine_targeted" 2>/dev/null || true
  pkill -f "timesync_attack" 2>/dev/null || true

  echo ""
  echo "╔════════════════════════════════════════════════════════╗"
  echo "║  ✓ ATTACK STOPPED — estimate recovering in motion      ║"
  echo "╚════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Press Enter to land and end demo..."
  read -r
fi

echo "  Landing all drones..."
for i in 1 2 3 4 5; do
  ros2 topic pub --once /px4_${i}/fmu/in/vehicle_command \
    px4_msgs/msg/VehicleCommand \
    "{command: 21, param1: 0.0, target_system: $((i+1)), target_component: 1}" \
    2>/dev/null || true
done
sleep 3

echo "  Shutting down (swarm_viz stays alive)..."
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1; kill_motion_nodes
echo ""
echo "  Motion demo complete. swarm_viz: pid=$(pgrep -f swarm_viz || echo 'not running')"
echo ""
