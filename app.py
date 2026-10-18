
import os
import threading
from flask import Flask, Response, request, abort, stream_with_context

app = Flask(__name__)

CAMERA_TOKEN = os.environ.get("CAMERA_TOKEN", "")
MAX_FRAME_SIZE = 500_000

latest_frame = None
frame_number = 0
frame_condition = threading.Condition()


@app.get("/")
def home():
    return """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESP32-CAM Cloud Stream</title>
  <style>
    body {
      background: #151923;
      color: white;
      font-family: Arial, sans-serif;
      text-align: center;
      padding: 20px;
    }
    img {
      width: 100%;
      max-width: 800px;
      height: auto;
      border-radius: 12px;
    }
    .status { color: #63d8ff; }
  </style>
</head>
<body>
  <h2>ESP32-CAM Cloud Stream</h2>
  <p class="status">VGA 640 × 480 · Latest-frame stream</p>
  <img src="/stream" alt="Waiting for camera frames">
  <p>Keep the camera connected to its hotspot.</p>
</body>
</html>
"""


@app.get("/health")
def health():
    with frame_condition:
        return {
            "status": "ok",
            "has_frame": latest_frame is not None,
            "frame_number": frame_number
        }


@app.post("/upload")
def upload():
    global latest_frame, frame_number

    if not CAMERA_TOKEN:
        abort(503, "CAMERA_TOKEN is not configured")

    if request.headers.get("X-Camera-Token") != CAMERA_TOKEN:
        abort(401, "Invalid camera token")

    if request.mimetype != "image/jpeg":
        abort(415, "Expected image/jpeg")

    data = request.get_data(cache=False)

    if not data or len(data) > MAX_FRAME_SIZE:
        abort(413, "Invalid frame size")

    with frame_condition:
        latest_frame = data
        frame_number += 1
        frame_condition.notify_all()

        current_number = frame_number

    return {"received": True, "frame": current_number}, 200


def generate_stream():
    last_number = 0

    while True:
        with frame_condition:
            changed = frame_condition.wait_for(
                lambda: frame_number != last_number,
                timeout=15
            )

            if not changed:
                # Let the browser connection remain open while
                # waiting for the next camera frame.
                continue

            data = latest_frame
            last_number = frame_number

        if data is None:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(data)).encode() +
            b"\r\n"
            b"Cache-Control: no-store\r\n\r\n"
            + data + b"\r\n"
        )


@app.get("/stream")
def stream():
    response = Response(
        stream_with_context(generate_stream()),
        content_type="multipart/x-mixed-replace; boundary=frame"
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["X-Accel-Buffering"] = "no"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
