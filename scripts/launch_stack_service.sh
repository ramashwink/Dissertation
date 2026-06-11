#!/bin/bash
# launch_stack_service.sh  (mitigation-experiments branch)
# ==========================================================
# Launches full stack using Design B (service-based allowlist registry).
# Fixed: spawn positions now match 5-drone grid (not 3-drone line),
#        paths point at swarm_discovery package.
#
# Design B finding: blocks Sybil (unknown IDs) but NOT impersonation
# (attacker using a valid ID like px4_2). This is a key dissertation result.
#
# Usage: bash scripts/launch_stack_service.sh
# Prerequisites: start_swarm.sh already running

set -e

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
CODE="$HOME/Dissertation/code"
SESSION="swarm_svc"

SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50 -n sensing

# ── Window 0: Sensing ────────────────────────────────────────────────────────
tmux send-keys -t $SESSION:sensing "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION:sensing
tmux send-keys -t $SESSION:sensing "$SRC && sleep 3 && python3 $CODE/inter_drone_ranging.py" Enter

# ── Window 1: Design B registry service ─────────────────────────────────────
tmux new-window -t $SESSION -n registry_svc
tmux send-keys -t $SESSION:registry_svc \
  "$SRC && ros2 run swarm_discovery swarm_registry_service" Enter

# ── Window 2: Swarm clients (Design B) ──────────────────────────────────────
# Note: swarm_registry_service.py allowlist currently has px4_1/2/3 only.
# To add px4_4 and px4_5, update ALLOWED_NAMESPACES in swarm_registry_service.py
tmux new-window -t $SESSION -n clients
tmux send-keys -t $SESSION:clients \
  "$SRC && sleep 5 && \
  ros2 run swarm_discovery swarm_client px4_1 0.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_client px4_2 2.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_client px4_3 4.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_client px4_4 2.0 2.0 0.0 & \
  ros2 run swarm_discovery swarm_client px4_5 4.0 2.0 0.0 & wait" Enter

# ── Window 3: WLS localisation × 5 ──────────────────────────────────────────
tmux new-window -t $SESSION -n localisation
tmux send-keys -t $SESSION:localisation \
  "$SRC && sleep 8 && \
  ros2 run swarm_discovery coop_loc_dynamic px4_1 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_2 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_3 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_4 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_5 & wait" Enter

# ── Window 4: Visualisation ──────────────────────────────────────────────────
tmux new-window -t $SESSION -n viz
tmux send-keys -t $SESSION:viz \
  "$SRC && ros2 run swarm_discovery swarm_viz" Enter

# ── Window 5: Attack prompt ──────────────────────────────────────────────────
tmux new-window -t $SESSION -n attacks
tmux send-keys -t $SESSION:attacks "$SRC" Enter
tmux send-keys -t $SESSION:attacks "# Design B Sybil attack (unknown IDs — BLOCKED by allowlist):" Enter
tmux send-keys -t $SESSION:attacks "# ros2 run swarm_discovery sybil_service_attack" Enter
tmux send-keys -t $SESSION:attacks "" Enter
tmux send-keys -t $SESSION:attacks "# Design B impersonation attack (valid ID px4_2 — ACCEPTED = vulnerability):" Enter
tmux send-keys -t $SESSION:attacks "# ros2 run swarm_discovery sybil_service_attack  # watch for px4_2 attempt" Enter
tmux send-keys -t $SESSION:attacks "" Enter
tmux send-keys -t $SESSION:attacks "# Compare with Design A:" Enter
tmux send-keys -t $SESSION:attacks "# bash scripts/launch_wls.sh  (Design A, all attacks succeed)" Enter

echo ""
echo "[+] Design B stack launched in session '$SESSION'"
echo "    tmux attach -t $SESSION"
echo ""
echo "Security finding to demonstrate:"
echo "  Sybil (ghost_1/2/3): BLOCKED — not in allowlist"
echo "  Impersonation (px4_2 with wrong spawn): ACCEPTED — allowlist gap"
echo "  Full mitigation requires HMAC tokens or SROS2"
