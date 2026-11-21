"""Person (and table) detection with YOLOX through OpenCV's DNN module (CPU only, Apache-2.0 model)."""

from dataclasses import dataclass

import cv2
import numpy as np

PERSON, DINING_TABLE = 0, 60
_STRIDES = (8, 16, 32)


@dataclass(frozen=True)
class Detection:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in frame pixels
    score: float
    cls: int

    @property
    def foot(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, float(self.box[3]))

    @property
    def center(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)


class Detector:
    def __init__(
        self, model_path: str, size: int = 640, person_conf: float = 0.30, nms: float = 0.45, tiles: int = 1
    ) -> None:
        self.net = cv2.dnn.readNetFromONNX(model_path)
        self.size, self.person_conf, self.nms, self.tiles = size, person_conf, nms, tiles
        grids, strides = [], []
        for s in _STRIDES:
            n = size // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grids, self.strides = np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)

    def detect(self, frame: np.ndarray, classes: tuple[int, ...] = (PERSON,), conf: float | None = None) -> list[Detection]:
        """Look at the whole picture, or (tiles > 1) at overlapping pieces of it: small, far-away things get more
        pixels that way. Slower in proportion to the number of pieces, so use it for big pictures only."""
        if self.tiles <= 1:
            return self._detect_one(frame, classes, conf)
        h, w = frame.shape[:2]
        overlap, n = 0.2, self.tiles
        tw, th = int(w / (n - (n - 1) * overlap)), int(h / (n - (n - 1) * overlap))
        boxes: list[Detection] = []
        for ty in range(n):
            for tx in range(n):
                x0, y0 = int(tx * tw * (1 - overlap)), int(ty * th * (1 - overlap))
                for d in self._detect_one(frame[y0 : y0 + th, x0 : x0 + tw], classes, conf):
                    b = d.box
                    boxes.append(Detection((b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0), d.score, d.cls))
        out: list[Detection] = []
        for cls in classes:  # the same person in two overlapping pieces should count once
            mine = [d for d in boxes if d.cls == cls]
            if not mine:
                continue
            xywh = [[d.box[0], d.box[1], d.box[2] - d.box[0], d.box[3] - d.box[1]] for d in mine]
            keep = cv2.dnn.NMSBoxes(xywh, [d.score for d in mine], 0.0, self.nms)
            out.extend(mine[int(i)] for i in np.array(keep).flatten())
        return out

    def _detect_one(self, frame: np.ndarray, classes: tuple[int, ...], conf: float | None) -> list[Detection]:
        h, w = frame.shape[:2]
        ratio = min(self.size / h, self.size / w)
        nh, nw = int(h * ratio), int(w * ratio)
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        canvas[:nh, :nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = canvas.transpose(2, 0, 1)[None].astype(np.float32)
        self.net.setInput(blob)
        out = self.net.forward()[0]  # (anchors, 85)
        xy = (out[:, :2] + self.grids) * self.strides
        wh = np.exp(out[:, 2:4]) * self.strides
        found: list[Detection] = []
        for cls in classes:
            score = out[:, 4] * out[:, 5 + cls]
            keep = score >= (conf if conf is not None else self.person_conf)
            if not keep.any():
                continue
            c, s, d = xy[keep], score[keep], wh[keep]
            boxes = np.concatenate([c - d / 2, d], axis=1) / ratio  # x, y, w, h in frame pixels
            idx = cv2.dnn.NMSBoxes(boxes.tolist(), s.tolist(), 0.0, self.nms)
            for i in np.array(idx).flatten():
                x, y, bw, bh = boxes[i]
                box = (max(0, int(x)), max(0, int(y)), min(w - 1, int(x + bw)), min(h - 1, int(y + bh)))
                found.append(Detection(box, float(s[i]), cls))
        return found
