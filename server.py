#!/usr/bin/env python3
"""
Local schedule board server.

Runs with Python's standard library only:
    python server.py --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
DATA_DIR = ROOT_DIR / "data"
DATA_FILE = DATA_DIR / "schedules.json"
DATA_LOCK = threading.Lock()
NEWS_FEED_URL = os.environ.get(
    "NEWS_FEED_URL",
    "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
)
NEWS_DISPLAY_LIMIT = int(os.environ.get("NEWS_DISPLAY_LIMIT", "2"))
NEWS_POOL_LIMIT = int(os.environ.get("NEWS_POOL_LIMIT", "20"))
NEWS_CACHE_SECONDS = int(os.environ.get("NEWS_CACHE_SECONDS", "60"))
NEWS_FETCH_TIMEOUT_SECONDS = float(os.environ.get("NEWS_FETCH_TIMEOUT_SECONDS", "8"))
NEWS_LOCK = threading.Lock()
NEWS_CACHE: dict[str, Any] = {"items": [], "fetched_at": 0.0, "updated_at": "", "error": "", "cursor": 0}
MARKET_CACHE_SECONDS = int(os.environ.get("MARKET_CACHE_SECONDS", "60"))
MARKET_FETCH_TIMEOUT_SECONDS = float(os.environ.get("MARKET_FETCH_TIMEOUT_SECONDS", "8"))
NAVER_INDEX_API_URL = os.environ.get(
    "NAVER_INDEX_API_URL",
    "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:KOSPI,KOSDAQ,KPI200",
)
NAVER_MARKET_INDEX_API_URL = os.environ.get(
    "NAVER_MARKET_INDEX_API_URL",
    "https://m.stock.naver.com/front-api/marketIndex/majors",
)
MARKET_LOCK = threading.Lock()
MARKET_CACHE: dict[str, Any] = {"items": [], "fetched_at": 0.0, "updated_at": "", "error": ""}
INDEX_NAMES = {
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
    "KPI200": "KOSPI 200",
}

ADD_ACTION_WORDS = (
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
)
DELETE_ACTION_WORDS = (
    "삭제해줘",
    "삭제해",
    "삭제",
    "지워줘",
    "지워",
    "취소해줘",
    "취소해",
    "취소",
    "빼줘",
    "빼",
)
ACTION_WORDS = (
    *ADD_ACTION_WORDS,
    *DELETE_ACTION_WORDS,
    "일정",
    "예약",
)
FILLER_WORDS = (
    "해주세요",
    "해줘",
    "해",
    "하려고",
    "하려구",
    "하고싶어",
    "하고 싶어",
    "싶어",
    "좀",
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


def parse_news_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed:
            return parsed.astimezone().replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        pass
    return value.strip()


def text_or_empty(parent: ElementTree.Element, child_name: str) -> str:
    found = parent.find(child_name)
    if found is None or found.text is None:
        return ""
    return html.unescape(found.text).strip()


def parse_rss_items(xml_bytes: bytes, limit: int) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_bytes)
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        source = item.find("source")
        source_text = html.unescape(source.text).strip() if source is not None and source.text else ""
        parsed = {
            "title": text_or_empty(item, "title"),
            "link": text_or_empty(item, "link"),
            "source": source_text,
            "published_at": parse_news_date(text_or_empty(item, "pubDate")),
        }
        if parsed["title"] and parsed["link"]:
            items.append(parsed)
        if len(items) >= limit:
            break
    return items


def rotate_news_items(items: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    if not items:
        return [], 0

    limit = max(1, NEWS_DISPLAY_LIMIT)
    with NEWS_LOCK:
        cursor = int(NEWS_CACHE.get("cursor") or 0) % len(items)
        selected = [items[(cursor + offset) % len(items)] for offset in range(min(limit, len(items)))]
        NEWS_CACHE["cursor"] = (cursor + limit) % len(items)
        next_cursor = int(NEWS_CACHE["cursor"])
    return selected, next_cursor


def fetch_news_items() -> dict[str, Any]:
    now_ts = datetime.now().timestamp()
    with NEWS_LOCK:
        cached_age = now_ts - float(NEWS_CACHE.get("fetched_at") or 0)
        cached_items = list(NEWS_CACHE.get("items") or [])
        cached_updated_at = str(NEWS_CACHE.get("updated_at") or "")
        is_cache_fresh = bool(cached_items) and cached_age < NEWS_CACHE_SECONDS
    if is_cache_fresh:
        items, next_cursor = rotate_news_items(cached_items)
        return {
            "items": items,
            "updated_at": cached_updated_at,
            "pool_size": len(cached_items),
            "next_cursor": next_cursor,
            "cached": True,
        }

    req = urllib.request.Request(
        NEWS_FEED_URL,
        headers={"User-Agent": "ScheduleBoard/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=NEWS_FETCH_TIMEOUT_SECONDS) as resp:
            fetched_items = parse_rss_items(resp.read(), max(NEWS_DISPLAY_LIMIT, NEWS_POOL_LIMIT))
        updated_at = now_iso()
        with NEWS_LOCK:
            NEWS_CACHE.update({"items": fetched_items, "fetched_at": now_ts, "updated_at": updated_at, "error": ""})
        items, next_cursor = rotate_news_items(fetched_items)
        return {
            "items": items,
            "updated_at": updated_at,
            "pool_size": len(fetched_items),
            "next_cursor": next_cursor,
            "cached": False,
        }
    except (OSError, urllib.error.URLError, ElementTree.ParseError) as exc:
        with NEWS_LOCK:
            NEWS_CACHE["error"] = str(exc)
            cached_items = list(NEWS_CACHE.get("items") or [])
            cached_updated_at = str(NEWS_CACHE.get("updated_at") or "")
        items, next_cursor = rotate_news_items(cached_items)
        return {
            "items": items,
            "updated_at": cached_updated_at,
            "pool_size": len(cached_items),
            "next_cursor": next_cursor,
            "cached": True,
            "error": str(exc),
        }


def read_json_url(url: str, referer: str = "") -> dict[str, Any]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "ScheduleBoard/1.0 Mozilla/5.0",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=MARKET_FETCH_TIMEOUT_SECONDS) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset, errors="replace"))


def parse_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return 0.0
    return float(text)


def format_decimal(value: float, places: int = 2) -> str:
    return f"{value:,.{places}f}"


def format_signed(value: float, places: int = 2) -> str:
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:,.{places}f}"


def normalize_direction(value: float | None = None, direction_name: str = "") -> str:
    if value is not None:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
    normalized = direction_name.upper()
    if normalized == "RISING":
        return "up"
    if normalized == "FALLING":
        return "down"
    return "flat"


def signed_text(value: Any, direction: str) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return text
    if text.startswith(("+", "-")):
        return text
    if direction == "up":
        return f"+{text}"
    return text


def timestamp_from_millis(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000).astimezone().replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OSError):
        return now_iso()


def fetch_naver_indices() -> list[dict[str, str]]:
    payload = read_json_url(NAVER_INDEX_API_URL, "https://finance.naver.com/sise/")
    result = payload.get("result") or {}
    updated_at = timestamp_from_millis(result.get("time"))
    items: list[dict[str, str]] = []
    for area in result.get("areas") or []:
        if area.get("name") != "SERVICE_INDEX":
            continue
        for raw_item in area.get("datas") or []:
            code = str(raw_item.get("cd") or "").strip()
            if code not in INDEX_NAMES:
                continue
            value = parse_number(raw_item.get("nv")) / 100
            change = parse_number(raw_item.get("cv")) / 100
            change_rate = parse_number(raw_item.get("cr"))
            direction = normalize_direction(change)
            items.append(
                {
                    "category": "index",
                    "code": code,
                    "name": INDEX_NAMES[code],
                    "value": format_decimal(value),
                    "unit": "pt",
                    "change": format_signed(change),
                    "change_rate": format_signed(change_rate),
                    "direction": direction,
                    "status": str(raw_item.get("ms") or ""),
                    "delay": "",
                    "source": "Naver Finance / KRX",
                    "updated_at": updated_at,
                }
            )
    return items


def fetch_naver_domestic_gold() -> list[dict[str, str]]:
    payload = read_json_url(NAVER_MARKET_INDEX_API_URL, "https://m.stock.naver.com/marketindex/home/major")
    result = payload.get("result") or {}
    for raw_item in result.get("metals") or []:
        if raw_item.get("reutersCode") != "M04020000" and raw_item.get("name") != "국내 금":
            continue
        fluct_type = raw_item.get("fluctuationsType") or {}
        change_value = parse_number(raw_item.get("fluctuations"))
        direction = normalize_direction(change_value, str(fluct_type.get("name") or ""))
        return [
            {
                "category": "gold",
                "code": str(raw_item.get("reutersCode") or "M04020000"),
                "name": "국내 금",
                "value": str(raw_item.get("closePrice") or ""),
                "unit": str(raw_item.get("unit") or "원/g"),
                "change": signed_text(raw_item.get("fluctuations"), direction),
                "change_rate": signed_text(raw_item.get("fluctuationsRatio"), direction),
                "direction": direction,
                "status": str(raw_item.get("marketStatus") or ""),
                "delay": str(raw_item.get("delayTimeName") or ""),
                "source": "Naver Stock / 국내 금 M04020000",
                "updated_at": str(raw_item.get("localTradedAt") or now_iso()),
            }
        ]
    return []


def fetch_market_items() -> dict[str, Any]:
    now_ts = datetime.now().timestamp()
    with MARKET_LOCK:
        cached_age = now_ts - float(MARKET_CACHE.get("fetched_at") or 0)
        cached_items = list(MARKET_CACHE.get("items") or [])
        cached_updated_at = str(MARKET_CACHE.get("updated_at") or "")
        cached_error = str(MARKET_CACHE.get("error") or "")
        is_cache_fresh = bool(cached_items) and cached_age < MARKET_CACHE_SECONDS
    if is_cache_fresh:
        return {
            "items": cached_items,
            "updated_at": cached_updated_at,
            "cached": True,
            "error": cached_error,
        }

    items: list[dict[str, str]] = []
    errors: list[str] = []
    for source_name, fetcher in (("indices", fetch_naver_indices), ("gold", fetch_naver_domestic_gold)):
        try:
            items.extend(fetcher())
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{source_name}: {exc}")

    if items:
        updated_at = now_iso()
        error = "; ".join(errors)
        with MARKET_LOCK:
            MARKET_CACHE.update({"items": items, "fetched_at": now_ts, "updated_at": updated_at, "error": error})
        return {"items": items, "updated_at": updated_at, "cached": False, "error": error}

    error = "; ".join(errors) or "market data unavailable"
    with MARKET_LOCK:
        MARKET_CACHE["error"] = error
        cached_items = list(MARKET_CACHE.get("items") or [])
        cached_updated_at = str(MARKET_CACHE.get("updated_at") or "")
    return {"items": cached_items, "updated_at": cached_updated_at, "cached": True, "error": error}


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
    for word in FILLER_WORDS:
        title = title.replace(word, " ")
    title = re.sub(r"\b에\b|에서|으로|로|을|를|은|는", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" .,!?")
    return title or "일정"


def normalize_match_text(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", text).lower()


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


def voice_command_action(text: str) -> str:
    compact = re.sub(r"\s+", "", text.lower())
    add_positions = [compact.rfind(word) for word in ADD_ACTION_WORDS if word in compact]
    delete_positions = [compact.rfind(word) for word in DELETE_ACTION_WORDS if word in compact]
    last_add = max(add_positions, default=-1)
    last_delete = max(delete_positions, default=-1)

    if last_delete > last_add:
        return "delete"
    if last_add >= 0:
        return "add"
    raise ValueError("지원하는 일정 명령이 아닙니다")


def parse_delete_command(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("text is required")

    today = date.today()
    schedule_date, date_token = parse_korean_date(text, today)
    schedule_time, time_token = parse_korean_time(text)
    title = clean_title(text, [date_token, time_token])
    return {
        "title": "" if title == "일정" else title,
        "date": schedule_date.isoformat() if date_token else "",
        "time": schedule_time if time_token else "",
    }


def matches_delete_query(item: dict[str, Any], query: dict[str, Any]) -> bool:
    if query.get("date") and item.get("date") != query["date"]:
        return False
    if query.get("time") and item.get("time") != query["time"]:
        return False

    title = normalize_match_text(str(item.get("title", "")))
    query_title = normalize_match_text(str(query.get("title", "")))
    if not query_title:
        return bool(query.get("date") or query.get("time"))
    return query_title in title or title in query_title


def matches_delete_title(item: dict[str, Any], query: dict[str, Any]) -> bool:
    title = normalize_match_text(str(item.get("title", "")))
    query_title = normalize_match_text(str(query.get("title", "")))
    if not title or not query_title:
        return False
    return query_title in title or title in query_title


def delete_schedules_by_query(query: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items = read_schedules()
    matches = [item for item in items if matches_delete_query(item, query)]
    if len(matches) == 1:
        match_id = matches[0].get("id")
        remaining = [item for item in items if item.get("id") != match_id]
        write_schedules(remaining)
        return matches, matches
    if len(matches) > 1:
        return [], matches

    title_matches = [item for item in items if matches_delete_title(item, query)]
    if len(title_matches) != 1:
        return [], title_matches

    match_id = title_matches[0].get("id")
    remaining = [item for item in items if item.get("id") != match_id]
    write_schedules(remaining)
    return title_matches, title_matches


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
        if parsed.path == "/api/news":
            self.send_json(fetch_news_items())
            return
        if parsed.path == "/api/markets":
            self.send_json(fetch_market_items())
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
                self.execute_voice_command(str(payload.get("text", "")))
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

    def execute_voice_command(self, text: str) -> None:
        action = voice_command_action(text)
        if action == "add":
            parsed_schedule = parse_voice_command(text)
            self.create_schedule(
                parsed_schedule,
                extra={"action": "added", "parsed": parsed_schedule},
            )
            return

        query = parse_delete_command(text)
        deleted, candidates = delete_schedules_by_query(query)
        if len(deleted) == 1:
            self.send_json({"action": "deleted", "deleted": deleted[0], "query": query})
            return
        if candidates:
            self.send_json(
                {
                    "error": "삭제할 일정이 여러 개입니다",
                    "action": "ambiguous_delete",
                    "query": query,
                    "candidates": candidates,
                },
                status=409,
            )
            return
        self.send_json(
            {
                "error": "삭제할 일정을 찾지 못했습니다",
                "action": "not_found_delete",
                "query": query,
            },
            status=404,
        )

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
