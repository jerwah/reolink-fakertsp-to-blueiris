# Reolink Cellular Cam to Blue Iris

This repository provides a set of tools and instructions about how I got my Reolink Go Ranger Cellular Camera footage into Blue Iris for alerts, AI review, storage, and retrieval. Since the Reolink cellular camera does not support a typical "always-on" stream even with an unlimited-use SIM, this workaround was created because I REALLY like being able to review the footage in Blue Iris. There IS a delay of up to a minute or so, but in my particular use case, that is acceptable. If you need true real-time streaming, get a different camera. You'll always have the Reolink delay to recognize the motion, trigger, send the MP4 via FTPS, and THEN we need to detect it and sweep it into the RTSP stream for Blue Iris to be happy.

The overall behavior in Blue Iris is that the camera shows a static image "Waiting for Reolink Camera Events." Once a Reolink file is detected, it is played into the stream, replacing the "Waiting for..." image, which is enough to trip Blue Iris alerts. You can then set up the processing in Blue Iris to your heart's content. After the video is played, it returns to the static "Waiting for Reolink Camera Events" until the next one. I strongly recommend setting Blue Iris to put a date/time overlay on the page so you can easily tell if the RTSP stream is active or not.

## Table of Contents

- [Reolink Cellular Cam to Blue Iris](#reolink-cellular-cam-to-blue-iris)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [How it Works](#how-it-works)
  - [Features](#features)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Usage](#usage)
    - [First Run Checklist](#first-run-checklist)
  - [Configuration](#configuration)
  - [Troubleshooting](#troubleshooting)
  - [Contributing](#contributing)
  - [License](#license)

## Overview

This project is a collection of scripts and configuration files that work together to create a fake RTSP camera system from a Reolink Cellular Camera. This allows you to use the camera within Blue Iris, which normally requires a constant RTSP stream.

## How it Works

The system consists of three main components:

1.  **FTPS Server:** This receives the MP4s from the Reolink Camera. I already had one set up; you need this to start the process (reminder: FTPS != SFTP).
2.  **OBS/mediamtx Servers:** Docker containers running a stripped-down OBS/mediamtx setup. These create the "fake" camera RTSP stream to feed to Blue Iris constantly.
3.  **Monitor Script:** A Python script that watches for the new video clips from the camera. When a new clip is detected, it calls OBS to inject the new clip into the stream. Blue Iris then triggers alerts/AI scanning/etc. as normal. When the clip is over, it returns to the static "Waiting" screen.

## Features

*   **RTSP stream:** The core of this project is a system that creates a predictable RTSP stream from the Reolink camera's FTPS uploads.
*   **Blue Iris Integration:** The generated RTSP stream can be easily added to Blue Iris, and all Blue Iris features are now available for processing them.
*   **Monitoring:** A monitoring script is included to ensure the system is running smoothly.
*   **OBS Integration:** An OBS profile and desktop file are included to help with scene management.

## Prerequisites
*   A Reolink Cellular Camera that supports FTPS uploads (Go Ranger tested).
*   A server to run the FTPS Server, Docker containers, and scripts.
*   Blue Iris installed and configured.
*   Docker and Docker Compose installed.

## Disclaimer

This project is not affiliated with Reolink or Blue Iris. “Reolink” and “Blue Iris” are trademarks of their respective owners.

This repo uses third-party Docker images (e.g., LinuxServer Webtop and MediaMTX). Those components are licensed by their upstream authors under their respective licenses; this repository’s license applies only to the content in this repo.

## Installation

1.  **Configure the camera FTPS server:**
    *   Follow the instructions in `Reolink/FTPSSetup.md` to set up the camera to send mp4s to the FTPS server.

2.  **Configure the `docker-compose.yml` file:**
    *   Open the `docker-compose.yml` file and review the settings. You may need to change the port mappings if they conflict with other services on your server.

3.  **Check permissions**
    * If the user running the OBS container doesn't have read access to the staged MP4s, playback will fail.
    * The monitoring service must be able to read the camera drop directory and write logs to `/var/log`.

4.  **Configure the monitor via INI (recommended):**
        * Copy the sample config and then edit the INI values:
            - `cp monitor/monitor.ini.sample monitor/monitor.ini`
        * (Optional) Validate the INI without starting the monitor:
            - `python3 monitor/monitor.py --test-config --config monitor/monitor.ini`
        * The main settings you may need to review:
            - `base_path` (where FTPS drops MP4s, expects `YYYY/MM/DD/` folders)
            - `host_staging_path` and `container_staging_path` (where standby/error videos live, host vs container)
            - `error_video_name` (must exist in the staging directory)
            - `log_file` and `send_to` (logging + alert recipient)
            - `obs.host`, `obs.port`, `obs.password` (OBS WebSocket connection)
            - `permissions.enabled`, `permissions.user_group`, `permissions.file_mask`, `permissions.directory_mask` (optional chmod/chown fixups)

5.  **Stage Standby and Error videos**
    * You can use the provided `Standby_With_Audio.mp4` and `ERROR_ALERT.mp4` or create your own.
    * Copy them to the folder specified by `host_staging_path` in your `monitor.ini` (default: `/var/lib/fakecam`).

6.  **Start the Docker containers:**
    ```bash
    docker-compose up -d
    ```

7.  **Set up OBS:**
    *   Follow the instructions in `obs/README.md` to set up OBS.

8.  **(Optional) Set up OBS to auto-launch**
    * Copy `obs/obs.desktop` into `./config/.config/autostart/` (this path is inside the Webtop container because `./config` is mounted to `/config`).

9.  **Set up the monitoring service (host-run, recommended)**
    This monitor is designed to run on the Docker host (not inside a container).

    ```bash
    sudo mkdir -p /opt/reolink_monitor
    sudo cp monitor/monitor.py monitor/reolink_monitor.service monitor/requirements.txt /opt/reolink_monitor/
    sudo cp monitor/monitor.ini.sample /opt/reolink_monitor/monitor.ini
    cd /opt/reolink_monitor

    # Create venv + install dependencies
    python3 -m venv .venv
    . .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    deactivate

    # Install + start systemd unit
    sudo cp reolink_monitor.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable reolink_monitor
    sudo systemctl start reolink_monitor
    ```

    Notes:
    * The service file uses `/opt/reolink_monitor/.venv/bin/python3` by default.
    * The service launches the script with `--config /opt/reolink_monitor/monitor.ini`.
    * The monitor connects to OBS WebSocket at `127.0.0.1:4455` by default, so it must run on the same host where the OBS container is running (this repo uses `network_mode: host`).


## Usage

Once the system is set up, you can add the RTSP stream to Blue Iris. The RTSP URL will be:
`rtsp://<server_ip>:8554/live/<streamkey>`
i.e. rtsp://<server_ip>:8554/live/reolink 
   + Make - Generic/ONVIF    - Media/video/RTSP prot: 8554
   + Model - RTSP H.264/H.265....  - Discovery/ONVIF port: 8999
   + Main - (default)
   + Sub - (none)
   + Audio: 64kbps G.711 u-law
   Check Send RTSP Keep-alives
   Check Use RTSP/stream timecode

If all goes well you should be seeing your "Waiting" video. 
Recommend: 
 - configuring BI to show date/timestamp so you know the stream is alive
 - setting up watchdog to detect loss of video signal and reset camera/window after 2 timeouts.
   ( if mediamtx / obs goes down BI wasn't great about reconnecting until I changed this)

## First Run Checklist

Use this checklist if you're not seeing motion clips make it into Blue Iris yet.

1. Confirm FTPS uploads are landing where the monitor watches
    - Verify the camera is successfully uploading MP4s to your FTPS server.
    - Confirm the files land under the `base_path` configured in your `monitor.ini` using the `YYYY/MM/DD/` folder structure.
    - Check today's directory exists and contains MP4s: `<base_path>/YYYY/MM/DD/`.
    - Permissions check (common gotcha): the monitoring service user must be able to read the uploaded MP4s and traverse the directories.

2. Confirm staging permissions and standby/error videos exist
    - Ensure the `host_staging_path` exists on the host (default: `/var/lib/fakecam`).
    - Verify `Standby_With_Audio.mp4` and `ERROR_ALERT.mp4` exist there and are readable by the OBS container user (`PUID`/`PGID` in `docker-compose.yml`).
    - If vsftpd writes files with restrictive permissions, enable permission fixups in `monitor.ini` (`permissions.enabled=true`) and set `permissions.file_mask` / `permissions.user_group` as needed.

3. Confirm OBS is streaming to MediaMTX
    - In OBS, configure Stream output to `rtmp://127.0.0.1:1935/live` and set a Stream Key.
    - Start streaming (or configure auto-start).
    - Check MediaMTX logs: `docker-compose logs mediamtx`.

4. Confirm Blue Iris RTSP URL matches your stream key
    - Use `rtsp://<server_ip>:8554/live/<streamkey>` (stream key must match OBS exactly).
    - Enable RTSP keep-alives/timecode in Blue Iris as described above.

5. Confirm the monitor service is running and dependencies are installed
    - Set up the venv and install `monitor/requirements.txt` per the Installation steps.
    - Check logs: `journalctl -u reolink_monitor`.
    - Note: If alert emails fail, monitoring can still work; it only affects notifications.


## Configuration

The monitor is configured via an INI file.

* Start with `monitor/monitor.ini.sample` and copy it to `monitor/monitor.ini` (or pass `--config /path/to/monitor.ini`).
* Defaults in the sample INI match the defaults in the script.
* Use `--test-config` to validate the INI and exit without starting monitoring.

## Troubleshooting

*   **RTSP stream not working:**
    *   Check the logs for MediaMTX: `docker-compose logs mediamtx`.
    *   In OBS, verify you are streaming to the correct RTMP server and that you set a stream key.
*   **Monitor script not running:**
    *   Check the logs for the monitor script: `journalctl -u reolink_monitor`.
    *   Make sure the camera clips are landing under your configured `base_path` using a `YYYY/MM/DD` folder tree.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
