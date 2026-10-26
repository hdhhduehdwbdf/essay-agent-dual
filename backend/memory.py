# -*- coding: utf-8 -*-
"""记忆层：写入、召回、冲突消解、容量淘汰。

淘汰用综合分而不是「最旧先死」：
    score = 0.35*置信 + 0.25*新鲜 + 0.25*被想起 + 0.15*置顶
这样「用户是高三学生家长、孩子 2027 高考」这种 89 天没被再提但极重要的画像不会先被删。
"""
import time

from . import store

CAPACITY = 200

# 冲突消解：同类型里语义重叠的记忆，新的取代旧的
CONFLICT_PAIRS = [
    ("主攻议论文", "主攻记叙文"),
    ("议论文", "记叙文"),
    ("想学", "正在练"),
]

TYPE_ORDER = ["学业", "偏好", "表达习惯", "事实"]


def _freshness(last_seen_at):
    days = max(0.0, (time.time() - (last_seen_at or time.time())) / 86400.0)
    # 半衰期 60 天
    return 0.5 ** (days / 60.0)


def score(m):
    conf = float(m.get("confidence") or 0.5)
    fresh = _freshness(m.get("last_seen_at"))
    recall = min(1.0, (m.get("recall_count") or 0) / 5.0)
    pin = 1.0 if m.get("pinned") else 0.0
    return 0.35 * conf + 0.25 * fresh + 0.25 * recall + 0.15 * pin


def _evict_if_needed(student_id):
    rows = store.q(
        "SELECT * FROM memories WHERE student_id = ? AND superseded_by = ''", (student_id,))
    if len(rows) <= CAPACITY:
        return 0
    rows.sort(key=score)
    drop = len(rows) - CAPACITY
    for m in rows[:drop]:
        store.x("DELETE FROM memories WHERE id = ?", (m["id"],))
    return drop


def _find_conflict(student_id, content):
    """找一条被新内容取代的旧记忆。"""
    old = store.q(
        "SELECT * FROM memories WHERE student_id = ? AND superseded_by = ''", (student_id,))
    for a, b in CONFLICT_PAIRS:
        if a in content:
            for m in old:
                if b in m["content"]:
                    return m, b
        if b in content:
            for m in old:
                if a in m["content"]:
                    return m, a
    return None, None


def add(student_id, content, type_="学业", source="", confidence=0.8):
    content = (content or "").strip()
    if not content:
        return None

    # 完全重复：只刷新时间，不新增
    dup = store.q1(
        "SELECT * FROM memories WHERE student_id = ? AND content = ? AND superseded_by = ''",
        (student_id, content))
    if dup:
        store.update("memories", dup["id"], {"last_seen_at": store.now(),
                                             "recall_count": (dup["recall_count"] or 0) + 1})
        return dup["id"]

    superseded_id = ""
    conflict, old_token = _find_conflict(student_id, content)
    if conflict:
        superseded_id = conflict["id"]

    row = {
        "id": store.new_id("mem_"),
        "student_id": student_id,
        "type": type_,
        "content": content,
        "source": source,
        "confidence": float(confidence),
        "pinned": 0,
        "recall_count": 0,
        "superseded_by": "",
        "created_at": store.now(),
        "last_seen_at": store.now(),
    }
    store.insert("memories", row)

    if superseded_id:
        store.update("memories", superseded_id, {"superseded_by": row["id"]})

    _evict_if_needed(student_id)
    return row["id"]


def list_for(student_id):
    rows = store.q("SELECT * FROM memories WHERE student_id = ? ORDER BY type, created_at",
                   (student_id,))
    out = []
    for m in rows:
        superseded_by = m.get("superseded_by") or ""
        item = {
            "id": m["id"],
            "type": m["type"],
            "content": m["content"],
            "source": m["source"],
            "confidence": round(float(m["confidence"]), 2),
            "pinned": bool(m["pinned"]),
            "recallCount": m["recall_count"] or 0,
            "score": round(score(m), 3),
            "createdAt": m["created_at"],
            "superseded": bool(superseded_by),
        }
        if superseded_by:
            old = store.q1("SELECT content FROM memories WHERE id = ?", (superseded_by,))
            item["replacedBy"] = old["content"] if old else ""
        out.append(item)

    out.sort(key=lambda x: (TYPE_ORDER.index(x["type"]) if x["type"] in TYPE_ORDER else 99,
                            -x["score"]))
    return out


def touch(memory_id):
    m = store.q1("SELECT recall_count FROM memories WHERE id = ?", (memory_id,))
    if m:
        store.update("memories", memory_id, {
            "last_seen_at": store.now(),
            "recall_count": (m["recall_count"] or 0) + 1,
        })


def update_text(memory_id, content, confidence):
    store.update("memories", memory_id, {
        "content": content.strip(),
        "confidence": float(confidence),
        "last_seen_at": store.now(),
    })


def delete(memory_id):
    store.x("DELETE FROM memories WHERE id = ?", (memory_id,))


def learned_today(student_id):
    """会话末统一呈现「今天我学到的」，不实时弹。"""
    since = store.now() - 86400
    rows = store.q(
        "SELECT content FROM memories WHERE student_id = ? AND created_at > ? "
        "AND superseded_by = '' ORDER BY created_at DESC LIMIT 5", (student_id, since))
    return [r["content"] for r in rows]
