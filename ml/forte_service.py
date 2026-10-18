"""ForteBank cash-room video analysis -> result in the hackathon API format.

    from forte_analyze import Analyzer
    result = Analyzer("models").analyze("video.mov")      # {"verdict": ..., "violations": [...]}

    python forte_analyze.py models video.mov [--out result.json]

Pipeline (fully local): object detector fine-tuned on real Forte frames (people, cash, cash bag,
laptop with screen state, banknote counter, safe ...), door open/closed classifier on the whole
frame, safe open/closed classifier on the detected safe, then time rules over the signals.
"""

import argparse
import base64
import json
from pathlib import Path

import cv2
import numpy as np

FPS = 2.0
RULES = {
    "cash_left": (
        "Деньги оставлены без присмотра",
        "Кассир покинул рабочее место, наличные остались на столе.",
        "Правила НБРК № 231 (кассовые операции), п. 20 — хранение наличных",
    ),
    "bag_left": (
        "Инкассаторская сумка оставлена без присмотра",
        "Кассир покинул рабочее место, сумка с ценностями осталась на столе.",
        "Правила НБРК № 231, п. 20, 24 — приём и хранение ценностей",
    ),
    "laptop_unlocked": (
        "Компьютер не заблокирован при уходе",
        "Кассир покинул рабочее место, экран ноутбука остался включённым и разблокированным.",
        "Требования к информационной безопасности рабочего места кассира",
    ),
    "door_open": (
        "Дверь кассового помещения оставлена открытой",
        "Дверь кассового помещения открыта длительное время во время работы.",
        "Правила НБРК № 231, п. 12 — порядок доступа в кассовое помещение",
    ),
    "safe_open": (
        "Сейф оставлен открытым",
        "Сейф открыт длительное время / при отсутствии кассира.",
        "Правила НБРК № 231, п. 20 — хранение ценностей в сейфе",
    ),
    "previous_cash": (
        "Деньги предыдущего клиента не убраны",
        "Клиент ушёл, его наличные остались на столе до прихода следующего клиента.",
        "Правила НБРК № 231, п. 20 — хранение наличных",
    ),
}


def box_overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def area(b):
    return max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))


def runs(flags, t, min_len):
    """[(start, end)] of True runs lasting at least min_len seconds."""
    out, s = [], None
    for i, f in enumerate(flags):
        if f and s is None:
            s = i
        if (not f or i == len(flags) - 1) and s is not None:
            e = i if not f else i
            if t[e] - t[s] >= min_len:
                out.append((s, e))
            s = None
    return out


def smooth(x, k):
    a = np.asarray(x, dtype=float)
    return np.array([np.median(a[max(0, i - k) : i + k + 1]) for i in range(len(a))])


