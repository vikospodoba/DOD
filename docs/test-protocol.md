# Prototype Test Protocol

## Required Environment

- Browser: current Chrome or Edge.
- Camera: Full HD USB camera, target 1920x1080 at 30 FPS.
- Network: wired local network, at least 100 Mbit/s.
- Server: NVIDIA RTX GPU with CUDA runtime; record exact model and VRAM.
- Source faces: at least `default-human`.

## Checks

| # | Check | Expected result |
|---|---|---|
| 1 | `docker compose up --build` | Java service and worker become healthy. |
| 2 | Open prototype URL | Interface loads and lists source faces. |
| 3 | Start camera | Browser asks only for camera permission; mirrored video appears. |
| 4 | Select each source face | Active card changes without restarting the camera. |
| 5 | Worker unavailable | Source video remains visible; Java stays responsive. |
| 6 | 720p and 1080p run | FPS, latency, inference time are recorded. |
| 7 | 2, 4, 6, 8, 10 people in frame with `manyFaces` enabled | FPS drop and visual stability are recorded for each group size. |
| 8 | 30-minute run | No crash and no steady memory growth. |

## Metrics to Record

- Browser FPS.
- Full latency.
- Worker inference time.
- GPU memory usage.
- Network throughput.
- Number of detected/swapped faces.
- Visual limitations and model artifacts.
