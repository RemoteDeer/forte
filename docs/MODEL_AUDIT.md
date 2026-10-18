# Model integration audit — 18 October 2026

This report concerns the previous `v0m_early.pt` / `ml.inference` pipeline.
The subsequently supplied three-model `forte_service` package is described in
[ML_CONTRACT.md](ML_CONTRACT.md); the positive timings below are historical results
of the previous model, not predictions guaranteed by the replacement model.

The supplied checkpoint is connected correctly. A real positive was reproduced through
both the original detector and the deployed Docker API. No backend loss of violations
or inference-parameter mismatch was found in this audit. No model weights, confidence
thresholds, or violation rules were changed to obtain the positive result.

## Positive video to check

Upload **`Х-46.mov`** from the supplied videos directory (the first letter is Cyrillic `Х`).
The detector returns ML02, cash unattended, in three ranges:

| Start, seconds | End, seconds |
| --- | --- |
| 1.33 | 5.00 |
| 8.00 | 11.33 |
| 13.67 | 17.33 |

The deployed API completed job `3f64b24f69b0440fa8fd793bb4276d08` in plugin mode with all three
ranges intact, six valid JPEG evidence frames, and the same three events in SQLite.
SHA-256 of the stored upload matched the source video: upload handling did not alter it.
These are detector candidates for human review, not independently labeled ground truth.

## Checkpoint and inference

- `models/v0m_early.pt` matches the original supplied file and Docker-mounted file.
- SHA-256: `d4179f8b69e6b1af4a6019fcf8d0b09cb062f0d25e38a0cd0947f874c26bd1ca`.
- Task: `detect`; 18 class names, mapped from the checkpoint rather than hardcoded class IDs.
- Checkpoint Ultralytics version and installed Docker version: `8.4.181`.
- Docker: PyTorch `2.9.1+cpu`, torchvision `0.24.1+cpu`, PyAV `18.1.0`, OpenCV `4.14.0.94`.
- Original defaults preserved: sampling 3 FPS, confidence 0.35, image size 864, CPU.
  The original additional cash confidence threshold remains 0.4.
- PIL/RGB frames are passed to Ultralytics as in the supplied script. The frontend
  and OpenCV evidence extraction do not preprocess the model's input.
- The checkpoint records precision 0.95438, recall 0.84969, mAP50 0.91028,
  and mAP50–95 0.78326. These are saved training/validation metrics, not a new evaluation.
  The checkpoint alone does not establish which validation dataset produced them.

## Dataset comparison

Selected the **20 shortest** local MOV files to bound CPU processing time.
This is not a random sample and has no independently verified violation labels.
Actual YOLO inference processed **1074 sampled frames**. For every file:

1. Recorded inference outputs from the integrated detector.
2. Decoded/sampled the file again using the supplied original script; compared SHA-256
   of every sampled image's pixels against the integration's inputs.
3. Replayed the same YOLO predictions through the original script and compared all
   original output fields, including signals, work area, verdict, ranges, and types.
4. Validated the adapter output against the backend schema and checked time bounds.

All 20 comparisons matched. For `Х-46.mov`, a further **independent fresh inference**
using the unmodified original script also matched all original output fields.
The deployed Docker API then independently analyzed the actual uploaded video.

| Video | Duration, seconds | Sampled frames | Episodes |
| --- | ---: | ---: | ---: |
| `Х-20.mov` | 11.63 | 35 | 0 |
| `Х-33.mov` | 14.33 | 43 | 0 |
| `Х-24.mov` | 14.70 | 45 | 0 |
| `Х-17.mov` | 14.73 | 45 | 0 |
| `Х-10.mov` | 15.57 | 47 | 0 |
| `Х-37.mov` | 15.87 | 48 | 0 |
| `Х-28.mov` | 16.53 | 50 | 0 |
| `X-2.mov` | 17.07 | 52 | 0 |
| `Х-29.mov` | 17.30 | 52 | 0 |
| `Х-34.mov` | 17.73 | 54 | 0 |
| `Х-23.mov` | 18.27 | 55 | 0 |
| `Х-30.mov` | 18.80 | 57 | 0 |
| `Х-46.mov` | 19.13 | 58 | 3 |
| `Х-21.mov` | 19.60 | 59 | 0 |
| `Х-26.mov` | 19.80 | 60 | 0 |
| `Х-3.mov` | 20.03 | 61 | 0 |
| `Х-44.mov` | 20.43 | 62 | 0 |
| `Х-15.mov` | 20.87 | 63 | 0 |
| `Х-22.mov` | 21.03 | 64 | 0 |
| `Х-32.mov` | 21.30 | 64 | 0 |

**Result: 1 of 20 videos produced violations; 3 episodes total.**
Detailed object counts, signals, ranges, and checkpoint metadata are recorded in
[model-audit-results.json](model-audit-results.json). Per-file elapsed times in that
artifact include diagnostics and, on the final video, concurrent CPU/memory contention;
they are not deployment benchmarks.

## Backend checks

- All 38 backend tests passed, including both positive ML rules, multiple episodes,
  confidence omission, valid JPEG evidence, persistence, and frame-based progress.
- Missing weights, corrupt video, model exceptions, malformed results, unknown rules,
  and invalid time bounds fail explicitly rather than silently becoming `no_violation`.
- The adapter preserves each returned event; the backend applies no additional
  confidence filter. The frontend maps/sorts the event list without filtering it.
- The YOLO adapter intentionally omits event confidence because the supplied script
  does not calculate one; missing confidence does not remove an event.
- Dependency consistency check passed. Docker uses plugin mode, the local checkpoint,
  and the expected callable `ml.inference:analyze`.

## Remaining limits

The script only generates `cash_unattended` (minimum 2 seconds) and
`service_abandoned` (minimum 3 seconds). Other object classes, such as phone, door,
safe, and laptop state, do not independently generate violations in the supplied script.
For example, `Х-34.mov` has a phone detection and `Х-37.mov` has open-door detections,
but the original script does not define violation rules for them.

People are not classified as cashier versus customer. The work area and consecutive
frame-duration conditions can suppress a candidate; this is original detector logic,
not backend filtering. ML02 on the positive video used the script's fallback work area.
Accuracy and false positives/negatives still require a labeled evaluation set.
The ML01/ML02 legal citations remain unverified, as documented in the ML contract.

No model or backend behavior needed changing as a result of this audit.
