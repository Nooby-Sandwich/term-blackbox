import json
import struct
import threading

import pytest

from blackbox.protocol import MAX_MESSAGE_SIZE, recv_message, send_message


def test_roundtrip_preserves_unicode_and_escape_codes(sock_pair):
    a, b = sock_pair
    msg = {"type": "output", "data": "\x1b[31mred\x1b[0m héllo 日本 \r\n"}
    send_message(a, msg)
    assert recv_message(b) == msg


def test_messages_arrive_in_order(sock_pair):
    a, b = sock_pair
    for i in range(50):
        send_message(a, {"type": "input", "data": str(i)})
    assert [recv_message(b)["data"] for _ in range(50)] == [str(i) for i in range(50)]


def test_large_message(sock_pair):
    a, b = sock_pair
    big = {"type": "output", "data": "x" * 2_000_000}
    # The sender can block until the receiver drains the socket buffer.
    t = threading.Thread(target=send_message, args=(a, big))
    t.start()
    assert recv_message(b) == big
    t.join(5)


def test_fragmented_delivery_is_reassembled(sock_pair):
    """TCP may deliver a message in many tiny pieces."""
    a, b = sock_pair
    payload = json.dumps({"type": "input", "data": "hello"}).encode()
    raw = struct.pack("!I", len(payload)) + payload

    def dribble():
        for i in range(len(raw)):
            a.sendall(raw[i : i + 1])

    t = threading.Thread(target=dribble)
    t.start()
    assert recv_message(b) == {"type": "input", "data": "hello"}
    t.join(5)


def test_closed_connection_returns_none(sock_pair):
    a, b = sock_pair
    a.close()
    assert recv_message(b) is None


def test_truncated_header_returns_none(sock_pair):
    a, b = sock_pair
    a.sendall(b"\x00\x00")
    a.close()
    assert recv_message(b) is None


def test_truncated_payload_returns_none(sock_pair):
    a, b = sock_pair
    a.sendall(struct.pack("!I", 100) + b"only ten b")
    a.close()
    assert recv_message(b) is None


def test_oversized_length_header_is_rejected(sock_pair):
    a, b = sock_pair
    a.sendall(struct.pack("!I", MAX_MESSAGE_SIZE + 1))
    with pytest.raises(ValueError):
        recv_message(b)


def test_sending_oversized_message_raises(sock_pair):
    a, _ = sock_pair
    with pytest.raises(ValueError):
        send_message(a, {"type": "output", "data": "x" * (MAX_MESSAGE_SIZE + 1)})


def test_invalid_json_raises(sock_pair):
    a, b = sock_pair
    body = b"not json at all"
    a.sendall(struct.pack("!I", len(body)) + body)
    with pytest.raises(ValueError):  # json.JSONDecodeError subclasses ValueError
        recv_message(b)
