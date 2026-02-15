# FTPS Setup

This document describes how to set up the Reolink camera to save to an FTPS server. The setup of an FTPS server is outside the scope of this document. You should ensure it is up and running and working before attempting to configure your cellular camera to write to it. 

For those unfamiliar, FTPS != SFTP. In my case, I got this all working with vsftpd on Ubuntu LTS 24, and you MUST open PASV ports to your server, not just port 990 (or whatever you port forwarded). The Reolink camera will not work without them. I limited mine to 100, and it has never been an issue. 

## 1. Create a user for the camera
In your FTPS server, dedicate a user for camera use and set up a directory to receive the MP4s (and JPGs) from the camera.

## 2. Configure your camera for FTPS
Go to your camera settings / FTP / FTP Settings:
 - Server Address: [Your server address]
 - Server Port: 990 (typically)
 - Anonymous FTP: OFF
 - Username/Password: As set up in step #1
 - Disable Plain Unencrypted FTP: ON
 - Remote Directory: Set to the relative path from the FTPS destination (e.g., /driveway).
 - Subfolder Creation Rule: Monitor expects: YYYY-MM-DD

   Note: Even though the camera UI calls this rule `YYYY-MM-DD`, Reolink creates a nested folder structure on the server that looks like `YYYY/MM/DD/` (this is what the monitor script expects).

   This results in:
   ```
   {ftpsroot}/{remote directory}/YYYY
                                  /MM
                                      /DD
   ```
   Example: `/home/reolinkftp/2026/01/10/` <MP4s-JPGs from that day>

 - Upload: Video & Image or just Video

### Video
 - Resolution: Clear (Fluent will work if you're bandwidth-constrained, but Clear is recommended).
 - FTP Postpone: Sets how long to record after motion. I chose 15 seconds to get the video up to Blue Iris as quickly as possible, but this is up to you.
 - File Overwrite: Off

### Image (if you chose Video & Image)
 - Resolution: Up to you
 - File Overwrite: Off

Use the TEST function to ensure your settings are correct. Reolink support was essentially useless when I called them about setting up FTPS. I got it working through a lot of trial and error.

Once this is done, you should have MP4s showing up in your FTPS landing directory