class Analyzer:
    def __init__(self, models_dir, device="cpu"):
        from ultralytics import YOLO

        m = Path(models_dir)
        self.det = YOLO(str(m / "forte_det.pt"))
        self.door = YOLO(str(m / "forte_door.pt"))
        self.safe = YOLO(str(m / "forte_safe.pt"))
        self.device = device

    def frames(self, path):
        cap = cv2.VideoCapture(str(path))
        nxt = 0.0
        while True:
            ok, img = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t + 1e-6 >= nxt:
                nxt = t + 1.0 / FPS
                yield t, img
        cap.release()

    def observe(self, path):
        obs, imgs = [], []
        for t, img in self.frames(path):
            r = self.det.predict(img, imgsz=864, conf=0.25, device=self.device, verbose=False)[0]
            dets = [
                (self.det.names[int(c)], float(s), b)
                for b, c, s in zip(
                    r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist(), strict=False
                )
            ]
            d = self.door.predict(img, imgsz=320, device=self.device, verbose=False)[0]
            door_open = float(d.probs.data[list(self.door.names.values()).index("open")])
            safe_open = 0.0
            safes = [b for n, s, b in dets if n == "safe" and s >= 0.4]
            if safes:
                x0, y0, x1, y1 = safes[0]
                w, h = x1 - x0, y1 - y0
                crop = img[
                    int(max(0, y0 - 0.35 * h)) : int(min(img.shape[0], y1 + 0.35 * h)),
                    int(max(0, x0 - 0.35 * w)) : int(min(img.shape[1], x1 + 0.35 * w)),
                ]
                if crop.size:
                    sp = self.safe.predict(crop, imgsz=224, device=self.device, verbose=False)[0]
                    safe_open = float(sp.probs.data[list(self.safe.names.values()).index("open")])
            obs.append({"t": t, "dets": dets, "door_open": door_open, "safe_open": safe_open})
            imgs.append(img)
        return obs, imgs

    @staticmethod
    def signals(obs):
        fixed = [
            b
            for o in obs
            for n, s, b in o["dets"]
            if s >= 0.5 and (n in ("counter_machine", "safe") or n.startswith("laptop"))
        ]
        zone = None
        if fixed:
            k = len(fixed) // 10
            xs0, ys0, xs1, ys1 = (sorted(b[i] for b in fixed) for i in range(4))
            x0, y0, x1, y1 = xs0[k], ys0[k], xs1[-1 - k], ys1[-1 - k]
            w, h = x1 - x0, y1 - y0
            zone = [x0 - 0.5 * w, y0 - 0.5 * h, x1 + 0.5 * w, y1 + 1.6 * h]
        sig = []
        for o in obs:
            ppl = [b for n, s, b in o["dets"] if n == "person" and s >= 0.45]
            if zone:
                ppl = [
                    p
                    for p in ppl
                    if zone[0] <= (p[0] + p[2]) / 2 <= zone[2] and zone[1] <= p[3] <= zone[3]
                ]
            counters = [b for n, s, b in o["dets"] if n == "counter_machine" and s >= 0.4]
            cash = [
                b
                for n, s, b in o["dets"]
                if n == "cash"
                and s >= 0.45
                and not any(box_overlap(b, c) > 0.3 * area(b) for c in counters)
            ]
            sig.append(
                {
                    "t": o["t"],
                    "people": len(ppl),
                    "cash": bool(cash),
                    "cash_boxes": cash,
                    "bag": any(n == "collection_bag" and s >= 0.45 for n, s, b in o["dets"]),
                    "laptop_on": any(n == "laptop_active" and s >= 0.5 for n, s, b in o["dets"]),
                    "door_open": o["door_open"] >= 0.5,
                    "safe_open": o["safe_open"] >= 0.5,
                }
            )
        return sig

    @staticmethod
    def rules(sig):
        t = [s["t"] for s in sig]
        n = len(sig)
        people = smooth([s["people"] for s in sig], 3)
        cash = smooth([s["cash"] for s in sig], 2)
        bag = smooth([s["bag"] for s in sig], 2)
        lap = smooth([s["laptop_on"] for s in sig], 2)
        door = smooth([s["door_open"] for s in sig], 1)
        safe = smooth([s["safe_open"] for s in sig], 1)
        found = []
        # cashier leaves: zone had someone, then empty >= 2 s (or until the end)
        i = 1
        while i < n:
            if people[i - 1] >= 1 and people[i] == 0:
                j = i
                while j < n and people[j] == 0:
                    j += 1
                if t[min(j, n - 1)] - t[i] >= 2.0 or j == n:
                    w = list(range(max(0, i - 2), min(n, i + 6)))
                    for kind, s in (
                        ("cash_left", cash),
                        ("bag_left", bag),
                        ("laptop_unlocked", lap),
                        ("safe_open", safe),
                    ):
                        if np.mean([s[k] for k in w]) >= 0.5:
                            found.append((kind, i))
                i = j
            i += 1
        for s0, _e0 in runs(door >= 0.5, t, 5.0):
            found.append(("door_open", s0))
        for s0, _e0 in runs(safe >= 0.5, t, 8.0):
            found.append(("safe_open", s0))
        for i in range(1, n):
            if people[i - 1] >= 2 and people[i] == 1 and cash[i] >= 0.5:
                j = i
                while j < n and people[j] <= 1 and cash[j] >= 0.5:
                    j += 1
                if j < n and people[j] >= 2 and cash[j] >= 0.5 and t[j] - t[i] >= 3:
                    found.append(("previous_cash", j))
        # one event per kind, earliest
        best = {}
        for kind, k in found:
            if kind not in best or k < best[kind]:
                best[kind] = k
        return sorted(best.items(), key=lambda x: x[1])

    def analyze(self, path):
        obs, imgs = self.observe(path)
        if not obs:
            return {
                "status": "failed",
                "verdict": "no_violation",
                "violations": [],
                "error": "no frames decoded",
            }
        sig = self.signals(obs)
        violations = []
        for kind, k in self.rules(sig):
            title, why, rule = RULES[kind]
            frames = []
            for j in sorted({k, min(len(imgs) - 1, k + 2)}):
                ok, jpg = cv2.imencode(".jpg", imgs[j], [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    frames.append(
                        {
                            "timestamp_sec": round(obs[j]["t"], 2),
                            "image_base64": base64.b64encode(jpg.tobytes()).decode(),
                        }
                    )
            violations.append(
                {
                    "type": title,
                    "timecode_sec": round(obs[k]["t"], 2),
                    "description": (
                        f"{why} Основание: {rule}. "
                        "Результат — подсказка для проверки человеком."
                    ),
                    "rule": rule,
                    "evidence_frames": frames,
                }
            )
        return {
            "status": "done",
            "verdict": "violation" if violations else "no_violation",
            "violations": violations,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    a = Analyzer(args.models, args.device)
    results = {}
    for v in args.videos:
        r = a.analyze(v)
        results[Path(v).name] = r
        print(
            Path(v).name,
            r["verdict"],
            [(x["type"], x["timecode_sec"]) for x in r["violations"]],
            flush=True,
        )
    if args.out:
        slim = {
            k: {
                **r,
                "violations": [
                    {
                        **x,
                        "evidence_frames": [
                            {"timestamp_sec": f["timestamp_sec"]} for f in x["evidence_frames"]
                        ],
                    }
                    for x in r["violations"]
                ],
            }
            for k, r in results.items()
        }
        Path(args.out).write_text(json.dumps(slim, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
