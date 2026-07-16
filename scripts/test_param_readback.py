#!/usr/bin/env python3
"""
test_param_readback.py
=======================
Manual test: does param_set_send actually land, and can we confirm it via
PARAM_VALUE read-back? set_rc_params.py currently fires param_set_send with
no confirmation — this script checks whether that's actually a problem
before we add retry logic to the real script.

Usage:
    python3 test_param_readback.py            # test all 5 drones
    python3 test_param_readback.py 2          # test just px4_2
"""
import sys
import time
from pymavlink import mavutil

PORTS = {1: 18571, 2: 18572, 3: 18573, 4: 18574, 5: 18575}
TEST_PARAM = b'COM_OF_LOSS_T'
TEST_VALUE = 5.0
PARAM_TYPE = 9  # MAV_PARAM_TYPE_REAL32
READ_TIMEOUT = 2.0


def set_and_verify(sysid, port, attempts=3):
    conn = mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=254)
    time.sleep(0.4)

    conn.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
    hb = conn.wait_heartbeat(timeout=3)
    print(f"  px4_{sysid}: heartbeat {'received from sysid='+str(hb.get_srcSystem()) if hb else 'NONE'}")

    for attempt in range(1, attempts + 1):
        conn.mav.param_set_send(sysid, 1, TEST_PARAM, TEST_VALUE, PARAM_TYPE)

        conn.mav.param_request_read_send(sysid, 1, TEST_PARAM, -1)
        deadline = time.time() + READ_TIMEOUT
        got = None
        while time.time() < deadline:
            msg = conn.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.3)
            if msg is None:
                continue
            name = msg.param_id.rstrip('\x00') if isinstance(msg.param_id, str) else \
                   msg.param_id.decode().rstrip('\x00')
            if name == TEST_PARAM.decode():
                got = msg.param_value
                break

        if got is not None and abs(got - TEST_VALUE) < 1e-3:
            print(f"  px4_{sysid}: attempt {attempt} -> CONFIRMED {TEST_PARAM.decode()}={got}")
            return True
        else:
            print(f"  px4_{sysid}: attempt {attempt} -> "
                  f"{'no PARAM_VALUE reply' if got is None else f'mismatch (got {got})'}")

    print(f"  px4_{sysid}: FAILED after {attempts} attempts")
    return False


def main():
    targets = [int(sys.argv[1])] if len(sys.argv) > 1 else list(PORTS.keys())
    print(f"[TEST] Verifying param set+read-back for {TEST_PARAM.decode()}={TEST_VALUE} "
          f"on {len(targets)} drone(s)...")
    results = {}
    for sysid in targets:
        results[sysid] = set_and_verify(sysid, PORTS[sysid])

    print()
    print("=== SUMMARY ===")
    for sysid, ok in results.items():
        print(f"  px4_{sysid}: {'OK' if ok else 'FAILED'}")
    n_fail = sum(1 for ok in results.values() if not ok)
    print(f"\n{len(results) - n_fail}/{len(results)} confirmed on first pass.")


if __name__ == "__main__":
    main()
