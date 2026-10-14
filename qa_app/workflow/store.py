"""Ticket state on disk (JSON) plus an in-process event bus for live UI updates."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .models import Ticket


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class EventBus:
    """Fan-out of JSON events to every connected Server-Sent Events client. Safe to call from worker threads."""

    def __init__(self) -> None:
        self._subs: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[q] = asyncio.get_running_loop()
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.pop(q, None)

    def _put(self, q: asyncio.Queue, event: dict) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:  # slow client: drop it rather than block the app
            self._subs.pop(q, None)

    def publish(self, event: dict) -> None:
        for q, loop in list(self._subs.items()):
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self._put(q, event)
            elif not loop.is_closed():
                loop.call_soon_threadsafe(self._put, q, event)


bus = EventBus()


class TicketStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.tickets: dict[str, Ticket] = {}
        self.finished: dict[str, int] = {}  # ISO date -> count
        self.done_keys: list[str] = []  # tickets that left the board, so sync won't re-add them
        self.last_sync: float = 0.0
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.tickets = {t["key"]: Ticket(**t) for t in raw.get("tickets", [])}
        self.finished = raw.get("finished", {})
        self.done_keys = raw.get("done_keys", [])
        self.last_sync = raw.get("last_sync", 0.0)

    def save(self) -> None:
        with self._lock:
            _atomic_write(self.path, {
                "tickets": [t.model_dump() for t in self.tickets.values()],
                "finished": self.finished,
                "done_keys": self.done_keys,
                "last_sync": self.last_sync,
            })

    def get(self, key: str) -> Optional[Ticket]:
        return self.tickets.get(key)

    def all(self) -> list[Ticket]:
        return list(self.tickets.values())

    def put(self, t: Ticket) -> Ticket:
        with self._lock:
            t.updated = time.time()
            self.tickets[t.key] = t
            self.save()
        bus.publish({"type": "ticket", "ticket": t.public()})
        return t

    def patch(self, key: str, **fields: Any) -> Ticket:
        with self._lock:
            t = self.tickets[key]
            t = t.model_copy(update=fields)
            return self.put(t)

    def finish(self, key: str) -> None:
        with self._lock:
            self.tickets.pop(key, None)
            today = date.today().isoformat()
            self.finished[today] = self.finished.get(today, 0) + 1
            if key not in self.done_keys:
                self.done_keys.append(key)
            self.save()
        bus.publish({"type": "removed", "key": key, "finished_today": self.finished_today()})

    def finished_today(self) -> int:
        return self.finished.get(date.today().isoformat(), 0)
