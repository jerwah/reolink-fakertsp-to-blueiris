import cv2
import numpy as np

# Video settings
width = 1920
height = 1080
fps = 1
duration = 5  # seconds
output_file = "waiting.mp4"

# Colors
blue = (255, 0, 0)
white = (255, 255, 255)

# Text settings
text = "Waiting for stream..."
font = cv2.FONT_HERSHEY_SIMPLEX
font_scale = 2
thickness = 3

# Create video writer
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
video_writer = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

# Get text size
text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
text_x = (width - text_size[0]) // 2
text_y = (height + text_size[1]) // 2

# Generate frames
for _ in range(fps * duration):
    # Create a blue frame
    frame = np.full((height, width, 3), blue, np.uint8)

    # Add text to the frame
    cv2.putText(frame, text, (text_x, text_y), font, font_scale, white, thickness)

    # Write frame to video
    video_writer.write(frame)

# Release video writer
video_writer.release()

print(f"Video '{output_file}' created successfully.")
