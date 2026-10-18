"""Video -> detector -> per-frame signals -> rules -> verdict with time codes and evidence frames.

Camera-agnostic: the work area is found from the detected banknote counter / laptop, not from
fixed pixel regions, so the same rules run on a new angle.

Signals per sampled frame:
  people_at_desk   people whose box overlaps the (expanded) work area
  people_in_view   all people
  cash_on_desk     cash boxes inside the work area that no person's box covers much
  safe_open, door_open

Episodes (smoothed, minimum duration):
  cash_unattended   cash on the desk and nobody at the desk            -> ML02
  service_abandoned nobody at the desk while someone else is in view    -> ML01 (candidate)
  safe_left_open    safe open and nobody at the desk                   -> context

    .venv/bin/python -m ml.analyze_video --model models/v0m_early.pt video.mov --out result.json
"""

import argparse
import json
import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)
RULES = {
    "cash_unattended": (
        "ML02",
        "Наличные на рабочем месте без присмотра кассира",
        "Правила НБРК № 231, п. 20",
    ),
    "service_abandoned": (
        "ML01",
        "Кассир покинул рабочее место во время обслуживания",
        "Правила НБРК № 231, п. 22",
    ),
}


def expand(b, fx, fy, w, h):
    cx, cy, bw, bh = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[2] - b[0], b[3] - b[1]
    return [
        max(0, cx - bw * fx / 2),
        max(0, cy - bh * fy / 2),
        min(w, cx + bw * fx / 2),
        min(h, cy + bh * fy / 2),
    ]


def overlap(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return max(0, x1 - x0) * max(0, y1 - y0)


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def sample_frames(path, fps):
    import av

    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("Sampling FPS must be positive")
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("Video stream missing")
        stream = container.streams.video[0]
        step, next_t, origin = 1.0 / fps, 0.0, None
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError("Video frame has no presentation timestamp")
            timestamp = float(frame.pts * stream.time_base)
            if origin is None:
                origin = timestamp
            timestamp -= origin
            if timestamp + 1e-6 >= next_t:
                next_t = timestamp + step
                yield timestamp, frame.to_image()


def episodes(times, flags, min_len):
    out, start = [], None
    for t, f in zip(times, flags, strict=True):
        if f and start is None:
            start = t
        if not f and start is not None:
            if t - start >= min_len:
                out.append((start, t))
            start = None
    if start is not None and times and times[-1] - start >= min_len:
        out.append((start, times[-1]))
    return out


def analyze(
    model,
    video,
    fps=3.0,
    conf=0.35,
    imgsz=864,
    device="cpu",
    *,
    on_progress=None,
    duration=None,
):
    """Team detector, keeping detections rather than all decoded images in memory."""
    times, dets, dimensions = [], [], None
    for t, img in sample_frames(video, fps):
        r = model.predict(img, imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
        d = [
            {"cls": model.names[int(c)], "conf": float(s), "box": b}
            for b, c, s in zip(
                r.boxes.xyxy.tolist(),
                r.boxes.cls.tolist(),
                r.boxes.conf.tolist(),
                strict=True,
            )
        ]
        times.append(t)
        if len(times) % 30 == 0:
            logger.info("YOLO: %s sampled frames, video time %.2fs", len(times), t)
        if dimensions is None:
            dimensions = img.size
        dets.append(d)
        if on_progress is not None and duration is not None and duration > 0:
            # Report only frames whose inference has completed, never elapsed wall time.
            on_progress(min(0.99, max(0.0, t / duration)))
    if not times:
        raise ValueError("No frames were decoded; analysis was not completed")
    w, h = dimensions

    # Work area: median box of the counter/laptop detections over the whole video, expanded.
    anchors = [
        d["box"]
        for ds in dets
        for d in ds
        if d["cls"] in ("counter_machine",) or d["cls"].startswith("laptop")
    ]
    if anchors:
        mid = len(anchors) // 2
        x0, x1 = (
            min(sorted(a[0] for a in anchors)[: max(1, mid)]),
            max(sorted(a[2] for a in anchors)[mid:]),
        )
        y0, y1 = sorted(a[1] for a in anchors)[mid], sorted(a[3] for a in anchors)[mid]
        work = expand([x0, y0, x1, y1], 2.2, 3.5, w, h)
    else:
        work = [
            w * 0.15,
            h * 0.3,
            w * 0.85,
            h * 0.8,
        ]  # fallback: central lower part of the frame

    at_desk, cash_free, others, safe_open, door_open = [], [], [], [], []
    for ds in dets:
        people = [d["box"] for d in ds if d["cls"] == "person"]
        desk_people = [p for p in people if overlap(p, work) > 0.15 * area(p)]
        cash = [
            d["box"]
            for d in ds
            if d["cls"] == "cash"
            and d["conf"] >= 0.4
            and overlap(d["box"], work) > 0.5 * area(d["box"])
        ]
        uncovered = [
            c for c in cash if not any(overlap(c, p) > 0.6 * area(c) for p in people)
        ]
        at_desk.append(len(desk_people) > 0)
        cash_free.append(len(uncovered) > 0)
        others.append(len(people) - len(desk_people) > 0)
        safe_open.append(any(d["cls"] == "safe_open" for d in ds))
        door_open.append(any(d["cls"] == "door_open" for d in ds))

    flags = {
        "cash_unattended": [
            c and not a for c, a in zip(cash_free, at_desk, strict=True)
        ],
        "service_abandoned": [
            o and not a for o, a in zip(others, at_desk, strict=True)
        ],
    }
    found = []
    for kind, fl in flags.items():
        for s, e in episodes(
            times, fl, min_len=2.0 if kind == "cash_unattended" else 3.0
        ):
            code, title, rule = RULES[kind]
            found.append(
                {
                    "type": f"{code}: {title}",
                    "kind": kind,
                    "timecode_sec": round(s, 2),
                    "end_sec": round(e, 2),
                    "rule": rule,
                }
            )
    found.sort(key=lambda v: v["timecode_sec"])
    if on_progress is not None:
        on_progress(1.0)
    return {
        "verdict": "violation" if found else "no_violation",
        "used_fallback_area": not bool(anchors),
        "violations": found,
        "work_area": [round(v, 1) for v in work],
        "signals": {
            "t": [round(t, 2) for t in times],
            "at_desk": at_desk,
            "cash_free": cash_free,
            "others": others,
            "safe_open": safe_open,
            "door_open": door_open,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--model", required=True)
    ap.add_argument("--fps", type=float, default=3.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("YOLO_OFFLINE", "true")
    from ultralytics import YOLO

    if not Path(args.model).is_file():
        raise FileNotFoundError(args.model)
    model = YOLO(args.model)
    results = {}
    for v in args.videos:
        results[Path(v).name] = analyze(model, v, args.fps)
        r = results[Path(v).name]
        print(
            Path(v).name,
            r["verdict"],
            [(x["kind"], x["timecode_sec"]) for x in r["violations"]],
            flush=True,
        )
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
