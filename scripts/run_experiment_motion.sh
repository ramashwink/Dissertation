#!/bin/bash
# run_experiment_motion.sh
# ========================
# Motion variant of run_experiment.sh.
# Drones fly a coordinated pattern (hover/square/circle) while
# localisation and attack experiments run — tests attack effectiveness
# against moving targets.
#
# KEY DIFFERENCES from run_experiment.sh:
#   1. Uses swarm_heartbeat_dynamic (live GT positions, not fixed spawn)
#   2. Launches formation_flight node to command all drones
#   3. Waits for drones to reach altitude before injecting attack
#   4. CSVs labelled with motion pattern: {approach}_px4_N_{attack}_{pattern}.csv
#   5. swarm_viz preserved (same as patched run_experiment.sh)
#
# Usage:
#   bash run_experiment_motion.sh <approach> <attack> [pattern]
#
# Approaches:  wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber
# Attacks:     baseline | sybil | replay | wormhole | sybil_consistent |
#              replay_gradual | byzantine | timesync | targeted_ramp |
#              targeted_osc | targeted_two_drone
# Patterns:    hover | square | circle  (default: hover)
#
# Examples:
#   bash run_experiment_motion.sh ekf_chi2_huber targeted_ramp hover
#   bash run_experiment_motion.sh wls wormhole square
#   bash run_experiment_motion.sh ransac byzantine circle
#
# QGC monitoring ports:
#   px4_1: 18571   px4_2: 18572   px4_3: 18573
#   px4_4: 18574   px4_5: 18575
#
# Prerequisites:
#   start_swarm.sh must already be running.
#   Drones must be in a state where arming is possible (pre-arm checks pass).

set +e

APPROACH=${1:-}
ATTACK=${2:-}
PATTERN=${3:-hover}

if [ -z "$APPROACH" ] || [ -z "$ATTACK" ]; then
  echo "Usage: bash run_experiment_motion.sh <approach> <attack> [pattern]"
  echo ""
  echo "Approaches: wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber"
  echo "Attacks:    baseline | sybil | replay | wormhole | byzantine | timesync"
  echo "            targeted_ramp | targeted_osc | targeted_two_drone"
  echo "Patterns:   hover | square | circle  (default: hover)"
  exit 1
fi

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
CODE="$HOME/Dissertation/code"
METRICS="$HOME/Dissertation/evidence/metrics/motion"
GT_DIR="$HOME/Dissertation/evidence/gt/motion"
# WSL2 doesn't reliably support IPv4 multicast, which Fast-DDS needs for its
# default SPDP discovery. Point every node at the Fast-DDS discovery server
# (started in start_swarm_motion.sh) instead — no multicast involved.
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash && export ROS_DISCOVERY_SERVER=127.0.0.1:11811"

mkdir -p $METRICS $GT_DIR

WARMUP_SEC=25      # longer — drones need to arm + reach altitude
EXPERIMENT_SEC=90
ATTACK_DELAY=8
ALTITUDE_WAIT=60   # max wait for drones to reach OFFBOARD before logging (polled, not fixed)

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
  [sybil]="3 px4_2"
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
SESSION="motion_${APPROACH}_${ATTACK}_${PATTERN}"

if [ -z "$SCRIPT" ]; then echo "Unknown approach: $APPROACH"; exit 1; fi

# ── Helpers ──────────────────────────────────────────────────────────────────
kill_motion_nodes() {
  MYPID=$$
  for pattern in "coop_loc" "ground_truth_demux" "inter_drone_ranging" \
                 "swarm_registry" "swarm_heartbeat" "formation_flight" \
                 "extract_ground_truth" "sybil_registry" "sybil_consistent" \
                 "replay_attack" "wormhole_attack" "byzantine_insider" \
                 "byzantine_targeted" "timesync_attack"; do
    pgrep -f "$pattern" | grep -v "^${MYPID}$" | xargs -r kill -15 2>/dev/null || true
  done
}

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  MOTION EXPERIMENT: $APPROACH / $ATTACK / $PATTERN"
echo "════════════════════════════════════════════════════════════"
echo ""

# ── Step 0: Cleanup (preserve swarm_viz) ─────────────────────────────────────
echo "[0/7] Cleaning up (preserving swarm_viz)..."
tmux kill-session -t "motion_"* 2>/dev/null || true
sleep 1
kill_motion_nodes
sleep 2
echo "  Done."

# Gazebo runs for the whole batch — PX4 land/disarm never moves the model
# pose back to its grid spawn. A drone that crashed/drifted in an earlier
# run would otherwise stay displaced for every run after it.
echo "  Resetting drone poses to grid spawn..."
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
ros2 run swarm_discovery reset_swarm_poses

# ── Step 1: Ensure swarm_viz ─────────────────────────────────────────────────
echo "[1/7] Checking swarm_viz..."
if ! pgrep -f "swarm_discovery.*swarm_viz" > /dev/null 2>&1; then
  source /opt/ros/humble/setup.bash
  source "$WS/install/setup.bash"
  export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
  ros2 run swarm_discovery swarm_viz > /tmp/swarm_viz.log 2>&1 &
  sleep 2
  echo "  swarm_viz started (pid $(pgrep -f "swarm_discovery.*swarm_viz"))"
