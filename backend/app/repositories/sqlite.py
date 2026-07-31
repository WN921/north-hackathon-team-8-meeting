"""SQLite repository implementations for the meeting-room domain.

RFC-0001: Meeting room domain model and rule engine.
The repository layer persists rooms, composite rooms, opening schedules, rules,
bookings, time windows, audit events, idempotency results, and the lightweight
state revision used by local single-process deployments.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Protocol

from app.domain.booking import Booking
from app.domain.common import AuditEvent, BookingStatus, RuleType, TargetType, TimeWindow
from app.domain.composite_room import CompositeRoom
from app.domain.room import Room
from app.domain.rule import RoomRule
from app.domain.rule_engine import MeetingRuleEngine


class MeetingDatabase(Protocol):
    """Protocol accepted by the SQLite repository helpers."""

    row_factory: Any

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> sqlite3.Cursor: ...

    def executemany(self, sql: str, parameters: Iterable[Iterable[Any]]) -> sqlite3.Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def transaction(self): ...


class SQLiteMeetingDomainStore:
    """SQLite-backed store used by the RFC-0001 domain service."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.rooms = SQLiteRoomRepository(db)
        self.composites = SQLiteCompositeRoomRepository(db)
        self.opening_schedules = SQLiteOpeningScheduleRepository(db)
        self.rules = SQLiteRuleRepository(db)
        self.bookings = SQLiteBookingRepository(db)
        self.booking_windows = SQLiteBookingWindowRepository(db)
        self.audits = SQLiteAuditRepository(db)
        self.idempotency_results = SQLiteIdempotencyRepository(db)
        self.state_revision = SQLiteStateRevisionRepository(db)
        self.rule_engine = MeetingRuleEngine(self)

    @contextmanager
    def transaction(self):
        """Run repository writes inside one SQLite transaction."""

        try:
            yield
        except Exception:
            self.db.rollback()
            raise
        else:
            self.db.commit()


