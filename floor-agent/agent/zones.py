"""Table zones: a shape per table on the camera picture, linked to a WaitLess table and its waiter."""

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Zone:
    label: str  # the WaitLess table name, e.g. "T02"
    polygon: list[tuple[int, int]]
    seats: int = 4
    waiter: str | None = None  # resolved by the WaitLess server in production; read from the file in tests

    def _poly(self) -> np.ndarray:
        return np.array(self.polygon, np.int32)

    def contains(self, point: tuple[float, float], margin: float = 0) -> bool:
        """Inside the shape (margin > 0 also accepts points that close outside it, in pixels)."""
        return cv2.pointPolygonTest(self._poly(), (float(point[0]), float(point[1])), True) >= -margin

    @property
    def center(self) -> tuple[int, int]:
        x, y = self._poly().mean(axis=0)
        return int(x), int(y)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        x, y, w, h = cv2.boundingRect(self._poly())
        return x, y, x + w, y + h


def load_zones(path: str | Path) -> tuple[list[Zone], tuple[int, int]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    size = (data["frame"]["width"], data["frame"]["height"])
    return [
        Zone(z["label"], [tuple(p) for p in z["polygon"]], z.get("seats", 4), z.get("waiter"))
        for z in data["zones"]
    ], size


def scale_zones(zones: list[Zone], src: tuple[int, int], dst: tuple[int, int]) -> list[Zone]:
    """The sub-stream is a smaller picture than the one the shapes were drawn on: scale them to fit."""
    if src == dst:
        return zones
    fx, fy = dst[0] / src[0], dst[1] / src[1]
    return [Zone(z.label, [(int(x * fx), int(y * fy)) for x, y in z.polygon], z.seats, z.waiter) for z in zones]


def save_zones(path: str | Path, zones: list[Zone], frame_size: tuple[int, int]) -> None:
    payload = {
        "frame": {"width": frame_size[0], "height": frame_size[1]},
        "zones": [
            {"label": z.label, "polygon": [list(p) for p in z.polygon], "seats": z.seats, "waiter": z.waiter}
            for z in zones
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
