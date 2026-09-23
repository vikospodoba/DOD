# Java to Python Contract

## Health

`GET /health`

Response:

```json
{
  "status": "ok",
  "ready": true,
  "fps": 25.0,
  "inferenceMs": 18.4,
  "gpuMemoryUsedMb": 12000
}
```

## Readiness

`GET /ready`

Response:

```json
{
  "ready": true
}
```

## Prepare Character

`POST /v1/prepare-character`

Request:

```json
{
  "characterId": "default-human"
}
```

Response:

```json
{
  "status": "ok",
  "ready": true,
  "characterId": "default-human",
  "selectedCharacterId": "default-human"
}
```

The worker validates that the character exists and, in ML mode, can prepare reusable character state before frame processing.

## Select Character

`POST /v1/select-character`

Request:

```json
{
  "characterId": "default-human"
}
```

Response:

```json
{
  "status": "ok",
  "ready": true,
  "characterId": "default-human",
  "selectedCharacterId": "default-human"
}
```

## Process Frame

Java keeps a persistent TCP connection to the worker frame stream port, `8002` by default.
Each request and response is a length-prefixed binary message:

1. 4-byte unsigned big-endian message length.
2. 4-byte unsigned big-endian JSON header length.
3. UTF-8 JSON metadata.
4. JPEG frame bytes.

Java request metadata:

```json
{
  "characterId": "default-human",
  "manyFaces": true,
  "sequence": 42,
  "capturedAtEpochMs": 1783939200000
}
```

Worker response metadata:

```json
{
  "status": "ok",
  "characterId": "default-human",
  "sequence": 42,
  "capturedAtEpochMs": 1783939200000,
  "inferenceMs": 18
}
```

Worker statuses:

- `ok`
- `no_face`
- `model_not_ready`
- `invalid_character`
- `processing_error`

## Browser WebSocket Frame

Endpoint: `/ws/video`

Each binary message is:

1. 4-byte unsigned big-endian JSON header length.
2. UTF-8 JSON metadata.
3. JPEG frame bytes.

Browser to Java metadata:

```json
{
  "characterId": "default-human",
  "manyFaces": true,
  "sequence": 42,
  "capturedAtEpochMs": 1783939200000
}
```

Java to browser metadata:

```json
{
  "status": "ok",
  "characterId": "default-human",
  "sequence": 42,
  "capturedAtEpochMs": 1783939200000,
  "serverReceivedAtEpochMs": 1783939200020,
  "serverSentAtEpochMs": 1783939200040,
  "inferenceMs": 18
}
```
