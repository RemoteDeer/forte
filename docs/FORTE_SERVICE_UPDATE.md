# Forte service update — 18 October 2026

Integrated the supplied `forte_service.zip`: object detector `forte_det.pt` and
open/closed classifiers `forte_door.pt` / `forte_safe.pt`. All three checkpoint
checksums match the archive. Class names and model tasks were checked after loading.

The default callable is `ml.service_inference:analyze`, with `FORTE_MODEL_DIR=models`.
The supplied script is in `ml/forte_service.py`; only import timing and lint formatting
were adjusted. Signal computation, frame sampling and violation rules match the
supplied source. The old `ml.inference:analyze` adapter remains available for comparison.

The six source event types map to ML02–ML07. Types, descriptions, point timestamps
and evidence timestamps are preserved. The backend generates its standard JPEGs and
rule objects. Event confidence and episode boundaries are not invented. Failed decoding
is propagated as failure rather than a clean verdict. Progress uses completed frames.

## Real video checks

| Video | New pipeline result |
| --- | --- |
| Х-32.mov | ML05, door left open, at 3.00 s |
| Х-14.mov | ML07, previous client’s cash not removed, at 43.50 s |
| Х-46.mov | No violations |
| Х-37.mov | No violations |
| Х-44.mov | No violations |
| Х-24.mov | No violations |
| Х-34.mov | No violations |

The 142.53-second `Х-14.mov` completed locally in 151.89 seconds, within the
270-second backend deadline. This is a measurement on this computer, not a guarantee
for all videos. These are model outputs, not independently labeled accuracy estimates.
The previous audit’s three events in `Х-46.mov` concern the old model and rules.

All 45 backend tests passed. Tests cover mapping all six events, all three required
weight files, error propagation, door/safe duration thresholds, and all six types
through the API with valid JPEG evidence. Source rules and frame sampling were also
compared with the package’s AST. Details and weight hashes are in
[forte-service-verification.json](forte-service-verification.json).

The running API independently reproduced the door event in `Х-32.mov` at 3.00 s
with two valid JPEG frames and matching SQLite data; `Х-46.mov` completed with
no violations. Uploaded bytes were unchanged. Both jobs showed intermediate frame
progress and matched the supplied script’s direct outputs.

## Dependencies and deployment

Install CPU torch using `ml/requirements-cpu.txt`, then the current service using
`ml/requirements-service.txt` (Ultralytics >=8.4). Docker keeps the baseline dependency
layer separate from the service constraints to preserve its cached CPU torch install.

The first clean image rebuild hit a PyTorch download timeout; a retry hit Docker Hub
DNS failure. For this machine the runtime image was updated offline from the previously
verified image, whose Ultralytics 8.4.181, CPU torch and other dependencies already
satisfy the new service. Current backend and ML source were copied into that image;
the existing frontend was preserved. The repository Dockerfile still supports a fresh
build when package registries are reachable.

Normal deployment: `docker compose up --build -d --force-recreate --wait`.
The local updated image can be started with `docker compose up --no-build -d`.
The script retains sampled images in memory; long videos therefore use more RAM.
The legal references supplied by the model author remain marked unverified.
