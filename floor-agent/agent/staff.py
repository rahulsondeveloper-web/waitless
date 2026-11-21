"""Staff or guest? Waiters wear a dark uniform and stand; guests sit down in everyday clothes."""

import json
import statistics
from pathlib import Path

import cv2
import numpy as np

DARK_VALUE = 70  # brightness (0-255) below which a pixel counts as "uniform black"
DARK_SHARE = 0.55  # share of the torso that must be dark to count as wearing the uniform


def torso_dark_share(frame: np.ndarray, box: tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w < 8 or h < 16:
        return 0.0
    crop = frame[y1 + int(h * 0.18) : y1 + int(h * 0.58), x1 + int(w * 0.25) : x2 - int(w * 0.25)]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return float((hsv[:, :, 2] < DARK_VALUE).mean())


class Perspective:
    """Learns how tall a standing person looks at each spot of this camera, then spots people who are sitting.

    On a camera that looks down at an angle, a standing person's box height is roughly proportional to how low
    their feet are in the picture. The constant is learned from people who are walking, so no set-up is needed.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.samples: list[float] = []
        if self.path and self.path.exists():  # the camera does not move: start with what we learned last time
            self.samples = [json.loads(self.path.read_text())["standing_ratio"]] * 40

    def save(self) -> None:
        k = self.standing_ratio
        if self.path and k is not None and len(self.samples) >= 12:
            self.path.write_text(json.dumps({"standing_ratio": round(k, 4)}))

    def learn(self, box: tuple[int, int, int, int]) -> None:
        h, foot = box[3] - box[1], box[3]
        if foot > 120 and h > 40 and len(self.samples) < 400:
            self.samples.append(h / foot)

    @property
    def standing_ratio(self) -> float | None:
        return statistics.median(self.samples) if len(self.samples) >= 8 else None

    def is_seated(self, box: tuple[int, int, int, int]) -> bool:
        w, h, foot = box[2] - box[0], box[3] - box[1], max(box[3], 1)
        k = self.standing_ratio
        if k is None:  # not learned yet: fall back to the box shape
            return h / max(w, 1) < 1.9
        return (h / foot) / k < 0.72
