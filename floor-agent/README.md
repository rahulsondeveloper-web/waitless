# WaitLess Floor Agent

Runs on the restaurant's own laptop. It watches the CCTV **sub-stream** (RTSP), works out what is happening at each
table with Python + OpenCV, and (once connected to WaitLess) tells the **waiter in charge of that table**.
No video leaves the laptop.

Status: detection, table shapes, the seated / left / waiter-visit logic, the on-screen view, pairing with WaitLess and
sending alerts to the waiter in charge of the table all work against a test camera. Not yet done: the installer for
owners, an owner dashboard of table times, and staff names (shift check-in).

## What it detects

| | How |
|---|---|
| **Tables** | Found automatically from the picture (`python -m agent.setup_zones`), then linked to a WaitLess table name. In the product the owner confirms or edits them on screen. |
| **Guests seated** | A person sitting inside a table's shape for `seat-after` seconds (real: 30 s). Counted per table, with a running timer. |
| **Guests left** | Nobody sitting there for `leave-after` seconds (real: 2 min). |
| **Waiter** | Dark uniform, standing. Someone in dark clothes who then sits for a while is a guest, not a waiter. |
| **Waiter visit** | A waiter standing still beside a table that has guests for `visit-after` seconds (real: 10 s). Gives the time from "guests sat" to "first visit". |

Colours are deliberately not red/green so they never get mixed up with a camera system's own overlay:
**blue = free, magenta = occupied, cyan = waiter, yellow = waiter serving.**

## Who gets notified

The agent only reports "table T02: guests seated". WaitLess looks up which waiter is in charge of T02
(`restaurant_tables.waiter_user_id`) and notifies that person. In this test build the waiter name comes from
`config/zones.json` so you can see who would be told.

## Setup (Windows)

```powershell
cd floor-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Needed, kept inside this folder and not installed system-wide:

- `models\yolox.onnx` — YOLOX person/table model (Apache-2.0), from the OpenCV model zoo
- `tools\mediamtx\` — MediaMTX (RTSP server), only for testing
- `tools\ffmpeg\` — a portable FFmpeg build, only for testing

## Try it on the test video

```powershell
# 1. Once: find the tables in the clip and name them
.\.venv\Scripts\python.exe -m agent.setup_zones --source ..\design\cctv.mp4 --links config\test_links.json --waiters config\test_waiters.json

# 2a. Straight from the file, writes an annotated video
.\.venv\Scripts\python.exe run.py --source ..\design\cctv.mp4 --out out\demo.mp4 --demo

# 2b. As a live camera: starts MediaMTX + FFmpeg (loops design\cctv.mp4) and opens a preview window
powershell -ExecutionPolicy Bypass -File scripts\run-agent-test.ps1
```

`--demo` shortens every wait so a 40-second clip shows everything. Leave it off for real timings.
Example outputs: `out\floor_agent_demo_file.mp4`, `out\floor_agent_demo_rtsp.mp4`.

## Connect it to WaitLess (so the right waiter is told)

1. In WaitLess: **Tables → Setup → Camera laptop → Pair a laptop**. It shows a one-time code (valid 15 minutes).
2. On the laptop, once:
   ```powershell
   .\.venv\Scripts\python.exe run.py --server https://your-waitless-address --pair ABCD-EFGH --source "rtsp://..."
   ```
   Pairing saves a key in `configgent.json`. After that, `run.py --source "rtsp://..."` is enough.
3. Zone names must match the WaitLess table names (T1, T2, P1...). The agent warns about any that do not.

The agent reports only "T2: guests seated / left". **WaitLess** looks up the waiter in charge of T2 at that moment and
pushes the alert to that waiter only (everyone on shift if the table has no waiter). If the internet drops, events
wait in `config\outbox.json` and are sent when it returns; each has its own ID, so nothing is counted twice.

## Big pictures (1080p cameras)

Above 1280 pixels wide the agent looks at the picture in 2 x 2 overlapping pieces (`--tiles`), so small, far-away
tables and people get more pixels. It is slower (about 4x per look), so prefer the camera's **sub-stream** on a
real laptop and keep the table zones to the tables that are reasonably close to the camera. Far tables on a wide,
fisheye view are too small to judge reliably. Automatic table finding can leave fragments at tile edges: the owner
removes or resizes those on screen before using the zones (`config\zones_sample_fixed.json` was corrected this way).

## On a real camera

```powershell
.\.venv\Scripts\python.exe run.py --source "rtsp://user:password@192.168.1.20:554/Streaming/Channels/102" --show
```

Use the camera's **sub-stream** (smaller and lighter). Typical addresses:

| Brand | Sub-stream |
|---|---|
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/102` |
| Dahua / CP Plus | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=1` |

Draw the table shapes on a picture from that camera (zones are scaled to whatever size the stream is). The agent
learns by itself how tall standing people look on that camera and saves it in `config\perspective.json`.

## How it works

```
RTSP sub-stream ─► StreamReader (newest frame only, reconnects) ─► YOLOX person detection (3 per second)
  ─► Tracker (one ID per person) ─► Perspective (sitting or standing?) ─► uniform colour (waiter or guest?)
  ─► Engine (per-table state: free / occupied, visits) ─► events ─► overlay / WaitLess
```

| File | Job |
|---|---|
| `agent/capture.py` | Reads the stream on a thread, keeps only the newest frame, reconnects |
| `agent/detector.py` | YOLOX through OpenCV's DNN module (CPU only) |
| `agent/tracker.py` | Keeps each person's ID between pictures |
| `agent/staff.py` | Uniform colour and the camera's "how tall is a standing person here" learning |
| `agent/zones.py` | Table shapes and the link to a WaitLess table and waiter |
| `agent/engine.py` | Seated / left / visit rules and the events |
| `agent/overlay.py` | What is drawn on the picture |
| `run.py` | Ties it together |

## Known limits (Phase 0)

- Group sizes are undercounted when people hide each other (a table of 4 is often counted as 2-3).
- Telling a waiter from a guest in dark clothes is only by behaviour (a guest sits, a waiter doesn't). Staff names
  need the shift check-in planned for Phase 4.
- Short stops: the clip's waiter stands at T02 for under a second, so `--demo` uses a very short visit time.
- About 0.3 s per picture on this laptop (3 per second). Fine for one camera.
