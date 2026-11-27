"""Tests for BlackBox (ring buffer, pyte screen, atomic logging).

Assumes the API of recorder.BlackBox:
  BlackBox(rows, cols), .record(data), .resize(rows, cols), .flush(force=False),
  .buffer (deque), .screen (pyte.Screen), .path, module constants LOG_DIR / BUFFER_SIZE.
"""

import json
import os
import threading

from blackbox import recorder


def read_log(box):
    with open(box.path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_flush_writes_valid_jsonl(box):
    box.record("hello ")
    box.record("world")
    box.flush()

    entries = read_log(box)
    outputs = [e for e in entries if e["type"] == "output"]
    assert [e["data"] for e in outputs] == ["hello ", "world"]
    assert all(isinstance(e["timestamp"], float) for e in outputs)
    assert entries[-1]["type"] == "screen"


def test_ring_buffer_keeps_only_newest(log_dir, monkeypatch):
    monkeypatch.setattr(recorder, "BUFFER_SIZE", 3)
    box = recorder.BlackBox(rows=5, cols=40)
    for i in range(10):
        box.record(f"chunk{i}")
    box.flush()

    data = [e["data"] for e in read_log(box) if e["type"] == "output"]
    assert data == ["chunk7", "chunk8", "chunk9"]


def test_repeated_flush_does_not_duplicate_entries(box):
    box.record("once")
    box.flush()
    box.flush(force=True)
    box.flush(force=True)

    outputs = [e for e in read_log(box) if e["type"] == "output"]
    assert len(outputs) == 1


def test_flush_skips_write_when_nothing_changed(box):
    box.record("x")
    box.flush()
    os.remove(box.path)
    box.flush()  # not dirty -> must not recreate the file
    assert not os.path.exists(box.path)
    box.flush(force=True)  # force -> rewrites it
    assert os.path.exists(box.path)


def test_empty_buffer_writes_nothing(box):
    box.flush(force=True)
    assert not os.path.exists(box.path)


def test_no_temp_file_left_behind(box, log_dir):
    box.record("x")
    box.flush()
    assert [p.name for p in log_dir.iterdir() if p.name.endswith(".tmp")] == []


def test_screen_snapshot_applies_ansi(box):
    box.record("old text\r\n")
    box.record("\x1b[2J\x1b[Hnew text")  # clear screen, home cursor, write
    box.flush()

    snapshot = read_log(box)[-1]
    assert snapshot["type"] == "screen"
    assert snapshot["lines"][0].startswith("new text")
    assert not any("old text" in line for line in snapshot["lines"])


def test_raw_ansi_and_unicode_survive_json_roundtrip(box):
    raw = "\x1b[31mred\x1b[0m 日本 \x00\x07"
    box.record(raw)
    box.flush()
    assert read_log(box)[0]["data"] == raw


def test_resize_updates_virtual_screen(box):
    box.resize(10, 100)
    assert box.screen.lines == 10
    assert box.screen.columns == 100


def test_garbage_input_does_not_crash_recording(box):
    box.record("\x1b[999999999;;;;zzz\x1b]0;title\x07\x1b")
    box.record("still recording")
    box.flush()
    assert len([e for e in read_log(box) if e["type"] == "output"]) == 2


def test_concurrent_record_and_flush_keeps_log_valid(box):
    stop = threading.Event()

    def writer(n):
        for i in range(200):
            box.record(f"t{n}-{i}\r\n")

    def flusher():
        while not stop.is_set():
            box.flush(force=True)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    f = threading.Thread(target=flusher)
    f.start()
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    stop.set()
    f.join(10)

    box.flush(force=True)
    entries = read_log(box)  # raises if any line is corrupt
    assert entries[-1]["type"] == "screen"
