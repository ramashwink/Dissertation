import socket, time, collections

# Listen on 14550 with REUSEADDR to share with PX4
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
sock.bind(('127.0.0.1', 14550))
sock.settimeout(0.01)

sources = collections.Counter()
start = time.time()

print("[*] Capturing on 14550 for 65 seconds...")

while time.time() - start < 65:
    try:
        data, addr = sock.recvfrom(1024)
        sources[addr[0], addr[1]] += 1
    except socket.timeout:
        pass

sock.close()
print(f"\n--- Sybil Evidence: Unique Source Ports ---")
for addr, count in sorted(sources.items(), key=lambda x: -x[1]):
    print(f"  {addr[0]}:{addr[1]:5d}  →  {count:4d} packets")
print(f"\nTotal unique source addresses : {len(sources)}")
print(f"Sybil identities detected     : {len(sources)}")
