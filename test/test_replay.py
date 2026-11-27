import json
import os
import sys

import replay  # tools/replay.py (see pythonpath in pytest.ini)


def write_log(path, entries, tail=""):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
        f.write(tail)
    return str(path)


def out(data, ts=1000.0):
    return {"type": "output", "timestamp": ts, "data": data}


def test_snapshot_uses_saved_screen_record(tmp_path, capsys):
    """Regression: assigning screen.display used to raise AttributeError."""
    log = write_log(
        tmp_path / "a.jsonl",
        [out("ignored"), {"type": "screen", "timestamp": 1, "lines": ["PS> echo hi", "hi", ""]}],
    )
    replay.show_snapshot(log)
    printed = capsys.readouterr().out
    assert "saved snapshot" in printed
    assert "PS> echo hi" in printed
    assert "ignored" not in printed


def test_snapshot_falls_back_to_reconstruction(tmp_path, capsys):
    log = write_log(tmp_path / "b.jsonl", [out("old\r\n"), out("\x1b[2J\x1b[Hnew")])
    replay.show_snapshot(log)
    printed = capsys.readouterr().out
    assert "reconstructed" in printed
    assert "new" in printed
    assert "old" not in printed


def test_truncated_last_line_is_skipped(tmp_path, capsys):
    log = write_log(tmp_path / "c.jsonl", [out("fine")], tail='{"type": "outp')
    replay.show_snapshot(log)
    captured = capsys.readouterr()
    assert "fine" in captured.out
    assert "skipping unreadable line" in captured.err


def test_blank_lines_are_ignored(tmp_path):
    log = write_log(tmp_path / "d.jsonl", [out("x")], tail="\n\n")
    assert len(list(replay.iter_entries(log))) == 1


def test_handshake_filter_removes_terminal_queries_only():
    raw = "\x1b[c\x1b[?1004h\x1b[?9001h\x1b[1tPS> \x1b[31mred\x1b[0m"
    assert replay.HANDSHAKE.sub("", raw) == "PS> \x1b[31mred\x1b[0m"


def test_live_playback_filters_handshake_and_caps_delays(tmp_path, capsys, monkeypatch):
    delays = []
    monkeypatch.setattr(replay.time, "sleep", lambda s: delays.append(s))
    log = write_log(
        tmp_path / "e.jsonl",
        [out("\x1b[chello", ts=100.0), out(" world", ts=160.0)],  # 60 s idle gap
    )
    replay.play_live(log, speed=1.0)
    printed = capsys.readouterr().out
    assert "hello world" in printed
    assert "\x1b[c" not in printed
    assert max(delays) <= 0.5


def test_live_playback_resets_terminal_on_exit(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(replay.time, "sleep", lambda s: None)
    log = write_log(tmp_path / "f.jsonl", [out("x")])
    replay.play_live(log)
    assert "\x1b[0m\x1b[?25h" in capsys.readouterr().out


def test_get_log_files_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "LOG_DIR", str(tmp_path))
    old = write_log(tmp_path / "old.jsonl", [out("x")])
    new = write_log(tmp_path / "new.jsonl", [out("x")])
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    (tmp_path / "notes.txt").write_text("not a log")

    assert [os.path.basename(p) for p in replay.get_log_files()] == ["new.jsonl", "old.jsonl"]


def test_get_log_files_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "LOG_DIR", str(tmp_path / "does_not_exist"))
    assert replay.get_log_files() == []


def test_cli_list(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(replay, "LOG_DIR", str(tmp_path))
    write_log(tmp_path / "one.jsonl", [out("x")])
    monkeypatch.setattr(sys, "argv", ["replay.py", "--list"])
    replay.main()
    assert "one.jsonl" in capsys.readouterr().out


def test_cli_without_logs(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(replay, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["replay.py"])
    replay.main()
    assert "No logs found" in capsys.readouterr().out
