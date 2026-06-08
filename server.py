#!/usr/bin/env python3
"""
Local schedule board server.

Runs with Python's standard library only:
    python server.py --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import uuid
from datetime import date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
DATA_DIR = ROOT_DIR / "data"
DATA_FILE = DATA_DIR / "schedules.json"
DATA_LOCK = threading.Lock()

ACTION_WORDS = (
    "예약해줘",
    "예약해",
    "추가해줘",
    "추가해",
    "등록해줘",
    "등록해",
    "잡아줘",
    "잡아",
    "넣어줘",
    "넣어",
    "일정",
    "예약",
)
WEEKDAYS = {
    "월": 0,
    "월요일": 0,
    "화": 1,
    "화요일": 1,
    "수": 2,
    "수요일": 2,
    "목": 3,
    "목요일": 3,
    "금": 4,
    "금요일": 4,
    "토": 5,
    "토요일": 5,
    "일": 6,
    "일요일": 6,
}


def ensure_data_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text("[]\n", encoding="utf-8")


def read_schedules() -> list[dict[str, Any]]:
    ensure_data_file()
    with DATA_LOCK:
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    return []


def write_schedules(items: list[dict[str, Any]]) -> None:
    ensure_data_file()
    with DATA_LOCK:
        tmp_file = DATA_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_file, DATA_FILE)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def normalize_schedule(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    title = str(payload.get("title", existing.get("title", ""))).strip()
    if not title:
        raise ValueError("title is required")

    raw_date = str(payload.get("date", existing.get("date", date.today().isoformat()))).strip()
    raw_time = str(payload.get("time", existing.get("time", ""))).strip()
    parsed_date = date.fromisoformat(raw_date).isoformat()
    parsed_time = ""
    if raw_time:
        parsed_time = time.fromisoformat(raw_time).strftime("%H:%M")

    return {
        "id": str(existing.get("id") or payload.get("id") or uuid.uuid4()),
        "title": title,
        "date": parsed_date,
        "time": parsed_time,
        "notes": str(payload.get("notes", existing.get("notes", ""))).strip(),
        "done": bool(payload.get("done", existing.get("done", False))),
        "source": str(payload.get("source", existing.get("source", "web"))).strip() or "web",
        "created_at": str(existing.get("created_at") or now_iso()),
        "updated_at": now_iso(),
    }


def parse_korean_date(text: str, today: date) -> tuple[date, str]:
    compact = re.sub(r"\s+", "", text)
    if "모레" in compact:
        return today + timedelta(days=2), "모레"
    if "내일" in compact:
        return today + timedelta(days=1), "내일"
    if "오늘" in compact:
        return today, "오늘"

    match = re.search(r"(?:(다음|이번)\s*주\s*)?(월요일|화요일|수요일|목요일|금요일|토요일|일요일|월|화|수|목|금|토|일)", text)
    if match:
        prefix = match.group(1) or ""
        weekday_word = match.group(2)
        target = WEEKDAYS[weekday_word]
        days = (target - today.weekday()) % 7
        if prefix == "다음":
            days += 7 if days == 0 else 0
        elif prefix == "":
            days = 7 if days == 0 else days
        return today + timedelta(days=days), match.group(0)

    explicit = re.search(r"(\d{4})[년\-. ]+(\d{1,2})[월\-. ]+(\d{1,2})일?", text)
    if explicit:
        return date(int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3))), explicit.group(0)

    month_day = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일?", text)
    if month_day:
        year = today.year
        parsed = date(year, int(month_day.group(1)), int(month_day.group(2)))
        if parsed < today:
            parsed = date(year + 1, parsed.month, parsed.day)
        return parsed, month_day.group(0)

    return today, ""


def parse_korean_time(text: str) -> tuple[str, str]:
    match = re.search(
        r"(오전|오후|아침|저녁|밤)?\s*(\d{1,2})\s*시(?:\s*(반|(\d{1,2})\s*분?))?",
        text,
    )
    if not match:
        return "", ""

    meridiem = match.group(1) or ""
    hour = int(match.group(2))
    minute = 30 if match.group(3) == "반" else int(match.group(4) or 0)

    if meridiem in ("오후", "저녁", "밤") and hour < 12:
        hour += 12
    elif meridiem in ("오전", "아침") and hour == 12:
        hour = 0
    elif not meridiem and 1 <= hour <= 6:
        hour += 12

    if hour > 23 or minute > 59:
        raise ValueError("invalid time")
    return f"{hour:02d}:{minute:02d}", match.group(0)


def clean_title(text: str, consumed: list[str]) -> str:
    title = text
    for piece in consumed:
        if piece:
            title = title.replace(piece, " ")
    for word in ACTION_WORDS:
        title = title.replace(word, " ")
    title = re.sub(r"\b에\b|에서|으로|로", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" .,!?")
    return title or "일정"


def parse_voice_command(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("text is required")

    today = date.today()
    schedule_date, date_token = parse_korean_date(text, today)
    schedule_time, time_token = parse_korean_time(text)
    title = clean_title(text, [date_token, time_token])

    return {
        "title": title,
        "date": schedule_date.isoformat(),
        "time": schedule_time,
        "notes": "",
        "source": "voice",
        "done": False,
    }


def filtered_schedules(range_name: str) -> list[dict[str, Any]]:
    items = sorted(read_schedules(), key=lambda item: (item.get("date", ""), item.get("time", ""), item.get("title", "")))
    today = date.today()
    if range_name == "today":
        return [item for item in items if item.get("date") == today.isoformat()]
    if range_name == "week":
        week_end = today + timedelta(days=6)
        return [
            item
            for item in items
            if today.isoformat() <= str(item.get("date", "")) <= week_end.isoformat()
        ]
    return items


class ScheduleHandler(BaseHTTPRequestHandler):
    server_version = "ScheduleBoard/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_static("index.html")
            return
        if parsed.path.startswith("/static/"):
            self.serve_static(parsed.path.removeprefix("/static/"))
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "time": now_iso()})
            return
        if parsed.path == "/api/schedules":
            params = parse_qs(parsed.query)
            range_name = params.get("range", ["all"])[0]
            self.send_json({"items": filtered_schedules(range_name)})
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/schedules":
                payload = self.read_json_body()
                self.create_schedule(payload)
                return
            if parsed.path == "/api/voice-command":
                payload = self.read_json_body()
                parsed_schedule = parse_voice_command(str(payload.get("text", "")))
                self.create_schedule(parsed_schedule, extra={"parsed": parsed_schedule})
                return
            self.send_error(404, "Not found")
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, status=400)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/schedules/"):
            self.send_error(404, "Not found")
            return
        schedule_id = parsed.path.removeprefix("/api/schedules/").strip("/")
        if not schedule_id:
            self.send_error(404, "Not found")
            return
        try:
            payload = self.read_json_body()
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        items = read_schedules()
        for idx, item in enumerate(items):
            if item.get("id") == schedule_id:
                try:
                    updated = normalize_schedule(payload, existing=item)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                items[idx] = updated
                write_schedules(items)
                self.send_json({"item": updated})
                return
        self.send_error(404, "Schedule not found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/schedules/"):
            self.send_error(404, "Not found")
            return
        schedule_id = parsed.path.removeprefix("/api/schedules/").strip("/")
        if not schedule_id:
            self.send_error(404, "Not found")
            return
        items = read_schedules()
        remaining = [item for item in items if item.get("id") != schedule_id]
        if len(remaining) == len(items):
            self.send_error(404, "Schedule not found")
            return
        write_schedules(remaining)
        self.send_json({"ok": True})

    def create_schedule(self, payload: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
        try:
            item = normalize_schedule(payload)
            items = read_schedules()
            items.append(item)
            write_schedules(items)
            response = {"item": item}
            if extra:
                response.update(extra)
            self.send_json(response, status=201)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, relative_path: str) -> None:
        requested = (STATIC_DIR / relative_path).resolve()
        if not str(requested).startswith(str(STATIC_DIR.resolve())) or not requested.exists():
            self.send_error(404, "Not found")
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        data = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(requested.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local schedule board.")
    parser.add_argument("--host", default=os.environ.get("SCHEDULE_BOARD_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SCHEDULE_BOARD_PORT", "8080")))
    args = parser.parse_args()

    ensure_data_file()
    server = ThreadingHTTPServer((args.host, args.port), ScheduleHandler)
    print(f"Schedule board running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping schedule board.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
