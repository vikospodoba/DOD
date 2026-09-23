# DOD Deep Live Cam Prototype

Standalone copy of the DOD real-time face replacement prototype using Deep Live Cam as the local Python inference backend.

Runtime path:

```text
Camera -> Browser JPEG frame -> Java WebSocket -> Python Deep Live Cam worker -> Processed JPEG frame -> Browser
```

## Run Locally

This mode is for development on one machine.

1. Prepare the Deep Live Cam Python environment once:

```powershell
.\setup-deep-live-cam-env.ps1
```

2. Start the Deep Live Cam worker:

```powershell
.\run-deep-live-cam-worker.ps1
```

3. In another terminal, start Java:

```powershell
.\mvnw.cmd spring-boot:run
```

4. Open:

```text
http://localhost:8080
```

Localhost is accepted by modern browsers as a secure context for camera access. For access from another computer, use HTTPS with a trusted internal certificate.

## Run in Showroom Mode

Use this mode on the demo server. It runs the Java service, real Deep-Live-Cam worker, and HTTPS reverse proxy as Docker services with automatic restarts.

1. Prepare config and folders:

```bash
cp deploy/showroom.env.example deploy/showroom.env
mkdir -p deploy/certs deploy/cache logs/java logs/worker
```

2. Edit `deploy/showroom.env` and set `SHOWROOM_HOST` to the hostname opened on the touch-screen computer.

3. Put trusted TLS certificate files into:

```text
deploy/certs/fullchain.pem
deploy/certs/privkey.pem
```

4. Start:

```bash
docker compose --env-file deploy/showroom.env -f docker-compose.showroom.yml up -d --build
```

Open:

```text
https://<SHOWROOM_HOST>
```

For boot-time autostart, install `deploy/dod-showroom.service` as described in `docs/showroom-deployment.md`.

## Included Deep Live Cam Assets

This copy keeps Deep Live Cam under:

```text
experiments/Deep-Live-Cam/
```

The copied model directory is:

```text
experiments/Deep-Live-Cam/models/
  GFPGANv1.4.onnx
  inswapper_128.onnx
  inswapper_128_fp16.onnx
```

The runtime only requires one of:

```text
inswapper_128_fp16.onnx
inswapper_128.onnx
```

## Source Faces

Source faces are defined in:

```text
characters/manifest.json
```

Each entry has:

- `id`
- `name`
- `type`
- `imageUrl`

Every source face should also exist as an image file named by id, for example:

```text
characters/default-human.jpg
```

The selected source face id is saved in browser `localStorage` and is sent with every frame as `characterId`.

Use source faces only when you have the right to use the person's likeness and label generated output appropriately outside the demo.

## Worker API

The Java service talks to the worker through the existing contract:

- `GET /health`
- `GET /ready`
- `POST /v1/prepare-character`
- `POST /v1/select-character`
- persistent binary frame stream on port `8002`

See `docs/java-python-contract.md` for request and response details.

## Docker Compose Smoke Test

Docker Compose is left as a transport/smoke-test path. The Compose worker can run in `stub` mode without GPU-specific Deep Live Cam dependencies:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8082
```

For the actual Deep Live Cam backend as a long-running service, use Showroom Mode.

## Worker Quality Tuning

The Deep Live Cam worker exposes quality options through environment variables so the showroom run can compare visual quality and FPS without rebuilding images.

Default performance profile:

```text
DOD_POISSON_BLEND=false
DOD_COLOR_CORRECTION=false
DOD_MOUTH_MASK_SIZE=0
DOD_SHARPNESS=0
DOD_OPACITY=1.0
DOD_FACE_ENHANCER=none
```

Experimental quality profile:

```text
DOD_POISSON_BLEND=true
DOD_MOUTH_MASK_SIZE=25
DOD_SHARPNESS=0.2
```

`DOD_FACE_ENHANCER` supports `none`, `gfpgan`, `gpen256`, and `gpen512`. Enhancer modes require the matching ONNX file to already exist in the model directory; the worker will not download it at runtime.

## Documentation

- Java/Python contract: `docs/java-python-contract.md`
- Showroom deployment: `docs/showroom-deployment.md`
- Test protocol: `docs/test-protocol.md`
