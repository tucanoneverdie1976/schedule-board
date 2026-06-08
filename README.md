# Local Schedule Board

Porcupine voice assistant can write schedules here later, while this app serves a local web board.

## Run

```bash
python server.py --host 0.0.0.0 --port 8080
```

Open this from another device on the same network:

```text
http://192.168.68.66:8080
```

## API

Create a schedule:

```bash
curl -X POST http://localhost:8080/api/schedules \
  -H "Content-Type: application/json" \
  -d '{"title":"병원","date":"2026-06-08","time":"15:00","source":"voice"}'
```

Create from a Korean command sentence:

```bash
curl -X POST http://localhost:8080/api/voice-command \
  -H "Content-Type: application/json" \
  -d '{"text":"오늘 3시 병원 예약해"}'
```

List schedules:

```bash
curl http://localhost:8080/api/schedules?range=today
curl http://localhost:8080/api/schedules?range=week
curl http://localhost:8080/api/schedules?range=all
```
