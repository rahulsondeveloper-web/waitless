"""Reads a camera stream in the background and always hands over the newest frame.

Processing a frame takes longer than the camera takes to make one. Reading on a separate thread and throwing away
the old frames keeps the agent looking at "now" instead of falling further and further behind. If the stream drops
(camera restarted, Wi-Fi blip) it reconnects by itself.
"""

import os
import threading
import time

# TCP is slower to start but does not drop packets on a busy network. Must be set before OpenCV opens a stream.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import numpy as np  # noqa: E402


class StreamReader:
    def __init__(self, url: str) -> None:
        self.url = url
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.size: tuple[int, int] | None = None
        self.connected = False
        self.reconnects = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self.connected = False
                time.sleep(2)
                continue
            self.connected = True
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                with self._lock:
                    self._frame, self._seq = frame, self._seq + 1
                    self.size = (frame.shape[1], frame.shape[0])
            cap.release()
            self.connected = False
            self.reconnects += 1
            time.sleep(1)

    def read(self) -> tuple[int, np.ndarray | None]:
        with self._lock:
            return self._seq, (None if self._frame is None else self._frame.copy())

    def wait_for_first(self, timeout: float = 20.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.read()[1] is not None:
                return True
            time.sleep(0.1)
        return False

    def close(self) -> None:
        self._stop.set()
