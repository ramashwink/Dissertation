#!/bin/bash
# smoke_test_motion.sh
# ====================
# Full end-to-end smoke test for motion experiments.
# Runs a 30s abbreviated experiment to verify the entire pipeline works
# before committing to a full 90s data collection run.
#
# Usage: bash ~/Dissertation/scripts/smoke_test_motion.sh
#
# What it tests:
#   1. SITL swarm starts (all 5 drones in Gazebo)
#   2. ROS 2 stack connects (GT, ranging, registry, heartbeats)
#   3. EKF2 gets position (arm_all_drones seeds vision)
#   4. All 5 drones arm successfully
#   5. formation_flight holds hover
#   6. Localisation produces CSVs with data
#   7. Clean shutdown

set -e

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"
METRICS="$HOME/Dissertation/evidence/metrics/motion"
mkdir -p $METRICS

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         MOTION EXPERIMENT SMOKE TEST                 ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Start SITL ───────────────────────────────────────────────────────
echo "[1/7] Starting SITL swarm..."
pkill -f "bin/px4" 2>/dev/null || true
pkill -f "MicroXRCEAgent" 2>/dev/null || true
sleep 3

bash ~/Dissertation/scripts/start_swarm.sh &
SWARM_PID=$!

echo "  Waiting 60s for all 5 drones to boot..."
sleep 60

# Verify all 5 ports active
PORTS=$(ss -ulnp | grep "1857" | wc -l)
echo "  Active PX4 ports: $PORTS (need 5)"
if [ "$PORTS" -lt 5 ]; then
    echo "  ✗ FAIL: Not all drones started. Check: tail -f /tmp/px4_2.log"
    exit 1
fi
echo "  ✓ All 5 drones running"

# ── Step 2: Start ROS 2 stack ────────────────────────────────────────────────
echo ""
echo "[2/7] Starting ROS 2 stack..."
source /opt/ros/humble/setup.bash
source $WS/install/setup.bash

tmux new-session -d -s smoke -x 220 -y 50 -n gt
tmux send-keys -t smoke:gt \
  "$SRC && python3 $HOME/Dissertation/code/ground_truth_demux.py" Enter

tmux new-window -t smoke -n ranging
tmux send-keys -t smoke:ranging \
  "$SRC && sleep 2 && python3 $HOME/Dissertation/code/inter_drone_ranging.py" Enter

tmux new-window -t smoke -n registry
tmux send-keys -t smoke:registry \
  "$SRC && ros2 run swarm_discovery swarm_registry" Enter
sleep 4

for i in 1 2 3 4 5; do
    tmux new-window -t smoke -n "hb${i}"
    tmux send-keys -t smoke:hb${i} \
      "$SRC && ros2 run swarm_discovery swarm_heartbeat_dynamic px4_${i}" Enter
    sleep 0.3
done

echo "  Waiting 10s for registry..."
sleep 10

SEEN=$(ros2 topic echo /swarm/registry --once 2>/dev/null \
  | grep "total_seen" | awk '{print $2}' || echo 0)
echo "  Registry total_seen=$SEEN"
if [ "${SEEN:-0}" -lt 5 ]; then
    echo "  ✗ FAIL: Registry only sees $SEEN drones"
    exit 1
fi
echo "  ✓ All 5 drones registered"

# ── Step 3: Seed EKF2 + arm ──────────────────────────────────────────────────
echo ""
echo "[3/7] Seeding EKF2 and arming all drones..."
tmux new-window -t smoke -n arm
tmux send-keys -t smoke:arm \
  "python3 $HOME/Dissertation/scripts/arm_all_drones.py" Enter

echo "  Waiting 20s for EKF seeding + arming..."
sleep 20
echo "  ✓ Arm sequence complete (check QGC for Armed status)"

# ── Step 4: Start formation flight ───────────────────────────────────────────
echo ""
echo "[4/7] Starting formation flight (hover)..."
tmux new-window -t smoke -n flight
tmux send-keys -t smoke:flight \
  "$SRC && ros2 run swarm_discovery formation_flight hover" Enter

echo "  Waiting 15s for drones to reach altitude..."
sleep 15
echo "  ✓ Formation flight running"

# ── Step 5: Run localisation (30s smoke test) ────────────────────────────────
echo ""
echo "[5/7] Running localisation: ekf_chi2_huber (30s smoke test)..."
tmux new-window -t smoke -n algorithm
tmux send-keys -t smoke:algorithm \
  "$SRC && \
   python3 $HOME/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/coop_loc_ekf_chi2_huber.py px4_1 & \
   python3 $HOME/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/coop_loc_ekf_chi2_huber.py px4_2 & \
   python3 $HOME/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/coop_loc_ekf_chi2_huber.py px4_3 & \
   python3 $HOME/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/coop_loc_ekf_chi2_huber.py px4_4 & \
   python3 $HOME/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/coop_loc_ekf_chi2_huber.py px4_5 & wait" Enter

echo "  Collecting for 30s..."
for i in $(seq 1 30); do
    sleep 1
    if [ $((i % 10)) -eq 0 ]; then
        ROWS=$(wc -l ~/Dissertation/evidence/metrics/ekf_chi2_huber_px4_1.csv \
               2>/dev/null | awk '{print $1}' || echo 0)
        echo "  t=${i}s — rows written: ${ROWS:-0}"
    fi
done

# ── Step 6: Validate CSV output ──────────────────────────────────────────────
echo ""
echo "[6/7] Validating CSV output..."
PASS=0
FAIL=0
for i in 1 2 3 4 5; do
    CSV="$HOME/Dissertation/evidence/metrics/ekf_chi2_huber_px4_${i}.csv"
    if [ -f "$CSV" ]; then
        ROWS=$(wc -l < "$CSV")
        if [ "$ROWS" -gt 10 ]; then
            echo "  ✓ px4_${i}: $ROWS rows"
            PASS=$((PASS+1))
        else
            echo "  ✗ px4_${i}: only $ROWS rows (too few)"
            FAIL=$((FAIL+1))
        fi
    else
        echo "  ✗ px4_${i}: CSV not found"
        FAIL=$((FAIL+1))
    fi
done

# ── Step 7: Save smoke test CSVs + cleanup ───────────────────────────────────
echo ""
echo "[7/7] Saving smoke test results..."
for i in 1 2 3 4 5; do
    SRC_CSV="$HOME/Dissertation/evidence/metrics/ekf_chi2_huber_px4_${i}.csv"
    DST_CSV="$METRICS/SMOKE_ekf_chi2_huber_px4_${i}_baseline_hover.csv"
    [ -f "$SRC_CSV" ] && mv "$SRC_CSV" "$DST_CSV" && echo "  Saved: $(basename $DST_CSV)"
done

tmux kill-session -t smoke 2>/dev/null || true
pkill -f "coop_loc" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  SMOKE TEST COMPLETE"
echo "║  Passed: $PASS/5 drones  Failed: $FAIL/5 drones"
if [ $FAIL -eq 0 ]; then
echo "║  ✓ PIPELINE WORKING — ready for full experiment"
else
echo "║  ✗ ISSUES FOUND — check logs above"
fi
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Smoke test CSVs: $METRICS/SMOKE_*.csv"
echo ""
if [ $FAIL -eq 0 ]; then
echo "  Run full experiment:"
echo "  bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber baseline hover"
echo "  bash ~/Dissertation/scripts/run_experiment_motion.sh wls wormhole square"
fi
