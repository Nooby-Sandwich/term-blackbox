import json
import struct

# The maximum size of a single message (e.g., 10 Megabytes)
# This prevents a malicious client from crashing the server by sending 
# a giant "length" header (e.g., "I am about to send 4GB of data!").
MAX_MESSAGE_SIZE = 10 * 1024 * 1024

def send_message(sock, message_dict):
    """
    Packs a dictionary into JSON, prepends a 4-byte length header,
    and sends it over the socket.
    """
    # 1. Convert the dictionary to a JSON string, then to byte
    json_bytes = json.dumps(message_dict).encode('utf-8')

    # 2. Check if it's too big
    if len(json_bytes) > MAX_MESSAGE_SIZE:
        raise ValueError("Message is too large to send.")

    # 3. Pack the length into 4 bytes.
    # '!I' means: '!' = Network byte order (Big-Endian), 'I' = Unsigned Integer (4 bytes)
    header = struct.pack('!I', len(json_bytes))

    # 4. Send the header and the payload
    sock.sendall(header + json_bytes)


def recv_message(sock):
    """
    Reads exactly 4 bytes to get the length, then reads that many bytes
    to get the full JSON message.
    """
    header = recv_exact(sock, 4)
    if not header:
        return None # Connection closed

    # 2. Unpack the header to get the message length
    msg_length = struct.unpack('!I', header)[0]

    # 3. Sanity check
    if msg_length > MAX_MESSAGE_SIZE:
        raise ValueError("Received message is too large.")

    # 4. Read exactly `msg_length` bytes
    payload = recv_exact(sock, msg_length)
    if not payload:
        return None

    # 5. Decode and parse the JSON back into a dictionary
    return json.loads(payload.decode('utf-8'))

def recv_exact(sock, num_bytes):
    """
    Helper function: TCP might split data into chunks. 
    We need to loop until we have exactly `num_bytes`.
    """
    buffer = bytearray()
    while len(buffer) < num_bytes:
        # Read whatever is available, up to the remaining amount needed
        chunk = sock.recv(num_bytes - len(buffer))
        if not chunk:
            # Connection dropped
            return None
        buffer.extend(chunk)
    return bytes(buffer)



