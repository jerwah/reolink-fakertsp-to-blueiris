import argparse
import configparser
import logging
import os
import stat
import subprocess
import sys
import time
from datetime import datetime
import grp
import pwd

import obsws_python as obs
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "monitor.ini")


_CFG: dict = {}


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _parse_bool(value: object | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_octal_mode(value: object | None, default: int) -> int:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if not raw:
        return default
    try:
        if raw.startswith("0o"):
            return int(raw, 8)
        if raw.startswith("0"):
            return int(raw, 8)
        # If user enters 644/755, treat as octal digits.
        if all(ch in "01234567" for ch in raw):
            return int(raw, 8)
        return int(raw, 8)
    except Exception:
        return default


def _resolve_uid_gid(user_group: str) -> tuple[int | None, int | None]:
    """Resolve a `user:group` string to uid/gid. Empty parts are ignored."""
    if not user_group:
        return None, None
    if ":" not in user_group:
        user_part = user_group.strip()
        group_part = ""
    else:
        user_part, group_part = (part.strip() for part in user_group.split(":", 1))

    uid: int | None = None
    gid: int | None = None

    if user_part:
        try:
            uid = int(user_part)
        except ValueError:
            uid = pwd.getpwnam(user_part).pw_uid

    if group_part:
        try:
            gid = int(group_part)
        except ValueError:
            gid = grp.getgrnam(group_part).gr_gid

    return uid, gid


def load_config(config_path: str) -> dict:
    config = configparser.ConfigParser()
    read_ok = config.read(config_path)
    if not read_ok:
        raise FileNotFoundError(f"Config file not found/readable: {config_path}")

    monitor = config["monitor"] if config.has_section("monitor") else {}
    obs_cfg = config["obs"] if config.has_section("obs") else {}
    intervals = config["intervals"] if config.has_section("intervals") else {}
    permissions = config["permissions"] if config.has_section("permissions") else {}

    required_containers = _parse_csv(
        monitor.get("required_containers", "obs_compositor, mediamtx")
    )
    if not required_containers:
        required_containers = ["obs_compositor", "mediamtx"]

    cfg = {
        # Monitor + filesystem
        "base_path": monitor.get("base_path", "/home/camerauser/driveway"),
        # Not directly used by the monitor logic, but useful for documentation/ops
        "host_staging_path": monitor.get("host_staging_path", "/var/lib/fakecam"),
        "container_staging_path": monitor.get("container_staging_path", "/fakecam"),
        "error_video_name": monitor.get("error_video_name", "ERROR_ALERT.mp4"),
        "required_containers": required_containers,
        "retention_days": int(monitor.get("retention_days", "7")),
        "cooldown_seconds": int(monitor.get("cooldown_seconds", "10")),
        "log_file": monitor.get("log_file", "/var/log/reolink_monitor.log"),
        "send_to": monitor.get("send_to", "root"),

        # OBS websocket + scene/input names
        "obs_host": obs_cfg.get("host", "127.0.0.1"),
        "obs_port": int(obs_cfg.get("port", "4455")),
        "obs_password": obs_cfg.get("password", ""),
        "obs_media_input": obs_cfg.get("media_input", "Alert_Video"),
        "obs_scene_alert": obs_cfg.get("scene_alert", "Alert"),
        "obs_scene_standby": obs_cfg.get("scene_standby", "Standby"),

        # Timing
        "health_check_seconds": int(intervals.get("health_check_seconds", "300")),
        "main_loop_sleep_seconds": int(intervals.get("main_loop_sleep_seconds", "10")),
        "directory_poll_seconds": int(intervals.get("directory_poll_seconds", "30")),

        # Permission fixups
        "permissions_enabled": _parse_bool(permissions.get("enabled", ""), True),
        "permissions_user_group": permissions.get("user_group", "").strip(),
        "permissions_file_mode": _parse_octal_mode(permissions.get("file_mask", ""), 0o644),
        "permissions_dir_mode": _parse_octal_mode(permissions.get("directory_mask", ""), 0o755),
    }
    return cfg


def setup_logging(log_file: str) -> None:
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def send_alert_email(send_to: str, subject: str, message: str) -> None:
    """Sends a system mail alert."""
    try:
        subprocess.run(
            ["mail", "-s", subject, send_to],
            input=message,
            text=True,
            check=True,
        )
        logging.info(f"Health Alert Sent: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")


def get_current_date_path(base_path: str) -> str:
    """Returns today's path based on YYYY/MM/DD structure."""
    return os.path.join(base_path, datetime.now().strftime("%Y/%m/%d"))


def check_docker_health(required_containers: list[str], send_to: str) -> None:
    """Verifies that the required Docker containers are actually running."""
    for container in required_containers:
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip() != "true":
                raise Exception(f"Container {container} is not running.")
        except Exception as e:
            logging.error(f"DOCKER HEALTH CHECK FAILED: {e}")
            send_alert_email(
                send_to,
                f"CRITICAL: Docker Container {container} Down",
                f"Health check failed for {container} at {datetime.now()}.\nError: {e}",
            )


def ensure_directory_permissions(path: str, mode: int = 0o755) -> None:
    """Ensures directory permissions match exactly `mode` (chmod only if needed)."""
    try:
        st_mode = os.stat(path).st_mode
        current = stat.S_IMODE(st_mode)
        if current != mode:
            os.chmod(path, mode)
            logging.info(
                f"Fixed directory permissions: {path} from {oct(current)} to {oct(mode)}"
            )
    except Exception as e:
        logging.error(f"Failed to verify/fix directory permissions for {path}: {e}")


def apply_permissions(path: str, cfg: dict, is_dir: bool) -> None:
    """Optionally apply chown + chmod based on INI config."""
    if not cfg.get("permissions_enabled", True):
        return

    try:
        uid, gid = _resolve_uid_gid(cfg.get("permissions_user_group", ""))
    except Exception as e:
        logging.error(f"Failed to resolve user_group for permissions fixups: {e}")
        uid, gid = None, None

    try:
        if uid is not None or gid is not None:
            os.chown(path, uid if uid is not None else -1, gid if gid is not None else -1)
    except PermissionError as e:
        logging.error(f"Permission denied chown {path}: {e}")
    except Exception as e:
        logging.error(f"Failed to chown {path}: {e}")

    try:
        desired_mode = cfg["permissions_dir_mode"] if is_dir else cfg["permissions_file_mode"]
        current = stat.S_IMODE(os.stat(path).st_mode)
        if current != desired_mode:
            os.chmod(path, desired_mode)
    except PermissionError as e:
        logging.error(f"Permission denied chmod {path}: {e}")
    except Exception as e:
        logging.error(f"Failed to chmod {path}: {e}")


def validate_config(cfg: dict) -> tuple[list[str], list[str]]:
    """Validate config and return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    base_path = str(cfg.get("base_path", "")).strip()
    if not base_path:
        errors.append("monitor.base_path is empty")
    elif not os.path.isabs(base_path):
        warnings.append(f"monitor.base_path is not absolute: {base_path}")
    elif not os.path.isdir(base_path):
        warnings.append(
            f"monitor.base_path does not exist or is not a directory: {base_path}"
        )

    host_staging = str(cfg.get("host_staging_path", "")).strip()
    if host_staging:
        if not os.path.isabs(host_staging):
            warnings.append(f"monitor.host_staging_path is not absolute: {host_staging}")
        elif not os.path.isdir(host_staging):
            warnings.append(
                f"monitor.host_staging_path does not exist or is not a directory: {host_staging}"
            )

        error_name = str(cfg.get("error_video_name", "")).strip()
        if error_name and os.path.isdir(host_staging):
            candidate = os.path.join(host_staging, error_name)
            if not os.path.exists(candidate):
                warnings.append(
                    f"Error video not found at host_staging_path: {candidate} (used on corrupt/missing clips)"
                )

    required_containers = cfg.get("required_containers")
    if not isinstance(required_containers, list) or not required_containers:
        errors.append("monitor.required_containers is empty")

    obs_port = cfg.get("obs_port")
    if not isinstance(obs_port, int) or not (1 <= obs_port <= 65535):
        errors.append(f"obs.port must be 1-65535, got: {obs_port!r}")

    def _nonneg_int(key: str) -> None:
        value = cfg.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"{key} must be a non-negative integer, got: {value!r}")

    def _positive_int(key: str) -> None:
        value = cfg.get(key)
        if not isinstance(value, int) or value <= 0:
            errors.append(f"{key} must be a positive integer, got: {value!r}")

    _nonneg_int("retention_days")
    _nonneg_int("cooldown_seconds")
    _positive_int("health_check_seconds")
    _positive_int("main_loop_sleep_seconds")
    _positive_int("directory_poll_seconds")

    if cfg.get("permissions_enabled", True):
        file_mode = cfg.get("permissions_file_mode")
        dir_mode = cfg.get("permissions_dir_mode")
        if not isinstance(file_mode, int) or not (0 <= file_mode <= 0o777):
            errors.append(f"permissions.file_mask must be an octal mode (0-0777), got: {file_mode!r}")
        if not isinstance(dir_mode, int) or not (0 <= dir_mode <= 0o777):
            errors.append(
                f"permissions.directory_mask must be an octal mode (0-0777), got: {dir_mode!r}"
            )

        user_group = str(cfg.get("permissions_user_group", "")).strip()
        if user_group:
            try:
                _resolve_uid_gid(user_group)
            except Exception as e:
                errors.append(f"permissions.user_group is invalid ({user_group!r}): {e}")

    return errors, warnings

# --- WATCHDOG HANDLER ---

class ReolinkHandler(FileSystemEventHandler):
    def __init__(self, cfg: dict):
        self.last_trigger_time = 0
        self.cfg = cfg

    def on_closed(self, event):
        """Triggers when a file is fully written/closed by the FTP server."""
        src_path = os.fsdecode(event.src_path)
        if not event.is_directory and src_path.endswith(".mp4"):
            current_time = time.time()
            if current_time - self.last_trigger_time < self.cfg["cooldown_seconds"]:
                return

            logging.info(f"New Motion Alert: {src_path}")
            self.last_trigger_time = current_time

            # Optional permission fixups (chmod/chown) for vsftpd quirks.
            apply_permissions(src_path, self.cfg, is_dir=False)

            self.trigger_obs(src_path)

    def trigger_obs(self, file_path):
        """Commands OBS via WebSocket to switch scenes and play the video."""
        container_error_path = os.path.join(
            self.cfg["container_staging_path"],
            self.cfg["error_video_name"],
        )

        target_path = file_path
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            target_path = container_error_path

        try:
            cl = obs.ReqClient(
                host=self.cfg["obs_host"],
                port=self.cfg["obs_port"],
                password=self.cfg.get("obs_password", ""),
            )

            media_input = self.cfg["obs_media_input"]
            scene_alert = self.cfg["obs_scene_alert"]
            scene_standby = self.cfg["obs_scene_standby"]

            # Clear and reset the Media Input
            cl.set_input_settings(media_input, {"local_file": ""}, overlay=True)
            time.sleep(0.1)
            cl.set_input_settings(media_input, {"local_file": target_path}, overlay=True)

            # Switch to the Alert Scene
            cl.set_current_program_scene(scene_alert)

            # Wait for video to end or timeout after 60s
            time.sleep(2)
            start_timeout = time.time()
            while True:
                status = cl.get_media_input_status(media_input)
                media_state = getattr(status, "media_state", None)
                if media_state in ["OBS_MEDIA_STATE_ENDED", "OBS_MEDIA_STATE_STOPPED"]:
                    break
                if time.time() - start_timeout > 60:
                    break
                time.sleep(0.5)

            # Return to Standby
            cl.set_current_program_scene(scene_standby)
            time.sleep(0.5)

            # Reset the input to the error file to 're-arm'
            cl.set_input_settings(media_input, {"local_file": container_error_path}, overlay=True)
            cl.trigger_media_input_action(
                media_input, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
            )
            logging.info("OBS: Reset and re-armed.")

        except Exception as e:
            logging.error(f"OBS Connection Error: {e}")
            send_alert_email(self.cfg["send_to"], "CRITICAL: OBS Down", f"Connection failed: {e}")

# --- MAINTENANCE ---
def cleanup_old_files():
    """Removes files older than RETENTION_DAYS to prevent disk bloat."""
    now = time.time()
    one_day_seconds = 86400
    try:
        for root, dirs, files in os.walk(_CFG["base_path"], topdown=False):
            for file in files:
                file_path = os.path.join(root, file)
                if os.stat(file_path).st_mtime < now - (
                    _CFG["retention_days"] * one_day_seconds
                ):
                    os.remove(file_path)
                    logging.info(f"Purged old file: {file}")
            
            # Only remove empty directories if they haven't been touched in 24 hours
            # This prevents the script from deleting today's folder before a file lands.
            if not os.listdir(root) and root != _CFG["base_path"]:
                folder_age = now - os.path.getmtime(root)
                if folder_age > one_day_seconds:
                    os.rmdir(root)
                    logging.info(f"Purged empty directory: {root}")
    except Exception as e:
        logging.error(f"Cleanup Error: {e}")

def start_monitoring():
    current_path = get_current_date_path(_CFG["base_path"])
    
    cleanup_old_files()

    # Log ONCE that we are entering wait mode
    if not os.path.exists(current_path):
        logging.info(f"Watching for camera to create today's directory: {current_path}")
    
    # Stay silent in the loop
    while not os.path.exists(current_path):
        time.sleep(_CFG["directory_poll_seconds"])
        # Handle day rollover while waiting
        if get_current_date_path(_CFG["base_path"]) != current_path:
            return 

    if _CFG.get("permissions_enabled", True):
        ensure_directory_permissions(current_path, _CFG["permissions_dir_mode"])
        apply_permissions(current_path, _CFG, is_dir=True)

    event_handler = ReolinkHandler(_CFG)
    observer = Observer()
    
    try:
        observer.schedule(event_handler, current_path, recursive=False)
        # Log ONCE when the folder is finally found
        logging.info(f"Directory detected. Monitoring started on: {current_path}")
        observer.start()
    except Exception as e:
        logging.error(f"Failed to start observer: {e}")
        return

    try:
        current_day = datetime.now().day
        last_health_check = time.time()

        while True:
            time.sleep(_CFG["main_loop_sleep_seconds"])

            # Health check every 5 minutes
            if time.time() - last_health_check > _CFG["health_check_seconds"]:
                check_docker_health(_CFG["required_containers"], _CFG["send_to"])
                last_health_check = time.time()

            # Rotate monitor when the day changes
            if datetime.now().day != current_day:
                observer.stop()
                observer.join()
                return
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        exit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reolink directory monitor + OBS alert trigger"
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help="Path to INI config file"
    )
    parser.add_argument(
        "--test-config",
        action="store_true",
        help="Load + validate config then exit (does not start monitoring)",
    )
    args = parser.parse_args()

    try:
        _CFG = load_config(args.config)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    if args.test_config:
        errors, warnings = validate_config(_CFG)
        print(f"Config: {args.config}")
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"- {w}")
        if errors:
            print("Errors:")
            for err in errors:
                print(f"- {err}")
            sys.exit(2)
        print("OK")
        sys.exit(0)

    setup_logging(_CFG["log_file"])

    while True:
        start_monitoring()