class SQLiteRoomRepository:
    """SQLite-backed room repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def get(self, room_id: str) -> Room | None:
        row = self.db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        return _room_from_row(row) if row else None

    def list(self) -> list[Room]:
        return [
            row
            for row in (self.db.execute("SELECT * FROM rooms ORDER BY id").fetchall())
            if (room := _room_from_row(row)) is not None
        ]

    def save(self, room: Room) -> Room:
        self.db.execute(
            """
            INSERT INTO rooms (
                id, name, type, capacity, location, equipment, position, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                capacity = excluded.capacity,
                location = excluded.location,
                equipment = excluded.equipment,
                position = excluded.position,
                active = excluded.active,
                updated_at = excluded.updated_at
            """,
            (
                room.id,
                room.name,
                room.type,
                room.capacity,
                room.location,
                json.dumps(room.equipment, ensure_ascii=False),
                json.dumps(room.position, ensure_ascii=False) if room.position else None,
                int(room.active),
                _iso(room.created_at),
                _iso(room.updated_at),
            ),
        )
        return room

    def delete(self, room_id: str) -> None:
        self.db.execute("DELETE FROM rooms WHERE id = ?", (room_id,))


class SQLiteCompositeRoomRepository:
    """SQLite-backed composite-room repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def get(self, composite_id: str) -> CompositeRoom | None:
        row = self.db.execute("SELECT * FROM composite_rooms WHERE id = ?", (composite_id,)).fetchone()
        if row is None:
            return None
        return self._hydrate_composite(row)

    def list(self) -> list[CompositeRoom]:
        return [self._hydrate_composite(row) for row in self.db.execute("SELECT * FROM composite_rooms ORDER BY id").fetchall()]

    def save(self, composite_room: CompositeRoom) -> CompositeRoom:
        self.db.execute(
            """
            INSERT INTO composite_rooms (
                id, name, capacity, equipment, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                capacity = excluded.capacity,
                equipment = excluded.equipment,
                active = excluded.active,
                updated_at = excluded.updated_at
            """,
            (
                composite_room.id,
                composite_room.name,
                composite_room.capacity,
                json.dumps(composite_room.equipment, ensure_ascii=False),
                int(composite_room.active),
                _iso(composite_room.created_at),
                _iso(composite_room.updated_at),
            ),
        )
        self.db.execute("DELETE FROM composite_room_members WHERE composite_id = ?", (composite_room.id,))
        self.db.executemany(
            "INSERT INTO composite_room_members (composite_id, room_id, sort_order) VALUES (?, ?, ?)",
            [(composite_room.id, member_id, index) for index, member_id in enumerate(composite_room.member_room_ids)],
        )
        return composite_room

    def delete(self, composite_id: str) -> None:
        self.db.execute("DELETE FROM composite_room_members WHERE composite_id = ?", (composite_id,))
        self.db.execute("DELETE FROM composite_rooms WHERE id = ?", (composite_id,))

    def _hydrate_composite(self, row: sqlite3.Row) -> CompositeRoom:
        members = [
            member["room_id"]
            for member in self.db.execute(
                "SELECT room_id FROM composite_room_members WHERE composite_id = ? ORDER BY sort_order",
                (row["id"],),
            ).fetchall()
        ]
        return CompositeRoom(
            id=row["id"],
            name=row["name"],
            member_room_ids=members,
            capacity=int(row["capacity"]),
            equipment=json.loads(row["equipment"] or "[]"),
            active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )


class SQLiteOpeningScheduleRepository:
    """SQLite-backed opening-schedule repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def list_for_room(self, room_id: str) -> list[object]:
        from app.domain.common import OpeningSchedule

        return [
            OpeningSchedule(row["room_id"], row["weekday"], _parse_time(row["start_time"]), _parse_time(row["end_time"]))
            for row in self.db.execute(
                "SELECT * FROM opening_schedules WHERE room_id = ? ORDER BY weekday, start_time",
                (room_id,),
            ).fetchall()
        ]

    def save(self, schedule: object) -> object:
        from app.domain.common import OpeningSchedule

        if not isinstance(schedule, OpeningSchedule):
            raise TypeError("SQLiteOpeningScheduleRepository only accepts OpeningSchedule")
        self.db.execute(
            """
            INSERT INTO opening_schedules (room_id, weekday, start_time, end_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(room_id, weekday, start_time, end_time) DO UPDATE SET
                start_time = excluded.start_time,
                end_time = excluded.end_time
            """,
            (schedule.room_id, schedule.weekday, schedule.start_time.isoformat(), schedule.end_time.isoformat()),
        )
        return schedule

    def clear_for_room(self, room_id: str) -> None:
        self.db.execute("DELETE FROM opening_schedules WHERE room_id = ?", (room_id,))


class SQLiteRuleRepository:
    """SQLite-backed room-rule repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def get(self, rule_id: str) -> RoomRule | None:
        row = self.db.execute("SELECT * FROM room_rules WHERE id = ?", (rule_id,)).fetchone()
        return _rule_from_row(row, self.list_windows(rule_id)) if row else None

    def list_for_target(
        self,
        target_type: TargetType,
        target_id: str,
        *,
        include_protected: bool = True,
    ) -> list[RoomRule]:
        target_type_value = target_type.value if isinstance(target_type, TargetType) else target_type
        rows = self.db.execute(
            """
            SELECT * FROM room_rules
            WHERE target_type = ? AND target_id = ? AND (? = 1 OR protected = 0)
            ORDER BY created_at, id
            """,
            (target_type_value, target_id, int(include_protected)),
        ).fetchall()
        return [self._hydrate_rule(row) for row in rows]

    def list_all(self, *, include_protected: bool = True) -> list[RoomRule]:
        rows = self.db.execute(
            "SELECT * FROM room_rules WHERE (? = 1 OR protected = 0) ORDER BY created_at, id",
            (int(include_protected),),
        ).fetchall()
        return [self._hydrate_rule(row) for row in rows]

    def save(self, rule: RoomRule) -> RoomRule:
        self.db.execute(
            """
            INSERT INTO room_rules (
                id, target_type, target_id, rule_type, match_key, reason, actor_id, protected,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                target_type = excluded.target_type,
                target_id = excluded.target_id,
                rule_type = excluded.rule_type,
                match_key = excluded.match_key,
                reason = excluded.reason,
                actor_id = excluded.actor_id,
                protected = excluded.protected,
                updated_at = excluded.updated_at
            """,
            (
                rule.id,
                rule.target_type.value if isinstance(rule.target_type, TargetType) else rule.target_type,
                rule.target_id,
                rule.rule_type.value if isinstance(rule.rule_type, RuleType) else rule.rule_type,
                rule.match_key,
                rule.reason,
                rule.actor_id,
                int(rule.protected),
                _iso(rule.created_at),
                _iso(rule.updated_at),
            ),
        )
        self.db.execute("DELETE FROM rule_time_windows WHERE rule_id = ?", (rule.id,))
        self.db.executemany(
            """
            INSERT INTO rule_time_windows (
                rule_id, start_at, end_at, recurrence_weekdays, recurrence_start_time,
                recurrence_end_time, recurrence_end_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [_window_row(rule.id, window) for window in rule.time_windows],
        )
        return rule

    def delete(self, rule_id: str) -> None:
        self.db.execute("DELETE FROM rule_time_windows WHERE rule_id = ?", (rule_id,))
        self.db.execute("DELETE FROM room_rules WHERE id = ?", (rule_id,))

    def list_windows(self, rule_id: str) -> list[object]:
        from app.domain.common import Recurrence, RuleTimeWindow

        windows: list[RuleTimeWindow] = []
        for row in self.db.execute(
            """
            SELECT * FROM rule_time_windows
            WHERE rule_id = ?
            ORDER BY start_at, end_at, recurrence_weekdays
            """,
            (rule_id,),
        ).fetchall():
            recurrence = None
            if row["recurrence_weekdays"]:
                recurrence = Recurrence(
                    weekdays=tuple(int(day) for day in row["recurrence_weekdays"].split(",")),
                    start_time=_parse_time(row["recurrence_start_time"]),
                    end_time=_parse_time(row["recurrence_end_time"]),
                    end_date=datetime.fromisoformat(row["recurrence_end_date"]).date() if row["recurrence_end_date"] else None,
                )
            windows.append(
                RuleTimeWindow(
                    start_at=datetime.fromisoformat(row["start_at"]) if row["start_at"] else None,
                    end_at=datetime.fromisoformat(row["end_at"]) if row["end_at"] else None,
                    recurrence=recurrence,
                )
            )
        return windows

    def _hydrate_rule(self, row: sqlite3.Row) -> RoomRule:
        return _rule_from_row(row, self.list_windows(row["id"]))


class SQLiteBookingRepository:
    """SQLite-backed booking repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def get(self, booking_id: str) -> Booking | None:
        row = self.db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return _booking_from_row(row) if row else None

    def list_active(self) -> list[Booking]:
        return [
            booking
            for row in self.db.execute("SELECT * FROM bookings WHERE status = ? ORDER BY created_at, id", (BookingStatus.CONFIRMED.value,)).fetchall()
            if (booking := _booking_from_row(row)) is not None
        ]

    def list(self) -> list[Booking]:
        return [
            booking
            for row in self.db.execute("SELECT * FROM bookings ORDER BY created_at, id").fetchall()
            if (booking := _booking_from_row(row)) is not None
        ]

    def list_for_target(self, target_type: TargetType, target_id: str) -> list[Booking]:
        target_type_value = target_type.value if isinstance(target_type, TargetType) else target_type
        return [
            booking
            for row in self.db.execute(
                """
                SELECT * FROM bookings
                WHERE status = ? AND target_type = ? AND target_id = ?
                ORDER BY created_at, id
                """,
                (BookingStatus.CONFIRMED.value, target_type_value, target_id),
            ).fetchall()
            if (booking := _booking_from_row(row)) is not None
        ]

    def save(self, booking: Booking) -> Booking:
        self.db.execute(
            """
            INSERT INTO bookings (
                id, target_type, target_id, title, actor_id, organizer_id, attendees, description,
                status, idempotency_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                target_type = excluded.target_type,
                target_id = excluded.target_id,
                title = excluded.title,
                actor_id = excluded.actor_id,
                organizer_id = excluded.organizer_id,
                attendees = excluded.attendees,
                description = excluded.description,
                status = excluded.status,
                idempotency_key = excluded.idempotency_key,
                updated_at = excluded.updated_at
            """,
            (
                booking.id,
                booking.target_type.value if isinstance(booking.target_type, TargetType) else booking.target_type,
                booking.target_id,
                booking.title,
                booking.actor_id,
                booking.organizer_id,
                json.dumps(booking.attendees, ensure_ascii=False),
                booking.description,
                booking.status.value if isinstance(booking.status, BookingStatus) else booking.status,
                booking.idempotency_key,
                _iso(booking.created_at),
                _iso(booking.updated_at),
            ),
        )
        return booking

    def delete(self, booking_id: str) -> None:
        self.db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))


class SQLiteBookingWindowRepository:
    """SQLite-backed booking-window repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def list_for_booking(self, booking_id: str) -> list[object]:
        return [
            TimeWindow(datetime.fromisoformat(row["start_at"]), datetime.fromisoformat(row["end_at"]))
            for row in self.db.execute(
                "SELECT start_at, end_at FROM booking_time_windows WHERE booking_id = ? ORDER BY start_at",
                (booking_id,),
            ).fetchall()
        ]

    def save(self, booking_id: str, window: object) -> object:
        if not isinstance(window, TimeWindow):
            raise TypeError("SQLiteBookingWindowRepository only accepts TimeWindow")
        self.db.execute(
            """
            INSERT INTO booking_time_windows (booking_id, start_at, end_at)
            VALUES (?, ?, ?)
            ON CONFLICT(booking_id, start_at, end_at) DO NOTHING
            """,
            (booking_id, window.start_at.isoformat(), window.end_at.isoformat()),
        )
        return window

    def clear(self, booking_id: str) -> None:
        self.db.execute("DELETE FROM booking_time_windows WHERE booking_id = ?", (booking_id,))


class SQLiteAuditRepository:
    """SQLite-backed audit repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def save(self, event: AuditEvent) -> AuditEvent:
        target_type = event.target_type.value if event.target_type else None
        self.db.execute(
            """
            INSERT INTO audit_events (id, event_type, actor_id, target_type, target_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET details = excluded.details
            """,
            (
                event.id,
                event.event_type,
                event.actor_id,
                target_type,
                event.target_id,
                json.dumps(event.details, ensure_ascii=False),
                event.created_at.isoformat(),
            ),
        )
        return event

    def list(self) -> list[AuditEvent]:
        return [
            AuditEvent(
                id=row["id"],
                event_type=row["event_type"],
                actor_id=row["actor_id"],
                target_type=TargetType(row["target_type"]) if row["target_type"] else None,
                target_id=row["target_id"],
                details=json.loads(row["details"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in self.db.execute("SELECT * FROM audit_events ORDER BY created_at, id").fetchall()
        ]


class SQLiteIdempotencyRepository:
    """SQLite-backed idempotency-result repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT response_body FROM idempotency_results WHERE idempotency_key = ?", (key,)).fetchone()
        return json.loads(row["response_body"]) if row else None

    def save(self, key: str, operation: str, state_revision: int, response_body: dict[str, Any], now: datetime) -> None:
        self.db.execute(
            """
            INSERT INTO idempotency_results (
                idempotency_key, operation, state_revision, response_body, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                operation = excluded.operation,
                state_revision = excluded.state_revision,
                response_body = excluded.response_body,
                updated_at = excluded.updated_at
            """,
            (
                key,
                operation,
                state_revision,
                json.dumps(response_body, ensure_ascii=False),
                now.isoformat(),
                now.isoformat(),
            ),
        )


class SQLiteStateRevisionRepository:
    """SQLite-backed state revision repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def current(self) -> int:
        row = self.db.execute("SELECT revision FROM state_revision ORDER BY id DESC LIMIT 1").fetchone()
        return int(row["revision"]) if row else 0

    def increment(self) -> int:
        current = self.current()
        revision = current + 1
        self.db.execute("INSERT INTO state_revision (revision) VALUES (?)", (revision,))
        return revision


def init_sqlite_schema(db: sqlite3.Connection) -> None:
    """Create the SQLite schema used by RFC-0001 domain repositories."""

    db.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            location TEXT NOT NULL,
            equipment TEXT NOT NULL DEFAULT '[]',
            position TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS composite_rooms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            equipment TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS composite_room_members (
            composite_id TEXT NOT NULL,
            room_id TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            PRIMARY KEY (composite_id, room_id),
            FOREIGN KEY (composite_id) REFERENCES composite_rooms(id) ON DELETE CASCADE,
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS opening_schedules (
            room_id TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            PRIMARY KEY (room_id, weekday, start_time, end_time),
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS room_rules (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            match_key TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            protected INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS rule_time_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT NOT NULL,
            start_at TEXT,
            end_at TEXT,
            recurrence_weekdays TEXT,
            recurrence_start_time TEXT,
            recurrence_end_time TEXT,
            recurrence_end_date TEXT,
            FOREIGN KEY (rule_id) REFERENCES room_rules(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            title TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            organizer_id TEXT NOT NULL,
            attendees TEXT NOT NULL DEFAULT '[]',
            description TEXT,
            status TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(idempotency_key)
        );

        CREATE TABLE IF NOT EXISTS booking_time_windows (
            booking_id TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            PRIMARY KEY (booking_id, start_at, end_at),
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS idempotency_results (
            idempotency_key TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            state_revision INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS state_revision (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_room_rules_target ON room_rules(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_bookings_status_target ON bookings(status, target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_booking_time_windows ON booking_time_windows(start_at, end_at);
        CREATE INDEX IF NOT EXISTS idx_rule_time_windows ON rule_time_windows(start_at, end_at);
        """
    )
    db.row_factory = sqlite3.Row
    db.execute("INSERT OR IGNORE INTO state_revision (revision) VALUES (0)")


def connect_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open an RFC-0001 SQLite database and initialize its schema."""

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    init_sqlite_schema(db)
    db.commit()
    return db


def _room_from_row(row: sqlite3.Row | dict[str, Any]) -> Room:
    return Room(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        capacity=int(row["capacity"]),
        location=row["location"],
        equipment=json.loads(row["equipment"] or "[]"),
        position=json.loads(row["position"]) if row["position"] else None,
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def _rule_from_row(row: sqlite3.Row | dict[str, Any], windows: list[object]) -> RoomRule:
    return RoomRule(
        id=row["id"],
        target_type=TargetType(row["target_type"]),
        target_id=row["target_id"],
        rule_type=RuleType(row["rule_type"]),
        match_key=row["match_key"],
        reason=row["reason"],
        actor_id=row["actor_id"],
        protected=bool(row["protected"]),
        time_windows=list(windows),
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def _booking_from_row(row: sqlite3.Row | dict[str, Any]) -> Booking:
    return Booking(
        id=row["id"],
        target_type=TargetType(row["target_type"]),
        target_id=row["target_id"],
        title=row["title"],
        actor_id=row["actor_id"],
        organizer_id=row["organizer_id"],
        attendees=json.loads(row["attendees"] or "[]"),
        description=row["description"],
        status=BookingStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _window_row(rule_id: str, window: object) -> tuple[Any, ...]:
    from app.domain.common import Recurrence, RuleTimeWindow

    if not isinstance(window, RuleTimeWindow):
        raise TypeError("rule time windows must be RuleTimeWindow instances")
    recurrence = window.recurrence
    return (
        rule_id,
        _iso(window.start_at) if window.start_at else None,
        _iso(window.end_at) if window.end_at else None,
        ",".join(str(day) for day in recurrence.weekdays) if recurrence else None,
        recurrence.start_time.isoformat() if recurrence else None,
        recurrence.end_time.isoformat() if recurrence else None,
        recurrence.end_date.isoformat() if recurrence and recurrence.end_date else None,
    )