else
  echo "  swarm_viz already running ✓"
fi

# ── Step 2: Sensing ───────────────────────────────────────────────────────────
echo "[2/7] Starting sensing..."
tmux new-session -d -s $SESSION -x 240 -y 60 -n gt
tmux send-keys -t $SESSION:gt \
  "$SRC && python3 $CODE/ground_truth_demux.py" Enter

tmux new-window -t $SESSION -n ranging
tmux send-keys -t $SESSION:ranging \
  "$SRC && python3 $CODE/inter_drone_ranging.py" Enter
sleep 3

# ── Step 3: Registry + DYNAMIC heartbeats ────────────────────────────────────
echo "[3/7] Starting registry + dynamic heartbeats..."
tmux new-window -t $SESSION -n registry
tmux send-keys -t $SESSION:registry \
  "$SRC && ros2 run swarm_discovery swarm_registry" Enter
sleep 4

# One window per drone — dynamic (broadcasts live GT position)
for i in 1 2 3 4 5; do
  tmux new-window -t $SESSION -n "hb${i}"
  tmux send-keys -t $SESSION:hb${i} \
    "$SRC && ros2 run swarm_discovery swarm_heartbeat_dynamic px4_${i}" Enter
  sleep 0.3
done

echo "  Waiting 8s for registry to populate..."
sleep 8

# Verify registry
SEEN=$(ros2 topic echo /swarm/registry --once 2>/dev/null | grep "total_seen" | awk '{print $2}' || echo 0)
echo "  Registry total_seen=$SEEN"

# ── Step 4: Formation flight ──────────────────────────────────────────────────
echo "[4/7] Starting formation flight (pattern=$PATTERN)..."
tmux new-window -t $SESSION -n flight
tmux send-keys -t $SESSION:flight \
  "$SRC && ros2 run swarm_discovery formation_flight $PATTERN" Enter

echo "  Waiting for all drones to reach OFFBOARD (max ${ALTITUDE_WAIT}s)..."
echo "  Monitor in QGC: ports 18571-18575"
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
# Poll formation_flight's own readiness marker file instead of a fixed
# sleep or repeated `ros2 topic echo` calls — each of those spins up a
# fresh DDS participant, which adds real CPU load right when the drones
# are already struggling to arm under a heavily oversubscribed CPU.
READY_MARKER="/tmp/formation_flight_all_ready"

# A drone whose uXRCE-DDS bridge comes up slightly later than the others
# (usually the last-spawned one) can end up with a stale pub/sub match to
# formation_flight's very first publisher for it — the match never
# completes and never self-heals no matter how long you wait, but a full
# node restart (fresh publishers) reliably reconnects cleanly. So on
# timeout, restart formation_flight itself and give it one more attempt
# before giving up.
for ATTEMPT in 1 2; do
  rm -f "$READY_MARKER"
  SECONDS=0
  while [ $SECONDS -lt $ALTITUDE_WAIT ]; do
    if [ -f "$READY_MARKER" ]; then
      echo "  All 5 drones reached OFFBOARD after ${SECONDS}s (attempt $ATTEMPT)."
      break
    fi
    sleep 1
  done
  if [ -f "$READY_MARKER" ]; then
    break
  fi
  if [ $ATTEMPT -lt 2 ]; then
    echo "  WARNING: drones not all OFFBOARD after ${SECONDS}s — restarting formation_flight and retrying..."
    tmux send-keys -t $SESSION:flight C-c
    sleep 1
    tmux send-keys -t $SESSION:flight \
      "$SRC && ros2 run swarm_discovery formation_flight $PATTERN" Enter
  else
    echo "  WARNING: drones not all OFFBOARD after ${SECONDS}s and 1 restart — proceeding anyway."
  fi
done
echo "  Waiting 10s buffer for altitude climb..."
sleep 10

# ── Step 5: Localisation ─────────────────────────────────────────────────────
echo "[5/7] Starting localisation: $APPROACH..."
  # Clear stale CSVs to prevent rename collision
  for i in 1 2 3 4 5; do rm -f $HOME/Dissertation/evidence/metrics/${APPROACH}_px4_${i}.csv; done
  echo "  Stale CSVs cleared."

  # RC2 fix: wait for ranging to be flowing before launching localisation
  echo "  Waiting for ranging data on all drones..."
  source /opt/ros/humble/setup.bash
  source "$WS/install/setup.bash"
  export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
  for drone in px4_1 px4_2 px4_3 px4_4 px4_5; do
    nbr="px4_2"; [ "$drone" = "px4_2" ] && nbr="px4_1"
    topic="/${drone}/coop/range_to/${nbr}"
    for attempt in $(seq 1 30); do
      if ros2 topic echo "$topic" --once --no-arr > /dev/null 2>&1; then
        echo "    ${drone}: ranging ✓"
        break
      fi
      sleep 1
    done
  done

tmux new-window -t $SESSION -n algorithm
ROS2_NODE=${ROS2_NODE_MAP[$APPROACH]}

