import os
import time
import threading
from flask import Flask, Response, request, abort

app = Flask(__name__)

CAMERA_TOKEN = os.environ.get("CAMERA_TOKEN", "")
latest_frame = None
frame_condition = threading.Condition()

@app.get("/")
def home():
    return """
    <!doctype html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>ESP32 Cloud Camera</title>
      <style>
        body { background:#151923; color:white; text-align:center;
               font-family:Arial; padding:20px; }
        img { width:100%; max-width:800px; border-radius:12px; }
      </style>
    </head>
    <body>
      <h2>ESP32-CAM Cloud Stream</h2>
      <p>Live camera feed</p>
      <img src="/stream" alt="Waiting for camera">
    </body>
    </html>
    """

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/upload")
def upload():
    global latest_frame

    if not CAMERA_TOKEN:
        abort(503, "Server camera token is not configured")

    if request.headers.get("X-Camera-Token") != CAMERA_TOKEN:
        abort(401)

    if not request.mimetype or not request.mimetype.startswith("image/"):
        abort(415, "Expected an image")

    data = request.get_data(cache=False)

    if not data or len(data) > 500_000:
        abort(413, "Invalid image size")

    with frame_condition:
        latest_frame = data
        frame_condition.notify_all()

    return {"received": True, "bytes": len(data)}

def generate_stream():
    last_frame = None

    while True:
        with frame_condition:
            frame_condition.wait_for(
                lambda: latest_frame is not None
                        and latest_frame is not last_frame,
                timeout=10
            )
            frame = latest_frame

        if frame is None:
            continue

        last_frame = frame
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame)).encode() +
            b"\r\n\r\n" + frame + b"\r\n"
        )

@app.get("/stream")
def stream():
    return Response(
        generate_stream(),
        content_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"}
    )
