"""Draws what the agent sees. Colours are deliberately NOT red/green, so they never get mixed up with the
overlay that some camera systems burn into the picture: free = blue, occupied = magenta, staff = cyan.

Sizes are designed for a picture about 850 pixels wide and scale up with bigger pictures (1080p cameras)."""

import cv2
import numpy as np

from agent.engine import Engine, Table
from agent.tracker import Track

# OpenCV colours are B, G, R.
BLUE, MAGENTA, CYAN, YELLOW, WHITE, INK = (
    (255, 128, 0),
    (255, 0, 255),
    (255, 255, 0),
    (0, 230, 255),
    (255, 255, 255),
    (30, 30, 30),
)
FONT = cv2.FONT_HERSHEY_SIMPLEX
_S = 1.0  # how much bigger than the 850-pixel design this picture is


def _t(n: float) -> int:
    """A thickness / length in design pixels, at this picture's size."""
    return max(1, int(round(n * _S)))


def _text(img, text, org, scale=0.45, color=WHITE, thick=1):
    cv2.putText(img, text, org, FONT, scale * _S, INK, _t(thick) + _t(2), cv2.LINE_AA)
    cv2.putText(img, text, org, FONT, scale * _S, color, _t(thick), cv2.LINE_AA)


def _box(img, p1, p2, fill, border, alpha=0.78):
    over = img.copy()
    cv2.rectangle(over, p1, p2, fill, -1)
    cv2.addWeighted(over, alpha, img, 1 - alpha, 0, img)
    cv2.rectangle(img, p1, p2, border, _t(1))


def _pill(img, lines, center, accent):
    widths = [cv2.getTextSize(t, FONT, 0.42 * _S, _t(1))[0][0] for t, _ in lines]
    w, h = max(widths) + _t(14), len(lines) * _t(17) + _t(8)
    x1, y1 = center[0] - w // 2, center[1] - h // 2
    _box(img, (x1, y1), (x1 + w, y1 + h), INK, accent, 0.75)
    for i, (t, col) in enumerate(lines):
        _text(img, t, (x1 + _t(7), y1 + _t(16) + i * _t(17)), 0.42, col)


def _fmt(sec: float) -> str:
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def draw(frame: np.ndarray, engine: Engine, tracks: list[Track], t: float, toasts: list[tuple[float, str]]) -> np.ndarray:
    global _S
    _S = max(1.0, frame.shape[1] / 850)
    out = frame.copy()
    for tb in engine.tables.values():
        _table(out, tb, t)
    for tr in tracks:
        if not tr.confirmed:
            continue
        x1, y1, x2, y2 = tr.box
        if tr.is_staff:
            serving = any(tb.visitor == tr.id and tb.visit_confirmed for tb in engine.tables.values())
            col = YELLOW if serving else CYAN
            cv2.rectangle(out, (x1, y1), (x2, y2), col, _t(2))
            _text(out, "WAITER SERVING" if serving else "WAITER", (x1, max(_t(12), y1 - _t(5))), 0.42, col)
            pts = np.array([(p[1], p[2]) for p in tr.path], np.int32)
            if len(pts) > 1:
                cv2.polylines(out, [pts], False, col, _t(1), cv2.LINE_AA)
        elif tr.seated_now:
            cv2.rectangle(out, (x1, y1), (x2, y2), MAGENTA, _t(1))
    _panel(out, engine, toasts, t)
    return out


def _table(img, tb: Table, t: float) -> None:
    z = tb.zone
    pts = np.array(z.polygon, np.int32)
    occupied = tb.status == "occupied"
    col = MAGENTA if occupied else BLUE
    shade = img.copy()
    cv2.fillPoly(shade, [pts], col)
    cv2.addWeighted(shade, 0.14, img, 0.86, 0, img)
    cv2.polylines(img, [pts], True, col, _t(2), cv2.LINE_AA)
    if occupied:
        plural = "s" if tb.guests != 1 else ""
        lines = [(f"{z.label}  OCCUPIED", MAGENTA), (f"{tb.guests} guest{plural}  {_fmt(t - (tb.seated_at or t))}", WHITE)]
        if z.waiter:
            lines.append((z.waiter, YELLOW))
        _pill(img, lines, z.center, col)
    else:
        _pill(img, [(f"{z.label}  FREE", BLUE)], z.center, col)


def _panel(img, engine: Engine, toasts: list[tuple[float, str]], t: float) -> None:
    w = img.shape[1]
    pw = _t(284)
    x, y = w - pw - _t(8), _t(8)
    cap = max(engine.capacity, 1)
    _box(img, (x, y), (x + pw, y + _t(62)), INK, CYAN, 0.8)
    _text(img, "WaitLess Floor Agent", (x + _t(8), y + _t(17)), 0.5, CYAN)
    _text(img, f"Tables {engine.occupied}/{len(engine.tables)}", (x + _t(8), y + _t(38)), 0.45)
    _text(img, f"Guests {engine.seated_guests}/{engine.capacity}", (x + _t(100), y + _t(38)), 0.45)
    _text(img, f"Load {100 * engine.seated_guests // cap}%", (x + _t(205), y + _t(38)), 0.45)
    cv2.rectangle(img, (x + _t(8), y + _t(48)), (x + pw - _t(8), y + _t(53)), (80, 80, 80), -1)
    cv2.rectangle(
        img, (x + _t(8), y + _t(48)), (x + _t(8) + int((pw - _t(16)) * engine.seated_guests / cap), y + _t(53)), CYAN, -1
    )
    live = [m for ts, m in toasts if t - ts < 6][-3:]
    for i, msg in enumerate(live):
        yy = y + _t(78) + i * _t(38)
        _box(img, (x, yy), (x + pw, yy + _t(32)), INK, INK, 0.85)
        cv2.rectangle(img, (x, yy), (x + _t(4), yy + _t(32)), YELLOW, -1)
        _text(img, msg[:42], (x + _t(10), yy + _t(20)), 0.42, WHITE)
