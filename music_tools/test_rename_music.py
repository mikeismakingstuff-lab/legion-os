"""
test_rename_music.py
Tests for rename_music.py
"""

import json
import os
import shutil
from pathlib import Path
import pytest
import openpyxl
import mutagen

from rename_music import (
    sanitize_filename,
    update_tags,
    execute_rollback,
)


# ═══════════════════════════════════════════════════════════════
# Unit Tests for Helpers
# ═══════════════════════════════════════════════════════════════

def test_sanitize_filename():
    assert sanitize_filename("Artist: Title") == "Artist - Title"
    assert sanitize_filename("Artist/Title") == "Artist-Title"
    assert sanitize_filename("Artist? <Title> *") == "Artist Title"
    assert sanitize_filename("  Artist   -   Title  ") == "Artist - Title"
    assert sanitize_filename("Artist - Title.") == "Artist - Title"


def test_update_tags_mp3(tmp_path):
    # Create a dummy MP3 file
    mp3_path = tmp_path / "test.mp3"
    # Write empty bytes or valid MP3 header?
    # mutagen might fail if the file is completely empty or not a valid MP3.
    # Let's write a minimal valid MP3 file or mock mutagen.File.
    # Actually, mutagen.File can parse a minimal file, but let's see if we can use a mock or create a simple file.
    # Let's write a dummy file and see if mutagen can handle it.
    mp3_path.write_bytes(b"ID3v2.3.0\x00\x00\x00\x00\x00\x00")
    
    # Since it's a dummy file, mutagen might fail to parse it. Let's mock mutagen.File if needed,
    # or write a test that handles the exception.
    # Let's mock mutagen.File to return a dict-like object.
    class MockAudio(dict):
        def save(self):
            self.saved = True

    original_file = mutagen.File
    try:
        mutagen.File = lambda path, easy=True: MockAudio()
        ok, err = update_tags(mp3_path, "Test Artist", "Test Title")
        assert ok is True
        assert err is None
    finally:
        mutagen.File = original_file


# ═══════════════════════════════════════════════════════════════
# Integration Tests with Mock Directory and Excel
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def setup_test_env(tmp_path):
    # Create audio dir
    audio_dir = tmp_path / "RadioStation"
    audio_dir.mkdir()

    # Create dummy audio files
    file1 = audio_dir / "old_song_1.mp3"
    file1.write_bytes(b"")
    file2 = audio_dir / "old_song_2.flac"
    file2.write_bytes(b"")
    file3 = audio_dir / "conflict_song.mp3"
    file3.write_bytes(b"")
    file4 = audio_dir / "conflict_song_dup.mp3"
    file4.write_bytes(b"")

    # Create Excel file
    xlsx_path = tmp_path / "library.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Legion Results"
    ws.append(["Name", "FullName", "Artist", "Title"])
    ws.append(["old_song_1.mp3", "old_song_1.mp3", "Artist One", "Title One"])
    ws.append(["old_song_2.flac", "old_song_2.flac", "Artist Two", "Title Two"])
    # These two will conflict as they both resolve to "Artist Three - Title Three"
    ws.append(["conflict_song.mp3", "conflict_song.mp3", "Artist Three", "Title Three"])
    ws.append(["conflict_song_dup.mp3", "conflict_song_dup.mp3", "Artist Three", "Title Three"])
    wb.save(xlsx_path)

    return xlsx_path, audio_dir


def test_dry_run(setup_test_env, monkeypatch):
    xlsx_path, audio_dir = setup_test_env

    # Run main in dry-run mode
    import sys
    monkeypatch.setattr(sys, "argv", ["rename_music.py", str(xlsx_path), str(audio_dir)])

    # We can run main and capture stdout
    from rename_music import main
    
    # Mock update_tags to avoid mutagen errors on empty files
    monkeypatch.setattr("rename_music.update_tags", lambda p, a, t: (True, None))

    # Run main (should exit 0)
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0

    # Verify files were NOT renamed
    assert (audio_dir / "old_song_1.mp3").exists()
    assert not (audio_dir / "Artist One - Title One.mp3").exists()


def test_commit_and_rollback(setup_test_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    xlsx_path, audio_dir = setup_test_env

    # Run main in commit mode
    import sys
    monkeypatch.setattr(sys, "argv", ["rename_music.py", str(xlsx_path), str(audio_dir), "--commit"])

    # Mock update_tags
    monkeypatch.setattr("rename_music.update_tags", lambda p, a, t: (True, None))

    # Run main
    from rename_music import main
    main()

    # Verify files WERE renamed
    assert not (audio_dir / "old_song_1.mp3").exists()
    assert (audio_dir / "Artist One - Title One.mp3").exists()
    assert (audio_dir / "Artist Two - Title Two.flac").exists()
    
    # Verify conflict resolution
    assert (audio_dir / "Artist Three - Title Three.mp3").exists()
    assert (audio_dir / "Artist Three - Title Three (1).mp3").exists()

    # Find the transaction log
    logs = list(Path(".").glob("rename_transaction_*.json"))
    assert len(logs) >= 1
    log_path = logs[0]

    try:
        # Run rollback
        monkeypatch.setattr(sys, "argv", ["rename_music.py", "--rollback", str(log_path)])
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 0

        # Verify files were rolled back to original names
        assert (audio_dir / "old_song_1.mp3").exists()
        assert not (audio_dir / "Artist One - Title One.mp3").exists()
        assert (audio_dir / "old_song_2.flac").exists()
        assert (audio_dir / "conflict_song.mp3").exists()
        assert (audio_dir / "conflict_song_dup.mp3").exists()

    finally:
        # Clean up transaction log
        if log_path.exists():
            log_path.unlink()
