"""Run the Floor Agent on a video file or an RTSP camera stream.

    python run.py --source ../design/cctv.mp4 --out out/agent.mp4 --demo
    python run.py --source rtsp://localhost:8554/cctv_sub --show --demo

--demo shortens every wait so a 40-second clip shows everything. Without it the real timings apply (guests must stay
30 s to count as seated, 2 minutes empty to count as left, a waiter must stay 10 s to count as a visit).
"""

import argparse
import threading
import time
from pathlib import Path

from agent.capture import StreamReader  # sets the RTSP options, so it must load before OpenCV opens anything
import cv2  # noqa: I001
from agent.detector import Detector
from agent.engine import Engine, Settings
from agent.overlay import draw
from agent.staff import DARK_SHARE, Perspective, torso_dark_share
from agent.tracker import Tracker
from agent.uplink import Uplink, pair
from agent.zones import load_zones, scale_zones

DEMO = {
    "seat_after": 3.0,
    "leave_after": 6.0,
    "visit_after": 0.3,
    "still": 60.0,
    "reach": 60.0,
    "sit_confirm": 4.0,
    "count_window": 8.0,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="video file or rtsp:// address (use the camera's sub-stream)")
    ap.add_argument("--zones", default="config/zones.json")
    ap.add_argument("--model", default="models/yolox.onnx")
    ap.add_argument("--out", help="write the annotated video here")
    ap.add_argument("--show", action="store_true", help="live preview window (q to quit)")
    ap.add_argument("--sample-fps", type=float, default=3.0, help="how many times a second to look for people")
    ap.add_argument("--demo", action="store_true", help="short waits, for short test clips")
    ap.add_argument("--perspective", default="config/perspective.json", help="where the camera calibration is kept")
    ap.add_argument("--server", help="WaitLess address, e.g. https://app.waitless.example (needed with --pair)")
    ap.add_argument("--pair", metavar="CODE", help="pair this laptop with a restaurant using the owner's one-time code")
    ap.add_argument("--offline", action="store_true", help="do not talk to WaitLess even if this laptop is paired")
    ap.add_argument("--agent-config", default="config/agent.json")
    ap.add_argument("--tiles", type=int, default=0, help="look at big pictures in n x n pieces (default: 2 above 1280 px wide)")
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--debug", action="store_true", help="print what the agent thinks each person is")
    for name in Settings.__dataclass_fields__:
        ap.add_argument(f"--{name.replace('_', '-')}", type=float, default=None)
    args = ap.parse_args()

    if args.pair:
        if not args.server:
            raise SystemExit("Give the WaitLess address with --server when pairing.")
        done = pair(args.server, args.pair, args.agent_config)
        print(f"Paired with branch of '{done['agent']['name']}'. Tables: {', '.join(t['label'] for t in done['tables'])}")

    base = Settings()
    settings = Settings(
        **{
            name: getattr(args, name)
            if getattr(args, name) is not None
            else (DEMO[name] if args.demo and name in DEMO else getattr(base, name))
            for name in Settings.__dataclass_fields__
        }
    )

    is_stream = args.source.lower().startswith(("rtsp://", "rtmp://", "http"))
    reader = cap = None
    if is_stream:
        reader = StreamReader(args.source)
        if not reader.wait_for_first():
            raise SystemExit(f"No picture from {args.source} - is the camera address right and the stream running?")
        fps, (w, h) = 25.0, reader.size
    else:
        cap = cv2.VideoCapture(args.source, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise SystemExit(f"Cannot open {args.source}")
        fps, (w, h) = cap.get(cv2.CAP_PROP_FPS) or 25.0, (int(cap.get(3)), int(cap.get(4)))
    out_fps = 10.0 if is_stream else fps  # the sub-stream is 10 pictures a second
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), out_fps, (w, h)) if args.out else None

    zones, drawn_on = load_zones(args.zones)
    zones = scale_zones(zones, drawn_on, (w, h))
    uplink = None
    if not args.offline and Path(args.agent_config).exists():
        uplink = Uplink(args.agent_config)
        try:  # the waiter in charge of each table comes from WaitLess; the picture only shows it
            known = {t["label"].lower(): t for t in uplink.tables()}
        except Exception as exc:  # noqa: BLE001
            print(f"Could not read the tables from WaitLess ({exc}); events will be kept and sent when it is back.")
            known = {}
        for z in zones:
            t = known.get(z.label.lower())
            if t is not None:
                z.waiter = t["waiter_name"]
            elif known:
                print(f"  ! zone {z.label} is not a table in WaitLess: its events will be ignored there")
        print(f"Connected to {uplink.server} ({uplink.sent} sent so far, {len(uplink.pending)} waiting)")
    engine = Engine(zones, settings)
    tiles = args.tiles or (2 if w > 1280 else 1)
    detector, tracker, persp = Detector(args.model, tiles=tiles), Tracker(), Perspective(args.perspective)
    toasts: list[tuple[float, str]] = []
    tracks: list = []
    last, started, n, seen = -1e9, time.monotonic(), 0, 0
    busy = threading.Event()

    def analyse(frame, t: float) -> None:
        nonlocal tracks
        try:
            before = len(engine.events)
            found = tracker.update(detector.detect(frame), t)
            for tr in found:
                if tr.speed(t) > 50 and tr.height / max(tr.width, 1) > 2.2:
                    persp.learn(tr.box)  # a walking person shows how tall people look at this spot
                seated = persp.is_seated(tr.box)
                share = torso_dark_share(frame, tr.box)
                tr.seated_votes.append(seated)
                if not seated:  # the uniform is judged while standing (bending over a table hides it)
                    tr.dark.append(share >= DARK_SHARE)
                tr.seated_since = (tr.seated_since if tr.seated_since is not None else t) if tr.seated_now else None
                if args.debug:
                    print(
                        f"  t={t:5.1f} #{tr.id:<2} box={tr.box} dark={share:.2f} staff={tr.is_staff} "
                        f"seated={tr.seated_now} speed={tr.speed(t):.0f}"
                    )
            engine.update(found, t)
            for ev in engine.events[before:]:
                if ev.kind in ("seated", "left"):
                    if uplink:
                        uplink.enqueue(ev.kind, ev.table, ev.guests)
                    what = "guests seated" if ev.kind == "seated" else "is empty"
                    toasts.append((t, f"{ev.notify or 'All waiters'}: {ev.table} {what}"))
            tracks = found
        finally:
            busy.clear()

    mode = "  [demo timings]" if args.demo else ""
    print(f"Watching {args.source}  ({w}x{h}, {len(zones)} tables){mode}", flush=True)
    try:
        while True:
            if is_stream:
                seq, frame = reader.read()
                if frame is None or seq == seen:
                    time.sleep(0.01)
                    continue
                seen, t = seq, time.monotonic() - started
            else:
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                t = n / fps
            if args.max_seconds and t > args.max_seconds:
                break
            if t - last >= 1.0 / args.sample_fps and not busy.is_set():  # a few times a second, not every frame
                last = t
                if is_stream:  # the detector is slow: run it on its own thread so the picture stays smooth
                    busy.set()
                    threading.Thread(target=analyse, args=(frame.copy(), t), daemon=True).start()
                else:
                    analyse(frame, t)
            view = draw(frame, engine, tracks, t, toasts)
            if writer:
                writer.write(view)
            if args.show:
                cv2.imshow("WaitLess Floor Agent", view)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if writer:
            writer.release()
        if reader:
            reader.close()
        if uplink:
            uplink.close()
        if cap:
            cap.release()
        cv2.destroyAllWindows()
    persp.save()
    print(f"Standing-height ratio learned: {persp.standing_ratio}")
    print(f"Done: {len(engine.events)} events in {time.monotonic() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
