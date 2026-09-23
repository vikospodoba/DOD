# Showroom Deployment

This is the production-style path for the showroom server. It runs the browser UI, Java service, reverse proxy, and real Deep-Live-Cam worker as long-lived Docker services.

## Server prerequisites

- Linux server with an NVIDIA GPU.
- Current NVIDIA driver.
- Docker Engine with Docker Compose v2.
- NVIDIA Container Toolkit configured so `docker run --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` works.
- Trusted TLS certificate for the showroom hostname.

## Files expected on the server

```text
characters/
experiments/Deep-Live-Cam/models/
deploy/showroom.env
deploy/certs/fullchain.pem
deploy/certs/privkey.pem
```

The required Deep-Live-Cam model is one of:

```text
experiments/Deep-Live-Cam/models/inswapper_128_fp16.onnx
experiments/Deep-Live-Cam/models/inswapper_128.onnx
```

## First setup

```bash
cp deploy/showroom.env.example deploy/showroom.env
mkdir -p deploy/certs deploy/cache logs/java logs/worker
```

Edit `deploy/showroom.env` and set `SHOWROOM_HOST` to the DNS name used by the touch-screen browser.

Put the trusted certificate files into:

```text
deploy/certs/fullchain.pem
deploy/certs/privkey.pem
```

Start the service:

```bash
docker compose --env-file deploy/showroom.env -f docker-compose.showroom.yml up -d --build
```

Open:

```text
https://<SHOWROOM_HOST>
```

## Autostart with systemd

Copy the project to `/opt/dod-deep-live-cam`, then install the unit:

```bash
sudo cp deploy/dod-showroom.service /etc/systemd/system/dod-showroom.service
sudo systemctl daemon-reload
sudo systemctl enable --now dod-showroom.service
```

Useful commands:

```bash
sudo systemctl status dod-showroom.service
docker compose --env-file deploy/showroom.env -f docker-compose.showroom.yml ps
docker compose --env-file deploy/showroom.env -f docker-compose.showroom.yml logs -f inference-worker
docker compose --env-file deploy/showroom.env -f docker-compose.showroom.yml logs -f java-service
```

## Health checks

The worker container is considered healthy only when `/health` returns `ready: true`, meaning the model is loaded. The Java service starts after that and exposes `/actuator/health` through the internal container network.

The Python worker is not published to the local network. Only the HTTPS reverse proxy is exposed.
