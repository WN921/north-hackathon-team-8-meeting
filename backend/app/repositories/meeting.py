"""SQLite-backed repository for the local meeting-room backend. RFC-0002."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.config import DEFAULT_WORKSPACE_ID
from app.domain.models import Booking, CompositeRoom, Position, Room, Rule, TimeWindow

try:
    from app.auth.local import hash_password
except Exception:  # pragma: no cover - import fallback only protects repository-only usage.
    def hash_password(password: str) -> str:
        import hashlib

        return hashlib.sha256(password.encode("utf-8")).hexdigest()

DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "meeting_room.sqlite3"


def _ensure_parent() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    """Open a SQLite connection with row factory enabled."""

    _ensure_parent()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Yield a transactional SQLite session."""

    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _position_from_value(value: str | None) -> Position | None:
    data = _json_loads(value, None)
    if not data:
        return None
    return Position(**data)


def _position_to_value(position: Position | None) -> str | None:
    if position is None:
        return None
    return _json_dumps(position.to_dict())


class MeetingRepository:
    """Small in-process SQLite repository for RFC-0002 API operations."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or connect()
        self._owns_connection = conn is None

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def init_schema(self) -> None:
        """Create the minimal tables required by the API contract."""

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_revision (
                workspace_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member'
            );

            CREATE TABLE IF NOT EXISTS idempotency_keys (
                workspace_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, actor_id, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                location TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                equipment_json TEXT NOT NULL,
                position_json TEXT,
                protected INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS composites (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                member_room_ids_json TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                equipment_json TEXT NOT NULL,
                position_json TEXT,
                protected INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS opening_schedules (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                weekday INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                protected INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                rule_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                time_windows_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                fixed INTEGER NOT NULL DEFAULT 0,
                editable INTEGER NOT NULL DEFAULT 1,
                match_key TEXT,
                created_by TEXT,
                updated_by TEXT
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                title TEXT NOT NULL,
                organizer_id TEXT NOT NULL,
                attendees_json TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def seed_defaults(self) -> None:
        """Seed demo users, rooms, composites, opening schedules and fixed rules."""

        self.conn.execute(
            """
            INSERT OR IGNORE INTO users (id, username, password, name, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("user_001", "demo", hash_password("demo-password"), "演示用户", "member"),
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO users (id, username, password, name, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("user_002", "member", hash_password("demo-password"), "演示成员", "member"),
        )
        self.conn.execute("INSERT OR IGNORE INTO state_revision (workspace_id, revision) VALUES (?, 0)", (DEFAULT_WORKSPACE_ID,))
        rooms = [
            Room("activity-room", "活动室", "activity", "5F", 20, ["projector", "whiteboard"], Position(40, 40, 100, 60), True),
            Room("meeting-room-1", "会议室一", "medium", "5F", 12, ["projector", "whiteboard"], Position(160, 40, 100, 60), True),
            Room("meeting-room-2", "会议室二", "medium", "5F", 12, ["projector", "whiteboard"], Position(280, 40, 100, 60), True),
            Room("503", "503", "small", "5F", 4, ["whiteboard"], Position(40, 120, 80, 50), False),
            Room("504", "504", "small", "5F", 4, ["whiteboard"], Position(140, 120, 80, 50), False),
            Room("505", "505", "small", "5F", 4, ["whiteboard"], Position(240, 120, 80, 50), False),
            Room("506", "506", "small", "5F", 4, ["whiteboard"], Position(340, 120, 80, 50), False),
        ]
        for room in rooms:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO rooms (id, name, type, location, capacity, equipment_json, position_json, protected, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room.id,
                    room.name,
                    room.type,
                    room.location,
                    room.capacity,
                    _json_dumps(room.equipment),
                    _position_to_value(room.position),
                    int(room.protected),
                    int(room.active),
                ),
            )
        composite = CompositeRoom("meeting-room-1-2", "会议室一+会议室二", ["meeting-room-1", "meeting-room-2"], 24, ["projector", "whiteboard"], Position(80, 220, 200, 70))
        self.conn.execute(
            """
            INSERT OR IGNORE INTO composites (id, name, member_room_ids_json, capacity, equipment_json, position_json, protected, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                composite.id,
                composite.name,
                _json_dumps(composite.member_room_ids),
                composite.capacity,
                _json_dumps(composite.equipment),
                _position_to_value(composite.position),
                int(composite.protected),
                int(True),
            ),
        )
        for room_id in ["activity-room", "meeting-room-1", "meeting-room-2", "503", "504", "505", "506"]:
            for weekday in range(5):
                schedule = (room_id, weekday, "09:00", "18:00")
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO opening_schedules (id, room_id, weekday, start_time, end_time, protected)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (f"sch_{room_id}_{weekday}", *schedule, 0),
                )
        rules = [
            Rule(
                "rule_lunch_activity_room",
                "fixed_unavailable",
                "room",
                "activity-room",
                [TimeWindow("12:00", "13:00", "weekly:workday")],
                "活动室午餐固定占用",
                True,
                False,
                "activity-room:lunch:workday",
                "system",
                "system",
            ),
            Rule(
                "rule_505_tuesday",
                "weekly_unavailable",
                "room",
                "505",
                [TimeWindow("00:00", "24:00", "weekly:tuesday")],
                "505 每周二全天不可用",
                True,
                False,
                "505:weekly_unavailable:tuesday",
                "system",
                "system",
            ),
        ]
        for rule in rules:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO rules (id, rule_type, target_type, target_id, time_windows_json, reason, fixed, editable, match_key, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    rule.rule_type,
                    rule.target_type,
                    rule.target_id,
                    _json_dumps([window.to_dict() for window in rule.time_windows]),
                    rule.reason,
                    int(rule.fixed),
                    int(rule.editable),
                    rule.match_key,
                    rule.created_by,
                    rule.updated_by,
                ),
            )

    def get_state_revision(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> int:
        row = self.conn.execute("SELECT revision FROM state_revision WHERE workspace_id = ?", (workspace_id,)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO state_revision (workspace_id, revision) VALUES (?, 0)", (workspace_id,))
            self.conn.commit()
            return 0
        return int(row["revision"])

    def increment_state_revision(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> int:
        revision = self.get_state_revision(workspace_id) + 1
        self.conn.execute(
            "INSERT INTO state_revision (workspace_id, revision) VALUES (?, ?) ON CONFLICT(workspace_id) DO UPDATE SET revision = excluded.revision",
            (workspace_id, revision),
        )
        return revision

    def get_idempotency(self, workspace_id: str, actor_id: str, idempotency_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM idempotency_keys WHERE workspace_id = ? AND actor_id = ? AND idempotency_key = ?",
            (workspace_id, actor_id, idempotency_key),
        ).fetchone()

    def save_idempotency(self, workspace_id: str, actor_id: str, idempotency_key: str, request_hash: str, response_json: str) -> None:
        row = self.get_idempotency(workspace_id, actor_id, idempotency_key)
        if row is None:
            self.conn.execute(
                """
                INSERT INTO idempotency_keys (workspace_id, actor_id, idempotency_key, request_hash, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (workspace_id, actor_id, idempotency_key, request_hash, response_json, datetime.now(timezone.utc).isoformat()),
            )
            return
        if row["request_hash"] == request_hash:
            return
        raise ValueError("idempotency hash mismatch")


    def get_room(self, room_id: str) -> Room | None:
        row = self.conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if row is None:
            return None
        return Room(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            location=row["location"],
            capacity=int(row["capacity"]),
            equipment=_json_loads(row["equipment_json"], []),
            position=_position_from_value(row["position_json"]),
            protected=bool(row["protected"]),
            active=bool(row["active"]),
        )

    def list_rooms(self, include_composite: bool = False, date: str | None = None, start_at: str | None = None, end_at: str | None = None, capacity: int | None = None, equipment: list[str] | None = None, room_type: str | None = None) -> tuple[list[Room], list[CompositeRoom]]:
        where = ["active = 1"]
        params: list[Any] = []
        if capacity is not None:
            where.append("capacity >= ?")
            params.append(capacity)
        if equipment:
            for item in equipment:
                where.append("equipment_json LIKE ?")
                params.append(f"%{item}%")
        if room_type:
            where.append("type = ?")
            params.append(room_type)
        query = f"SELECT * FROM rooms WHERE {' AND '.join(where)} ORDER BY id"
        rooms = [
            Room(
                id=row["id"],
                name=row["name"],
                type=row["type"],
                location=row["location"],
                capacity=int(row["capacity"]),
                equipment=_json_loads(row["equipment_json"], []),
                position=_position_from_value(row["position_json"]),
                protected=bool(row["protected"]),
                active=bool(row["active"]),
            )
            for row in self.conn.execute(query, params).fetchall()
        ]
        composites: list[CompositeRoom] = []
        if include_composite:
            for row in self.conn.execute("SELECT * FROM composites WHERE active = 1 ORDER BY id").fetchall():
                composites.append(
                    CompositeRoom(
                        id=row["id"],
                        name=row["name"],
                        member_room_ids=_json_loads(row["member_room_ids_json"], []),
                        capacity=int(row["capacity"]),
                        equipment=_json_loads(row["equipment_json"], []),
                        position=_position_from_value(row["position_json"]),
                        protected=bool(row["protected"]),
                        active=bool(row["active"]),
                    )
                )
        return rooms, composites

    def upsert_room(self, room: Room) -> Room:
        self.conn.execute(
            """
            INSERT INTO rooms (id, name, type, location, capacity, equipment_json, position_json, protected, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                location = excluded.location,
                capacity = excluded.capacity,
                equipment_json = excluded.equipment_json,
                position_json = excluded.position_json,
                active = excluded.active
            """,
            (
                room.id,
                room.name,
                room.type,
                room.location,
                room.capacity,
                _json_dumps(room.equipment),
                _position_to_value(room.position),
                int(room.protected),
                int(room.active),
            ),
        )
        return room

    def upsert_opening_schedule(self, room_id: str, weekday: int, start_time: str, end_time: str, protected: bool = False) -> dict[str, Any]:
        schedule_id = f"sch_{room_id}_{weekday}"
        self.conn.execute(
            """
            INSERT INTO opening_schedules (id, room_id, weekday, start_time, end_time, protected)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                protected = excluded.protected
            """,
            (schedule_id, room_id, weekday, start_time, end_time, int(protected)),
        )
        return {"id": schedule_id, "room_id": room_id, "weekday": weekday, "start_time": start_time, "end_time": end_time}

    def patch_opening_schedule(self, schedule_id: str, room_id: str, weekday: int, start_time: str, end_time: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT protected FROM opening_schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            raise KeyError(schedule_id)
        if row["protected"]:
            raise ValueError("protected")
        self.conn.execute(
            """
            UPDATE opening_schedules
            SET room_id = ?, weekday = ?, start_time = ?, end_time = ?
            WHERE id = ?
            """,
            (room_id, weekday, start_time, end_time, schedule_id),
        )
        return {"id": schedule_id, "room_id": room_id, "weekday": weekday, "start_time": start_time, "end_time": end_time}


    def delete_opening_schedule(self, schedule_id: str) -> None:
        row = self.conn.execute("SELECT protected FROM opening_schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            raise KeyError(schedule_id)
        if row["protected"]:
            raise ValueError("protected")
        self.conn.execute("DELETE FROM opening_schedules WHERE id = ?", (schedule_id,))

    def list_rules(self, target_type: str | None = None, target_id: str | None = None, rule_type: str | None = None, fixed: bool | None = None, date: str | None = None, limit: int = 100) -> list[Rule]:
        where: list[str] = []
        params: list[Any] = []
        if target_type:
            where.append("target_type = ?")
            params.append(target_type)
        if target_id:
            where.append("target_id = ?")
            params.append(target_id)
        if rule_type:
            where.append("rule_type = ?")
            params.append(rule_type)
        if fixed is not None:
            where.append("fixed = ?")
            params.append(int(fixed))
        if date:
            where.append("(match_key LIKE ? OR reason LIKE ?)")
            params.extend([f"%{date}%", f"%{date}%"])
        query = "SELECT * FROM rules"
        if where:
            query += f" WHERE {' AND '.join(where)}"
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        rules: list[Rule] = []
        for row in self.conn.execute(query, params).fetchall():
            windows = [TimeWindow(**item) for item in _json_loads(row["time_windows_json"], [])]
            rules.append(
                Rule(
                    id=row["id"],
                    rule_type=row["rule_type"],
                    target_type=row["target_type"],
                    target_id=row["target_id"],
                    time_windows=windows,
                    reason=row["reason"],
                    fixed=bool(row["fixed"]),
                    editable=bool(row["editable"]),
                    match_key=row["match_key"],
                    created_by=row["created_by"],
                    updated_by=row["updated_by"],
                )
            )
        return rules

    def get_rule(self, rule_id: str) -> Rule | None:
        row = self.conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        if row is None:
            return None
        return Rule(
            id=row["id"],
            rule_type=row["rule_type"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            time_windows=[TimeWindow(**item) for item in _json_loads(row["time_windows_json"], [])],
            reason=row["reason"],
            fixed=bool(row["fixed"]),
            editable=bool(row["editable"]),
            match_key=row["match_key"],
            created_by=row["created_by"],
            updated_by=row["updated_by"],
        )

    def match_rule(self, target_type: str, target_id: str, rule_type: str, match_key: str | None, date: str | None = None) -> Rule | None:
        if match_key:
            row = self.conn.execute("SELECT * FROM rules WHERE match_key = ? AND fixed = 0", (match_key,)).fetchone()
            if row:
                return self._rule_from_row(row)
        query = "SELECT * FROM rules WHERE target_type = ? AND target_id = ? AND rule_type = ? AND fixed = 0"
        params: list[Any] = [target_type, target_id, rule_type]
        if date:
            query += " AND (match_key LIKE ? OR reason LIKE ?)"
            params.extend([f"%{date}%", f"%{date}%"])
        query += " ORDER BY updated_by DESC, id DESC LIMIT 1"
        row = self.conn.execute(query, params).fetchone()
        return self._rule_from_row(row) if row else None

    def upsert_rule(self, rule: Rule) -> tuple[Rule | None, Rule]:
        old = self.get_rule(rule.id) if self.get_rule(rule.id) else None
        self.conn.execute(
            """
            INSERT INTO rules (id, rule_type, target_type, target_id, time_windows_json, reason, fixed, editable, match_key, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                rule_type = excluded.rule_type,
                target_type = excluded.target_type,
                target_id = excluded.target_id,
                time_windows_json = excluded.time_windows_json,
                reason = excluded.reason,
                fixed = excluded.fixed,
                editable = excluded.editable,
                match_key = excluded.match_key,
                updated_by = excluded.updated_by
            """,
            (
                rule.id,
                rule.rule_type,
                rule.target_type,
                rule.target_id,
                _json_dumps([window.to_dict() for window in rule.time_windows]),
                rule.reason,
                int(rule.fixed),
                int(rule.editable),
                rule.match_key,
                rule.created_by,
                rule.updated_by,
            ),
        )
        return old, rule

    def delete_rule(self, rule_id: str) -> Rule:
        rule = self.get_rule(rule_id)
        if rule is None:
            raise KeyError(rule_id)
        if rule.fixed:
            raise ValueError("protected")
        self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        return rule

    def create_booking(self, booking: Booking, idempotency_key: str, actor_id: str, reason: str | None = None) -> Booking:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO bookings (id, target_type, target_id, start_at, end_at, title, organizer_id, attendees_json, description, status, idempotency_key, actor_id, reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking.id,
                booking.target_type,
                booking.target_id,
                booking.start_at,
                booking.end_at,
                booking.title,
                booking.organizer_id,
                _json_dumps(booking.attendees),
                booking.description,
                booking.status,
                idempotency_key,
                actor_id,
                reason,
                now,
                now,
            ),
        )
        return booking

    def get_booking(self, booking_id: str) -> Booking | None:
        row = self.conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if row is None:
            return None
        return self._booking_from_row(row)

    def list_bookings(self, target_type: str | None = None, target_id: str | None = None, actor_id: str | None = None, date: str | None = None, range_start: str | None = None, range_end: str | None = None, status: str | None = None, limit: int = 50) -> list[Booking]:
        where: list[str] = []
        params: list[Any] = []
        if target_type:
            where.append("target_type = ?")
            params.append(target_type)
        if target_id:
            where.append("target_id = ?")
            params.append(target_id)
        if actor_id:
            where.append("organizer_id = ? OR actor_id = ?")
            params.extend([actor_id, actor_id])
        if date:
            where.append("date(start_at) <= ?")
            where.append("date(end_at) >= ?")
            params.extend([date, date])
        if range_start:
            where.append("end_at > ?")
            params.append(range_start)
        if range_end:
            where.append("start_at < ?")
            params.append(range_end)
        if status:
            where.append("status = ?")
            params.append(status)
        query = "SELECT * FROM bookings"
        if where:
            query += f" WHERE {' AND '.join(where)}"
        query += " ORDER BY start_at LIMIT ?"
        params.append(limit)
        return [self._booking_from_row(row) for row in self.conn.execute(query, params).fetchall()]

    def update_booking(self, booking_id: str, **fields: Any) -> Booking:
        if not fields:
            row = self.conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            return self._booking_from_row(row) if row else None  # type: ignore[return-value]
        assignments = [f"{key} = ?" for key in fields]
        params: list[Any] = [*fields.values(), booking_id]
        self.conn.execute(f"UPDATE bookings SET {', '.join(assignments)} WHERE id = ?", params)
        row = self.conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return self._booking_from_row(row) if row else None  # type: ignore[return-value]

    def list_confirmed_bookings_for_window(self, start_at: str, end_at: str) -> list[Booking]:
        rows = self.conn.execute(
            """
            SELECT * FROM bookings
            WHERE status = 'confirmed'
              AND start_at < ?
              AND end_at > ?
            ORDER BY start_at
            """,
            (end_at, start_at),
        ).fetchall()
        return [self._booking_from_row(row) for row in rows]

    def list_opening_schedules(self, room_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM opening_schedules WHERE room_id = ? ORDER BY weekday", (room_id,)).fetchall()]

    def _rule_from_row(self, row: sqlite3.Row) -> Rule:
        return Rule(
            id=row["id"],
            rule_type=row["rule_type"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            time_windows=[TimeWindow(**item) for item in _json_loads(row["time_windows_json"], [])],
            reason=row["reason"],
            fixed=bool(row["fixed"]),
            editable=bool(row["editable"]),
            match_key=row["match_key"],
            created_by=row["created_by"],
            updated_by=row["updated_by"],
        )

    def _booking_from_row(self, row: sqlite3.Row) -> Booking:
        return Booking(
            id=row["id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            start_at=row["start_at"],
            end_at=row["end_at"],
            title=row["title"],
            organizer_id=row["organizer_id"],
            attendees=_json_loads(row["attendees_json"], []),
            description=row["description"],
            status=row["status"],
        )
