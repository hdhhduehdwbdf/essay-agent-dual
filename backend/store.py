# -*- coding: utf-8 -*-
"""SQLite 存储层：学生、教师、课程、运行状态、会话、记忆、事件。

零第三方依赖，只用标准库 sqlite3。所有写操作串行化，避免并发写锁。
"""
import json
import os
import sqlite3
import threading
import time
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("APP_DATA_DIR") or os.path.join(os.path.dirname(BASE_DIR), "data")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS teachers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, school TEXT DEFAULT '', subject TEXT DEFAULT '',
  class_code TEXT UNIQUE, created_at REAL);

CREATE TABLE IF NOT EXISTS students (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, class_name TEXT DEFAULT '', teacher_id TEXT,
  created_at REAL);

CREATE TABLE IF NOT EXISTS courses (
  id TEXT PRIMARY KEY, teacher_id TEXT, title TEXT NOT NULL, genre TEXT DEFAULT '记叙文',
  prompt TEXT DEFAULT '', due TEXT DEFAULT '', status TEXT DEFAULT 'published',
  current_stage INTEGER DEFAULT 0, created_at REAL);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, course_id TEXT, student_id TEXT,
  stage INTEGER DEFAULT 0, passed INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
  created_at REAL, updated_at REAL);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, run_id TEXT, session_id TEXT, role TEXT,
  content TEXT, cites TEXT DEFAULT '[]', steps TEXT DEFAULT '[]',
  created_at REAL);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, student_id TEXT, type TEXT DEFAULT '学业',
  content TEXT NOT NULL, source TEXT DEFAULT '',
  confidence REAL DEFAULT 0.8, pinned INTEGER DEFAULT 0,
  recall_count INTEGER DEFAULT 0, superseded_by TEXT DEFAULT '',
  created_at REAL, last_seen_at REAL);

CREATE TABLE IF NOT EXISTS marks (
  id TEXT PRIMARY KEY, student_id TEXT, course_id TEXT,
  text TEXT, at_sec INTEGER DEFAULT 0, created_at REAL);

CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY, teacher_id TEXT, title TEXT, kind TEXT,
  size_bytes INTEGER DEFAULT 0, status TEXT DEFAULT 'ready', created_at REAL);

CREATE TABLE IF NOT EXISTS unanswered (
  id TEXT PRIMARY KEY, teacher_id TEXT, question TEXT NOT NULL,
  ask_count INTEGER DEFAULT 1, created_at REAL, resolved INTEGER DEFAULT 0);
"""

_local = threading.local()
_write_lock = threading.Lock()


def now():
    return time.time()


def new_id(prefix=""):
    return (prefix + uuid.uuid4().hex[:12]) if prefix else uuid.uuid4().hex[:12]


def _conn():
    if getattr(_local, "conn", None) is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        c = sqlite3.connect(os.path.join(DATA_DIR, "app.db"), timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return _local.conn


def init_db():
    with _write_lock:
        c = _conn()
        c.executescript(SCHEMA)
        c.commit()


def q(sql, args=()):
    return [dict(r) for r in _conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    rows = _conn().execute(sql, args).fetchall()
    return dict(rows[0]) if rows else None


def x(sql, args=()):
    with _write_lock:
        c = _conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur


def insert(table, row):
    cols = ", ".join(row.keys())
    marks = ", ".join(["?"] * len(row))
    x("INSERT INTO %s (%s) VALUES (%s)" % (table, cols, marks), tuple(row.values()))
    return row


def update(table, row_id, patch):
    if not patch:
        return
    sets = ", ".join("%s = ?" % k for k in patch)
    x("UPDATE %s SET %s WHERE id = ?" % (table, sets), tuple(patch.values()) + (row_id,))


def get_setting(key, default=None):
    r = q1("SELECT value FROM settings WHERE key = ?", (key,))
    return r["value"] if r else default


def set_setting(key, value):
    x("INSERT INTO settings (key, value) VALUES (?, ?) "
      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def loads(text, default=None):
    try:
        return json.loads(text) if text else default
    except Exception:
        return default
