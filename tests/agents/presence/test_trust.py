"""Tests for the X trust-stage store."""
import json
import pytest
from pathlib import Path
from soveryn.agents.presence.trust import (
    read_trust_stage,
    set_trust_stage,
    panic_to_zero,
)


class TestReadTrustStage:
    """Tests for read_trust_stage."""

    def test_missing_file_returns_zero(self, tmp_path):
        """Default safe stage is 0 when file is absent."""
        trust_file = tmp_path / "x_trust.json"
        assert read_trust_stage(trust_file) == 0

    def test_read_valid_json(self, tmp_path):
        """Read a valid trust stage from JSON file."""
        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"stage": 1}))
        assert read_trust_stage(trust_file) == 1

    def test_read_all_valid_stages(self, tmp_path):
        """Read each valid stage value: 0, 1, 2."""
        trust_file = tmp_path / "x_trust.json"
        for stage in [0, 1, 2]:
            trust_file.write_text(json.dumps({"stage": stage}))
            assert read_trust_stage(trust_file) == stage

    def test_malformed_json_returns_zero(self, tmp_path):
        """Malformed JSON defaults to safe stage 0, never crashes."""
        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text("{not valid json")
        assert read_trust_stage(trust_file) == 0

    def test_missing_stage_key_returns_zero(self, tmp_path):
        """JSON without 'stage' key defaults to 0."""
        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"other": "value"}))
        assert read_trust_stage(trust_file) == 0

    def test_invalid_stage_value_returns_zero(self, tmp_path):
        """Invalid stage value (not an int, or not in {0,1,2}) defaults to 0."""
        trust_file = tmp_path / "x_trust.json"

        # String value
        trust_file.write_text(json.dumps({"stage": "one"}))
        assert read_trust_stage(trust_file) == 0

        # Out-of-range int
        trust_file.write_text(json.dumps({"stage": 5}))
        assert read_trust_stage(trust_file) == 0

        # Negative int
        trust_file.write_text(json.dumps({"stage": -1}))
        assert read_trust_stage(trust_file) == 0

        # Float
        trust_file.write_text(json.dumps({"stage": 1.5}))
        assert read_trust_stage(trust_file) == 0

    def test_unreadable_file_returns_zero(self, tmp_path):
        """Unreadable file (permission denied) defaults to 0."""
        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"stage": 2}))
        # Remove read permission
        trust_file.chmod(0o000)
        try:
            assert read_trust_stage(trust_file) == 0
        finally:
            # Restore for cleanup
            trust_file.chmod(0o644)


class TestSetTrustStage:
    """Tests for set_trust_stage."""

    def test_set_creates_file(self, tmp_path):
        """set_trust_stage creates the file if it doesn't exist."""
        trust_file = tmp_path / "x_trust.json"
        set_trust_stage(trust_file, 1)
        assert trust_file.exists()
        assert json.loads(trust_file.read_text()) == {"stage": 1}

    def test_set_creates_parent_directory(self, tmp_path):
        """set_trust_stage creates parent directories if needed."""
        trust_file = tmp_path / "subdir" / "deep" / "x_trust.json"
        set_trust_stage(trust_file, 2)
        assert trust_file.exists()
        assert json.loads(trust_file.read_text()) == {"stage": 2}

    def test_set_overwrites_existing_file(self, tmp_path):
        """set_trust_stage overwrites an existing file."""
        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"stage": 0}))
        set_trust_stage(trust_file, 2)
        assert json.loads(trust_file.read_text()) == {"stage": 2}

    def test_set_valid_stages(self, tmp_path):
        """set_trust_stage accepts stages 0, 1, 2."""
        trust_file = tmp_path / "x_trust.json"
        for stage in [0, 1, 2]:
            set_trust_stage(trust_file, stage)
            assert read_trust_stage(trust_file) == stage

    def test_set_invalid_stage_raises_valueerror(self, tmp_path):
        """set_trust_stage raises ValueError for invalid stage values."""
        trust_file = tmp_path / "x_trust.json"

        with pytest.raises(ValueError):
            set_trust_stage(trust_file, -1)

        with pytest.raises(ValueError):
            set_trust_stage(trust_file, 3)

        with pytest.raises(ValueError):
            set_trust_stage(trust_file, 5)

        with pytest.raises(ValueError):
            set_trust_stage(trust_file, "0")

    def test_set_atomic_write(self, tmp_path):
        """set_trust_stage uses atomic write (temp + replace)."""
        trust_file = tmp_path / "x_trust.json"
        # Set initial value
        set_trust_stage(trust_file, 0)
        # Overwrite with new value
        set_trust_stage(trust_file, 2)
        # File should be valid and complete
        assert json.loads(trust_file.read_text()) == {"stage": 2}
        # Check that the file is not corrupted
        assert read_trust_stage(trust_file) == 2


