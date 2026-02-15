import time
import os
import logging
import subprocess
from datetime import datetime
import obsws_python as obs
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURATION ---
# The directory where your cameras/FTPS server drops new files
BASE_PATH = "/home/camerauser/driveway"

# The directory shared with the OBS container (fakecam)
# HOST_PATH is where the script finds it, CONTAINER_PATH is how OBS sees it
HOST_STAGING_PATH = "/var/lib/fakecam"
CONTAINER_STAGING_PATH = "/fakecam"

# Path to an error video to play if a file is missing/corrupt
ERROR_VIDEO_NAME = "ERROR_ALERT.mp4"

# List of Docker containers that the script will health-check
REQUIRED_CONTAINERS = ["obs_compositor", "mediamtx"]

# Maintenance Settings
# Number of days to keep old video files before deletion
RETENTION_DAYS = 7
# Minimum seconds between triggers to prevent rapid re-triggering on multiple files
COOLDOWN_SECONDS = 10
# Log file location and alert recipient
LOG_FILE = "/var/log/reolink_monitor.log"
# System user or email for alerts
SEND_TO = "root"

# Setup Logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- HELPER FUNCTIONS ---

def send_alert_email(subject, message):
    """Sends a system mail alert."""
    try:
        cmd = f'echo "{message}" | mail -s "{subject}" {SEND_TO}'
        subprocess.run(cmd, shell=True, check=True)
        logging.info(f"Health Alert Sent: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def get_current_date_path():
    """Returns today's path based on YYYY/MM/DD structure."""
    return os.path.join(BASE_PATH, datetime.now().strftime('%Y/%m/%d'))

def check_docker_health():
    """Verifies that the required Docker containers are actually running."""
    for container in REQUIRED_CONTAINERS:
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True, text=True, check=True
            )
            if result.stdout.strip() != "true":
                raise Exception(f"Container {container} is not running.")
        except Exception as e:
            logging.error(f"DOCKER HEALTH CHECK FAILED: {e}")
            send_alert_email(
                f"CRITICAL: Docker Container {container} Down",
                f"Health check failed for {container} at {datetime.now()}.\nError: {e}"
            )

# --- WATCHDOG HANDLER ---

class ReolinkHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_trigger_time = 0

    def on_closed(self, event):
        """Triggers when a file is fully written/closed by the FTP server."""
        if not event.is_directory and event.src_path.endswith(".mp4"):
            current_time = time.time()
            if current_time - self.last_trigger_time < COOLDOWN_SECONDS:
                return

            logging.info(f"New Motion Alert: {event.src_path}")
            self.last_trigger_time = current_time

            # Ensure the file is readable by the Docker container
            try:
                os.chmod(event.src_path, 0o644)
            except Exception as e:
                logging.error(f"Permissions Error: {e}")

            self.trigger_obs(event.src_path)

    def trigger_obs(self, file_path):
        """Commands OBS via WebSocket to switch scenes and play the video."""
        # Map the local host path to the path inside the container
        file_name = os.path.basename(file_path)
        
        # Check if file exists and is not empty
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            target_path = os.path.join(CONTAINER_STAGING_PATH, ERROR_VIDEO_NAME)
        else:
            # We assume OBS is mounting the daily folder or the specific file
            # For simplicity in this generic version, we use the raw source path
            target_path = file_path 

        try:
            cl = obs.ReqClient(host='127.0.0.1', port=4455)
            
            # Clear and reset the Media Input
            cl.set_input_settings("Alert_Video", {"local_file": ""}, overlay=True)
            time.sleep(0.1)
            cl.set_input_settings("Alert_Video", {"local_file": target_path}, overlay=True)
            
            # Switch to the Alert Scene
            cl.set_current_program_scene("Alert")

            # Wait for video to end or timeout after 60s
            time.sleep(2)
            start_timeout = time.time()
            while True:
                status = cl.get_media_input_status("Alert_Video")
                if status.media_state in ['OBS_MEDIA_STATE_ENDED', 'OBS_MEDIA_STATE_STOPPED']:
                    break
                if time.time() - start_timeout > 60:
                    break
                time.sleep(0.5)

            # Return to Standby
            cl.set_current_program_scene("Standby")
            time.sleep(0.5)
            
            # Reset the input to the error file to 're-arm'
            reset_path = os.path.join(CONTAINER_STAGING_PATH, ERROR_VIDEO_NAME)
            cl.set_input_settings("Alert_Video", {"local_file": reset_path}, overlay=True)
            cl.trigger_media_input_action("Alert_Video", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP")
            logging.info("OBS: Reset and re-armed.")

        except Exception as e:
            logging.error(f"OBS Connection Error: {e}")
            send_alert_email("CRITICAL: OBS Down", f"Connection failed: {e}")

# --- MAINTENANCE ---

def cleanup_old_files():
    """Removes files older than RETENTION_DAYS to prevent disk bloat."""
    now = time.time()
    try:
        for root, dirs, files in os.walk(BASE_PATH, topdown=False):
            for file in files:
                file_path = os.path.join(root, file)
                if os.stat(file_path).st_mtime < now - (RETENTION_DAYS * 86400):
                    os.remove(file_path)
                    logging.info(f"Purged old file: {file}")
            
            # Remove empty directories
            if not os.listdir(root) and root != BASE_PATH:
                os.rmdir(root)
    except Exception as e:
        logging.error(f"Cleanup Error: {e}")

def start_monitoring():
    current_path = get_current_date_path()
    os.makedirs(current_path, exist_ok=True)
    cleanup_old_files()

    event_handler = ReolinkHandler()
    observer = Observer()
    observer.schedule(event_handler, current_path, recursive=False)

    logging.info(f"Monitor started on: {current_path}")
    observer.start()

    try:
        current_day = datetime.now().day
        last_health_check = time.time()

        while True:
            time.sleep(10)

            # Health check every 5 minutes
            if time.time() - last_health_check > 300:
                check_docker_health()
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
    while True:
        start_monitoring()