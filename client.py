import socket
import time

def start_client(server_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0) # 2 second timeout for packet loss detection
    
    server_address = (server_ip, 5005)
    total_packets = 10
    lost_packets = 0
    
    print(f"Starting Diagnostic Tool targeting {server_ip}...")
    print("-" * 50)

    for i in range(1, total_packets + 1):
        send_time = time.time()
        message = f"{i}:{send_time}"
        
        try:
            # Send UDP probe
            sock.sendto(message.encode('utf-8'), server_address)
            
            # Wait for reply
            data, server = sock.recvfrom(1024)
            receive_time = time.time()
            
            # Calculate RTT
            rtt = (receive_time - send_time) * 1000 # in milliseconds
            print(f"Packet {i}: Success | RTT: {rtt:.4f} ms")
            
        except socket.timeout:
            lost_packets += 1
            print(f"Packet {i}: LOST (Timeout)")
            
    print("-" * 50)
    print(f"Summary: Sent {total_packets}, Lost {lost_packets}, Loss Rate: {(lost_packets/total_packets)*100}%")
    sock.close()

if __name__ == "__main__":
    # Default to 10.0.0.2 (h2 in mininet), but can be passed as argument
    import sys
    target_ip = sys.argv[1] if len(sys.argv) > 1 else '10.0.0.2'
    start_client(target_ip)