# Launch the 5 per-drone algorithm nodes staggered (not all at once) — firing
# ~20 ROS2 participants (this + logger + registry + heartbeats + ranging) in
# a tight burst can overwhelm Fast-DDS discovery under CPU load, leaving some
# pub/sub pairs permanently unmatched even though everything involved is
# otherwise healthy. Same rationale as the existing heartbeat stagger above.
if [ -n "$ROS2_NODE" ]; then
  tmux send-keys -t $SESSION:algorithm "$SRC" Enter
  for i in 1 2 3 4 5; do
    tmux send-keys -t $SESSION:algorithm \
      "ros2 run swarm_discovery ${ROS2_NODE} px4_${i} &" Enter
    sleep 0.5
  done
  tmux send-keys -t $SESSION:algorithm "wait" Enter
else
  tmux send-keys -t $SESSION:algorithm "export COOP_ATTACK_LABEL=$ATTACK && $SRC" Enter
  for i in 1 2 3 4 5; do
    tmux send-keys -t $SESSION:algorithm \
      "python3 $PKG/$SCRIPT px4_${i} &" Enter
    sleep 0.5
  done
  tmux send-keys -t $SESSION:algorithm "wait" Enter
fi

if [ "$APPROACH" = "wls" ] || [ "$APPROACH" = "ekf" ]; then
  LOGGER_PATH="$WS/src/swarm_discovery/swarm_discovery/coop_loc_logger.py"
  tmux new-window -t $SESSION -n logger
  tmux send-keys -t $SESSION:logger "$SRC && sleep 3" Enter
  for i in 1 2 3 4 5; do
    tmux send-keys -t $SESSION:logger \
      "python3 $LOGGER_PATH $APPROACH px4_${i} &" Enter
    sleep 0.5
  done
  tmux send-keys -t $SESSION:logger "wait" Enter
fi

echo "  Waiting ${WARMUP_SEC}s for localisation to stabilise..."
sleep $WARMUP_SEC

# Ground truth logger
tmux new-window -t $SESSION -n gt_log
tmux send-keys -t $SESSION:gt_log \
  "$SRC && python3 ~/Dissertation/extract_ground_truth.py" Enter
sleep 2

# ── Step 6: Attack ────────────────────────────────────────────────────────────
if [ -n "$ATTACK_NODE" ]; then
  echo "[6/7] Injecting attack: $ATTACK (waiting ${ATTACK_DELAY}s)..."
  sleep $ATTACK_DELAY
  tmux new-window -t $SESSION -n attack
  tmux send-keys -t $SESSION:attack \
    "$SRC && ros2 run swarm_discovery ${ATTACK_NODE} ${ATTACK_ARG}" Enter
  echo "  Attack running."
else
  echo "[6/7] No attack (baseline run)."
fi

# ── Step 7: Collect ───────────────────────────────────────────────────────────
echo "[7/7] Collecting data for ${EXPERIMENT_SEC}s..."
for i in $(seq 1 $EXPERIMENT_SEC); do
  sleep 1
  if [ $((i % 15)) -eq 0 ]; then
    ROWS=$(wc -l < "$HOME/Dissertation/evidence/metrics/${APPROACH}_px4_1.csv" 2>/dev/null || echo 0)
    echo "  t=${i}s  rows: ${ROWS:-0}"
  fi
done

# ── Teardown ──────────────────────────────────────────────────────────────────
echo ""
echo "  Stopping (landing drones + preserving swarm_viz)..."
# Land all drones via offboard command
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
for i in 1 2 3 4 5; do
  ros2 topic pub --once \
    /px4_${i}/fmu/in/vehicle_command \
    px4_msgs/msg/VehicleCommand \
    "{command: 21, param1: 0.0, target_system: $((i+1)), target_component: 1}" \
    2>/dev/null || true
done

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 3
kill_motion_nodes
sleep 2

# Rename CSVs with motion tag
for i in 1 2 3 4 5; do
  SRC_CSV="$HOME/Dissertation/evidence/metrics/${APPROACH}_px4_${i}.csv"
  if [ "$ATTACK" = "baseline" ]; then
    DST="$METRICS/${APPROACH}_px4_${i}_baseline_${PATTERN}.csv"
  else
    DST="$METRICS/${APPROACH}_px4_${i}_${ATTACK}_${PATTERN}.csv"
  fi
  [ -f "$SRC_CSV" ] && mv "$SRC_CSV" "$DST" && echo "  Saved: $(basename $DST)"
done

# GT CSVs
for i in 1 2 3 4 5; do
  GT_SRC="$HOME/Dissertation/evidence/gt/gt_px4_${i}.csv"
  GT_DST="$GT_DIR/gt_px4_${i}_${APPROACH}_${ATTACK}_${PATTERN}.csv"
  [ -f "$GT_SRC" ] && cp "$GT_SRC" "$GT_DST"
done

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE: $APPROACH / $ATTACK / $PATTERN"
echo "  CSVs: $METRICS/"
echo "  swarm_viz: pid=$(pgrep -f "swarm_discovery.*swarm_viz" || echo 'not running')"
echo "════════════════════════════════════════════════════════════"
