import os
import tempfile
import textwrap
import unittest
import importlib.util
from pathlib import Path


def _load_monitor_module():
    repo_root = Path(__file__).resolve().parents[2]
    monitor_py = repo_root / "monitor" / "monitor.py"
    spec = importlib.util.spec_from_file_location("reolink_monitor", monitor_py)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestIniConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.monitor = _load_monitor_module()

    def test_load_config_defaults(self):
        ini = """\
        [monitor]
        # intentionally empty: defaults should apply

        [obs]
        # intentionally empty

        [intervals]
        # intentionally empty

        [permissions]
        # intentionally empty
        """
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(textwrap.dedent(ini))
            path = f.name

        try:
            cfg = self.monitor.load_config(path)
            self.assertEqual(cfg["base_path"], "/home/camerauser/driveway")
            self.assertEqual(cfg["container_staging_path"], "/fakecam")
            self.assertEqual(cfg["error_video_name"], "ERROR_ALERT.mp4")
            self.assertEqual(cfg["required_containers"], ["obs_compositor", "mediamtx"])
            self.assertEqual(cfg["retention_days"], 7)
            self.assertEqual(cfg["cooldown_seconds"], 10)
            self.assertEqual(cfg["log_file"], "/var/log/reolink_monitor.log")
            self.assertEqual(cfg["send_to"], "root")

            self.assertEqual(cfg["obs_host"], "127.0.0.1")
            self.assertEqual(cfg["obs_port"], 4455)
            self.assertEqual(cfg["obs_media_input"], "Alert_Video")
            self.assertEqual(cfg["obs_scene_alert"], "Alert")
            self.assertEqual(cfg["obs_scene_standby"], "Standby")

            self.assertEqual(cfg["health_check_seconds"], 300)
            self.assertEqual(cfg["main_loop_sleep_seconds"], 10)
            self.assertEqual(cfg["directory_poll_seconds"], 30)

            self.assertTrue(cfg["permissions_enabled"])
            self.assertEqual(cfg["permissions_user_group"], "")
            self.assertEqual(cfg["permissions_file_mode"], 0o644)
            self.assertEqual(cfg["permissions_dir_mode"], 0o755)
        finally:
            os.unlink(path)

    def test_permissions_parsing(self):
        ini = """\
        [permissions]
        enabled = off
        user_group = 1000:1001
        file_mask = 600
        directory_mask = 0750
        """
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(textwrap.dedent(ini))
            path = f.name

        try:
            cfg = self.monitor.load_config(path)
            self.assertFalse(cfg["permissions_enabled"])
            self.assertEqual(cfg["permissions_user_group"], "1000:1001")
            self.assertEqual(cfg["permissions_file_mode"], 0o600)
            self.assertEqual(cfg["permissions_dir_mode"], 0o750)
        finally:
            os.unlink(path)

    def test_octal_mode_accepts_common_forms(self):
        parse = self.monitor._parse_octal_mode
        self.assertEqual(parse("644", 0), 0o644)
        self.assertEqual(parse("0644", 0), 0o644)
        self.assertEqual(parse("0o644", 0), 0o644)
        self.assertEqual(parse("", 0o777), 0o777)
        self.assertEqual(parse(None, 0o777), 0o777)

    def test_validate_config_detects_missing_base_path(self):
        cfg = {
            "base_path": "/definitely/not/a/real/dir",
            "host_staging_path": "",
            "error_video_name": "ERROR_ALERT.mp4",
            "required_containers": ["obs_compositor"],
            "obs_port": 4455,
            "retention_days": 7,
            "cooldown_seconds": 10,
            "health_check_seconds": 300,
            "main_loop_sleep_seconds": 10,
            "directory_poll_seconds": 30,
            "permissions_enabled": False,
            "permissions_user_group": "",
            "permissions_file_mode": 0o644,
            "permissions_dir_mode": 0o755,
        }
        errors, warnings = self.monitor.validate_config(cfg)
        self.assertTrue(any("base_path" in w for w in warnings))

    def test_validate_config_accepts_minimal_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "base_path": tmp,
                "host_staging_path": tmp,
                "error_video_name": "ERROR_ALERT.mp4",
                "required_containers": ["obs_compositor", "mediamtx"],
                "obs_port": 4455,
                "retention_days": 7,
                "cooldown_seconds": 10,
                "health_check_seconds": 300,
                "main_loop_sleep_seconds": 10,
                "directory_poll_seconds": 30,
                "permissions_enabled": True,
                "permissions_user_group": "",
                "permissions_file_mode": 0o644,
                "permissions_dir_mode": 0o755,
            }
            errors, warnings = self.monitor.validate_config(cfg)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