class TestPanicToZero:
    """Tests for panic_to_zero."""

    def test_panic_sets_stage_to_zero(self, tmp_path):
        """panic_to_zero sets the stage to 0."""
        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"stage": 2}))
        panic_to_zero(trust_file)
        assert read_trust_stage(trust_file) == 0

    def test_panic_on_missing_file(self, tmp_path):
        """panic_to_zero works even if file is missing."""
        trust_file = tmp_path / "x_trust.json"
        panic_to_zero(trust_file)
        assert read_trust_stage(trust_file) == 0


class TestCLI:
    """Tests for the CLI interface."""

    def test_cli_set_command(self, tmp_path, monkeypatch):
        """CLI set command writes a stage value."""
        import sys
        from soveryn.agents.presence.trust import main

        trust_file = tmp_path / "x_trust.json"
        monkeypatch.setenv("X_TRUST_PATH", str(trust_file))

        # Test setting to stage 2
        monkeypatch.setattr(sys, "argv", ["trust", "set", "2"])
        try:
            main()
        except SystemExit:
            pass
        assert read_trust_stage(trust_file) == 2

    def test_cli_panic_command(self, tmp_path, monkeypatch):
        """CLI panic command sets stage to 0."""
        import sys
        from soveryn.agents.presence.trust import main

        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"stage": 2}))
        monkeypatch.setenv("X_TRUST_PATH", str(trust_file))

        monkeypatch.setattr(sys, "argv", ["trust", "panic"])
        try:
            main()
        except SystemExit:
            pass
        assert read_trust_stage(trust_file) == 0

    def test_cli_show_command(self, tmp_path, monkeypatch, capsys):
        """CLI show command prints the current stage."""
        import sys
        from soveryn.agents.presence.trust import main

        trust_file = tmp_path / "x_trust.json"
        trust_file.write_text(json.dumps({"stage": 1}))
        monkeypatch.setenv("X_TRUST_PATH", str(trust_file))

        monkeypatch.setattr(sys, "argv", ["trust", "show"])
        try:
            main()
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "1" in captured.out

    def test_cli_default_path(self, monkeypatch, tmp_path):
        """CLI uses default path from Path.home()/'soveryn_vnext'/'data'/'x_trust.json'."""
        import sys
        from pathlib import Path
        from soveryn.agents.presence.trust import main

        # Create a fake home directory structure
        fake_home = tmp_path / "home" / "user"
        fake_home.mkdir(parents=True)
        data_dir = fake_home / "soveryn_vnext" / "data"
        data_dir.mkdir(parents=True)
        trust_file = data_dir / "x_trust.json"

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.delenv("X_TRUST_PATH", raising=False)

        monkeypatch.setattr(sys, "argv", ["trust", "set", "1"])
        try:
            main()
        except SystemExit:
            pass
        assert trust_file.exists()
        assert read_trust_stage(trust_file) == 1

    def test_cli_invalid_stage_argument(self, tmp_path, monkeypatch):
        """CLI set command rejects invalid stage argument."""
        import sys
        from soveryn.agents.presence.trust import main

        trust_file = tmp_path / "x_trust.json"
        monkeypatch.setenv("X_TRUST_PATH", str(trust_file))

        monkeypatch.setattr(sys, "argv", ["trust", "set", "5"])
        with pytest.raises(SystemExit):
            main()


class TestRoundTrip:
    """Round-trip tests: set and read should preserve values."""

    def test_set_read_zero(self, tmp_path):
        """Set and read stage 0."""
        trust_file = tmp_path / "x_trust.json"
        set_trust_stage(trust_file, 0)
        assert read_trust_stage(trust_file) == 0

    def test_set_read_one(self, tmp_path):
        """Set and read stage 1."""
        trust_file = tmp_path / "x_trust.json"
        set_trust_stage(trust_file, 1)
        assert read_trust_stage(trust_file) == 1

    def test_set_read_two(self, tmp_path):
        """Set and read stage 2."""
        trust_file = tmp_path / "x_trust.json"
        set_trust_stage(trust_file, 2)
        assert read_trust_stage(trust_file) == 2

    def test_set_read_multiple_rounds(self, tmp_path):
        """Multiple set/read cycles preserve the value."""
        trust_file = tmp_path / "x_trust.json"
        stages = [0, 1, 2, 0, 2, 1]
        for stage in stages:
            set_trust_stage(trust_file, stage)
            assert read_trust_stage(trust_file) == stage
