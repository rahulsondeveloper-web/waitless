"""One-time setup: find the tables on the camera picture and link each to a WaitLess table.

    python -m agent.setup_zones --source ../design/cctv.mp4 --links config/test_links.json

The agent looks at the first seconds of the feed, boxes every dining table it sees in most frames, then names each
shape after the nearest point in the links file (the owner does this by clicking in the real app).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from agent.detector import DINING_TABLE, Detector
from agent.tracker import _iou
from agent.zones import Zone, save_zones


def suggest(source: str, model: str, seconds: float = 5.0, samples: int = 12, tiles: int = 1) -> tuple[list[tuple[int, int, int, int]], tuple[int, int]]:
    cap = cv2.VideoCapture(source)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    det = Detector(model, tiles=tiles)
    seen: list[list[tuple[int, int, int, int]]] = []
    size = (int(cap.get(3)), int(cap.get(4)))
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(seconds * fps * i / samples))
        ok, frame = cap.read()
        if not ok:
            break
        seen.append([d.box for d in det.detect(frame, (DINING_TABLE,), conf=0.25)])
    # A real table shows up in most of the sampled frames at (nearly) the same place.
    groups: list[list[tuple[int, int, int, int]]] = []
    for boxes in seen:
        for b in boxes:
            for g in groups:
                if _iou(np.mean(g, axis=0).astype(int).tolist(), b) > 0.5:
                    g.append(b)
                    break
            else:
                groups.append([b])
    stable = [tuple(int(v) for v in np.mean(g, axis=0)) for g in groups if len(g) >= max(2, len(seen) // 2)]
    return stable, size


def drop_nested(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """A table cut in two by a tile edge shows up as a small box inside (or beside) the full one: keep the biggest."""

    def area(b: tuple[int, int, int, int]) -> int:
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])

    def overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
        return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))

    keep: list[tuple[int, int, int, int]] = []
    for b in sorted(boxes, key=area, reverse=True):
        if not any(overlap(b, k) >= 0.5 * area(b) for k in keep):
            keep.append(b)
    return keep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--model", default="models/yolox.onnx")
    ap.add_argument("--links", help="JSON {table name: [x, y]} — which table each spot on the picture is")
    ap.add_argument("--waiters", help="JSON {table name: waiter name} (WaitLess resolves this itself in production)")
    ap.add_argument("--tiles", type=int, default=1, help="look at big pictures in n x n pieces (2 for 1080p)")
    ap.add_argument("--out", default="config/zones.json")
    args = ap.parse_args()

    boxes, size = suggest(args.source, args.model, tiles=args.tiles)
    links = json.loads(Path(args.links).read_text()) if args.links else {}
    waiters = json.loads(Path(args.waiters).read_text()) if args.waiters else {}
    # Ignore slivers (a table edge seen on its own): a real table box is not very flat.
    boxes = [b for b in boxes if (b[3] - b[1]) >= 60 and (b[2] - b[0]) / (b[3] - b[1]) < 2.2]
    boxes = drop_nested(boxes)
    zones: list[Zone] = []
    centres = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    if links:  # each table name takes the nearest shape; shapes nobody claimed are left out
        for label, (lx, ly) in links.items():
            i = min(range(len(boxes)), key=lambda k: (centres[k][0] - lx) ** 2 + (centres[k][1] - ly) ** 2)
            b = boxes[i]
            poly = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
            zones.append(Zone(label, poly, seats=4, waiter=waiters.get(label)))
    else:
        for n, b in enumerate(sorted(boxes, key=lambda b: (b[1] // 100, b[0])), 1):
            poly = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
            zones.append(Zone(f"T{n:02d}", poly, seats=4, waiter=waiters.get(f"T{n:02d}")))
    zones.sort(key=lambda z: z.label)
    save_zones(args.out, zones, size)
    print(f"Found {len(zones)} tables -> {args.out}")
    for z in zones:
        print(f"  {z.label}: box {z.bbox}  waiter {z.waiter}")


if __name__ == "__main__":
    main()
