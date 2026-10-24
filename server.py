import socket
import time

def start_server():
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_address = ('0.0.0.0', 5005) # Listen on port 5005
    sock.bind(server_address)
    print("Server listening on port 5005...")

    while True:
        # Receive data
        data, address = sock.recvfrom(1024)
        
        # Parse data: format is "SEQ_NUMBER:TIMESTAMP"
        message = data.decode('utf-8')
        parts = message.split(':')
        seq_num = parts[0]
        client_time = float(parts[1])
        
        current_time = time.time()
        print(f"Received Packet {seq_num} from {address} | Server Time: {current_time:.4f}")

        # Send reply back with the original sequence number and timestamp
        reply = f"ACK:{seq_num}:{client_time}"
        sock.sendto(reply.encode('utf-8'), address)

if __name__ == "__main__":
    start_server()