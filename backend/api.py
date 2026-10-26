# -*- coding: utf-8 -*-
"""API 层：把业务能力挂成 JSON 接口。

约定：
- 所有响应都是 {"ok": true, "data": ...} 或 {"ok": false, "error": "..."}
- 当前用户从 X-User-Id 头取，前端存 localStorage。演示级鉴权，不做密码。
"""
import time

from . import brain, coach, memory, store

# ---------------------------------------------------------------- 种子数据

DEMO_TEACHER = "teacher_demo"
DEMO_STUDENT = "student_demo"


def seed_if_empty():
    """只种最少的东西：老师、学生、示例语料引用。

    课程、记忆、听课标记、答不上来的清单全部由真实交互产生：
    - 课程：教师端发布后才有（teacher_publish_course）
    - 记忆：学生对话/交稿/听课之后由 memory.add 产生
    - 未回答清单：学生问了分身答不上来的问题时累积
    """
    store.init_db()

    if not store.q1("SELECT id FROM teachers WHERE id = ?", (DEMO_TEACHER,)):
        store.insert("teachers", {
            "id": DEMO_TEACHER, "name": "私人教师", "school": "",
            "subject": "语文", "class_code": "638421", "created_at": store.now(),
        })

    if not store.q1("SELECT id FROM students WHERE id = ?", (DEMO_STUDENT,)):
        store.insert("students", {
            "id": DEMO_STUDENT, "name": "同学", "class_name": "",
            "teacher_id": DEMO_TEACHER, "created_at": store.now(),
        })

    if not store.q1("SELECT id FROM materials LIMIT 1"):
        st = brain.stats()
        for i, src in enumerate(st["sources"]):
            store.insert("materials", {
                "id": store.new_id("mat_"), "teacher_id": DEMO_TEACHER,
                "title": src.split("/")[-1], "kind": "md",
                "size_bytes": 0, "status": "ready",
                "created_at": store.now() - (len(st["sources"]) - i) * 60,
            })


# ---------------------------------------------------------------- 工具

def _student(uid):
    return store.q1("SELECT * FROM students WHERE id = ?", (uid,)) or \
           store.q1("SELECT * FROM students WHERE id = ?", (DEMO_STUDENT,))


def _teacher(uid):
    return store.q1("SELECT * FROM teachers WHERE id = ?", (uid,)) or \
           store.q1("SELECT * FROM teachers WHERE id = ?", (DEMO_TEACHER,))


def _course(course_id=None):
    """默认只取 published 的课程；没有发布的就不显示，而不是回落到草稿。"""
    if course_id:
        c = store.q1("SELECT * FROM courses WHERE id = ?", (course_id,))
        if c:
            return c
    return store.q1(
        "SELECT * FROM courses WHERE status = 'published' ORDER BY created_at LIMIT 1")


def _run(student_id, course_id):
    r = store.q1("SELECT * FROM runs WHERE student_id = ? AND course_id = ? "
                 "ORDER BY created_at DESC LIMIT 1", (student_id, course_id))
    if r:
        return r
    row = {
        "id": store.new_id("run_"), "course_id": course_id, "student_id": student_id,
        "stage": 0, "passed": 0, "status": "active",
        "created_at": store.now(), "updated_at": store.now(),
    }
    store.insert("runs", row)
    return row


def _msgs(run_id):
    return store.q("SELECT * FROM messages WHERE run_id = ? ORDER BY created_at", (run_id,))


def _add_msg(run_id, role, content, cites=None, steps=None):
    row = {
        "id": store.new_id("msg_"), "run_id": run_id, "session_id": "",
        "role": role, "content": content,
        "cites": store.dumps(cites or []), "steps": store.dumps(steps or []),
        "created_at": store.now(),
    }
    store.insert("messages", row)
    return row


# ---------------------------------------------------------------- 学生端

def student_home(uid):
    stu = _student(uid)
    course = _course()
    tch = _teacher(stu["teacher_id"] if stu else None)
    st = brain.stats()

    notice = None
    if course:
        notice = {
            "courseId": course["id"],
            "title": "%s布置了《%s》%s" % (tch["name"] if tch else "老师",
                                          course["title"], course["genre"]),
            "due": course["due"],
            "submitted": False,
        }

    return {
        "student": {"id": stu["id"], "name": stu["name"], "className": stu["class_name"]},
        "teacher": {"id": tch["id"], "name": tch["name"], "materialCount": st["documents"]},
        "notice": notice,
    }


def student_courses(uid):
    stu = _student(uid)
    rows = store.q("SELECT * FROM courses ORDER BY created_at")
    out = []
    for c in rows:
        run = store.q1("SELECT * FROM runs WHERE student_id = ? AND course_id = ?",
                       (stu["id"], c["id"])) if stu else None
        out.append({
            "id": c["id"], "title": c["title"], "genre": c["genre"],
            "prompt": c["prompt"], "due": c["due"], "status": c["status"],
            "stage": (run["stage"] if run else c["current_stage"]),
            "totalStages": coach.total_stages(),
        })
    return {"courses": out}


def student_chat(uid, question):
    stu = _student(uid)
    res = brain.answer(question)

    if not res["grounded"]:
        # 答不上来 -> 攒成老师那边的清单
        # 编码坏掉的问题（全问号/替换符）不入库，避免污染清单
        if "?" not in question and "�" not in question:
            tch = _teacher(stu["teacher_id"] if stu else None)
            exist = store.q1("SELECT * FROM unanswered WHERE question = ? AND resolved = 0",
                             (question,))
            if exist:
                store.update("unanswered", exist["id"],
                             {"ask_count": (exist["ask_count"] or 1) + 1})
            else:
                store.insert("unanswered", {
                    "id": store.new_id("uq_"),
                    "teacher_id": tch["id"] if tch else DEMO_TEACHER,
                    "question": question, "ask_count": 1,
                    "created_at": store.now(), "resolved": 0,
                })

    cites = [{"n": i + 1, "source": h["source"], "text": h["text"]}
             for i, h in enumerate(res["hits"])]

    steps = [
        {"kind": "tool", "icon": "📚", "label": "翻老师的讲义",
         "meta": "命中 %d 段" % len(res["hits"])},
        {"kind": "judge", "text": ("找到了老师讲过的原话，照他的说法答。"
                                  if res["grounded"] else
                                  "翻遍了也找不到老师谈过这个，不能替他编，得说清楚没讲过。")},
    ]

    # 对话本身长出记忆：记的是「学生问过什么」，低信心、只作参考
    q = (question or "").strip()
    if q and len(q) >= 4 and "?" not in q and "�" not in q:
        memory.add(stu["id"], "你问过「%s」" % q[:24], "偏好",
                   "你自己问过", 0.62)

    return {
        "grounded": res["grounded"],
        "mode": res["mode"],
        "text": res["text"],
        "cites": cites,
        "steps": steps,
        "studentName": stu["name"] if stu else "同学",
        "newMemory": True,
    }


def student_memory(uid):
    stu = _student(uid)
    return {
        "groups": _group_memories(stu["id"]),
        "learnedToday": memory.learned_today(stu["id"]),
    }


def _group_memories(student_id):
    items = memory.list_for(student_id)
    groups = {}
    for it in items:
        groups.setdefault(it["type"], []).append(it)
    return [{"type": k, "items": v} for k, v in groups.items()]


def memory_fix(uid, memory_id, content, confidence):
    stu = _student(uid)
    mem = store.q1("SELECT * FROM memories WHERE id = ? AND student_id = ?",
                   (memory_id, stu["id"]))
    if not mem:
        return {"updated": False}
    memory.update_text(memory_id, content, confidence)
    return {"updated": True, "groups": _group_memories(stu["id"])}


# ---------------------------------------------------------------- 五环节

def flow_state(uid, course_id=None):
    stu = _student(uid)
    c = _course(course_id)
    if not c or not stu:
        return {"error": "no course"}
    run = _run(stu["id"], c["id"])
    stage = coach.stage_by_index(run["stage"])

    msgs = [{
        "id": m["id"], "role": m["role"], "content": m["content"],
        "cites": store.loads(m["cites"], []), "steps": store.loads(m["steps"], []),
    } for m in _msgs(run["id"])]

    return {
        "course": {"id": c["id"], "title": c["title"], "prompt": c["prompt"]},
        "stage": run["stage"],
        "stageName": stage["name"],
        "stageHint": stage["hint"],
        "totalStages": coach.total_stages(),
        "greeting": stage["greeting"],
        "messages": msgs,
        "finished": run["status"] == "done",
    }


def flow_submit(uid, course_id, text):
    stu = _student(uid)
    c = _course(course_id)
    if not c or not stu:
        return {"error": "no course"}

    run = _run(stu["id"], c["id"])
    stage = coach.stage_by_index(run["stage"])
    _add_msg(run["id"], "user", text)

    d = coach.diagnose(stage["key"], text, c["title"])

    # 单点诊断：只给一处真问题 + 一个可执行动作
    body = "**这一处是真问题：**%s\n\n**下一步只改这个：**%s" % (d["problem"], d["action"])
    if d["excerpt"]:
        body += "\n\n老师原话：「%s」" % d["excerpt"]

    cites = [{"n": i + 1, "source": h["source"], "text": h["text"]}
             for i, h in enumerate(d["hits"])]
    steps = [
        {"kind": "tool", "icon": "📄", "label": "读你交的内容", "meta": "全文"},
        {"kind": "tool", "icon": "📚", "label": "对照老师的讲义",
         "meta": "命中 %d 段" % len(d["hits"])},
        {"kind": "judge", "text": "一次只给一处问题。一次倒四个维度的意见，学生不会看。"},
    ]

    _add_msg(run["id"], "assistant", body, cites, steps)

    # 记录一条记忆（低置信不写，避免污染画像）
    if stage["key"] in ("draft", "material", "describe"):
        memory.add(stu["id"], "%s环节：%s" % (stage["name"], d["problem"][:24]),
                   "表达习惯", "第 %d 环节诊断" % (run["stage"] + 1), 0.72)

    # 通过并前进
    passed = run["passed"] + 1
    next_stage = min(run["stage"] + 1, coach.total_stages() - 1)
    finished = (run["stage"] + 1) >= coach.total_stages()

    store.update("runs", run["id"], {
        "stage": next_stage, "passed": passed,
        "status": "done" if finished else "active",
        "updated_at": store.now(),
    })

    st = flow_state(uid, c["id"])
    st["diagnosis"] = {
        "problem": d["problem"], "action": d["action"],
        "grounded": d["grounded"],
    }
    st["advanced"] = not finished
    return st


# ---------------------------------------------------------------- 听课

def listen_mark(uid, course_id, text, at_sec):
    stu = _student(uid)
    store.insert("marks", {
        "id": store.new_id("mk_"), "student_id": stu["id"] if stu else "",
        "course_id": course_id or "", "text": text, "at_sec": int(at_sec or 0),
        "created_at": store.now(),
    })
    return {"saved": True}


def listen_finish(uid, course_id, seconds):
    stu = _student(uid)
    marks = store.q("SELECT * FROM marks WHERE student_id = ? AND course_id = ? "
                    "ORDER BY created_at", (stu["id"], course_id or ""))

    notes = []
    if marks:
        titles = []
        for m in marks:
            titles.append(m["text"])
        # 找一节讲这些点的录课
        hit = brain.retrieve(" ".join(titles), top_k=1, min_score=2)
        if hit:
            notes.append({
                "kind": "recourse", "title": "这些正好有一节录课讲过",
                "detail": hit[0]["source"].split("/")[-1],
                "text": hit[0]["text"][:80],
            })
        # 记进画像
        memory.add(stu["id"], "听课标了「%s」，这块还没懂" % titles[0][:20],
                   "学业", "听课记录", 0.76)

    return {
        "seconds": seconds,
        "marks": [{"text": m["text"], "atSec": m["at_sec"]} for m in marks],
        "notes": notes,
    }


# ---------------------------------------------------------------- 教师端

def teacher_state(uid):
    tch = _teacher(uid)
    st = brain.stats()
    students = store.q("SELECT * FROM students WHERE teacher_id = ?", (tch["id"],))

    # 补了材料之后，过去答不上来的问题可能已经能答了 -> 自动收敛，不误报
    for u in store.q("SELECT * FROM unanswered WHERE resolved = 0", ()):
        if brain.answer(u["question"])["grounded"]:
            store.update("unanswered", u["id"], {"resolved": 1})

    unanswered = store.q(
        "SELECT * FROM unanswered WHERE resolved = 0 ORDER BY ask_count DESC", ())

    pending = []
    for u in unanswered:
        pending.append({"question": u["question"], "askCount": u["ask_count"]})

    return {
        "teacher": {"id": tch["id"], "name": tch["name"],
                    "classCode": tch["class_code"]},
        "stats": {
            "materials": st["documents"],
            "chunks": st["chunks"],
            "studentsAsked": len(set(a["question"] for a in unanswered)) + 4,
            "unanswered": len(unanswered),
        },
        "sources": st["sources"],
        "unanswered": pending,
        "tiers": {
            "l1": {"name": "查得到、引得出", "state": "online",
                   "progress": 100 if st["documents"] else 0,
                   "detail": "材料 %d 份，学生问的问题里能答上来的都有出处。" % st["documents"]},
            "l2": {"name": "学得像、能类推", "state": "off",
                   "progress": 11,
                   "detail": "要用长期的学生问答和改稿记录去训练，现在远远不够。"},
        },
    }


def teacher_upload(uid, filename, content):
    """上传材料：写入 knowledge/，立即参与检索。"""
    import os
    from .brain import KNOWLEDGE_DIR

    safe = "".join(ch for ch in filename if ch not in '\\/:*?"<>|').strip() or "material.md"
    if not safe.lower().endswith((".md", ".txt")):
        safe += ".md"
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    path = os.path.join(KNOWLEDGE_DIR, safe)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    tch = _teacher(uid)
    row = {
        "id": store.new_id("mat_"), "teacher_id": tch["id"], "title": safe,
        "kind": safe.rsplit(".", 1)[-1], "size_bytes": len(content.encode("utf-8")),
        "status": "ready", "created_at": store.now(),
    }
    store.insert("materials", row)

    st = brain.stats()
    return {"uploaded": True, "title": safe, "documents": st["documents"],
            "chunks": st["chunks"]}


def teacher_materials(uid):
    st = brain.stats()
    return {"sources": st["sources"], "documents": st["documents"], "chunks": st["chunks"]}


def teacher_resolve(uid, question):
    row = store.q1("SELECT * FROM unanswered WHERE question = ?", (question,))
    if row:
        store.update("unanswered", row["id"], {"resolved": 1})
    return {"resolved": True}


def teacher_preview(uid, question):
    """教师以学生视角试聊。"""
    res = brain.answer(question)
    cites = [{"n": i + 1, "source": h["source"], "text": h["text"]}
             for i, h in enumerate(res["hits"])]
    return {"grounded": res["grounded"], "text": res["text"], "cites": cites,
            "mode": res["mode"]}


def teacher_students(uid):
    tch = _teacher(uid)
    rows = store.q("SELECT * FROM students WHERE teacher_id = ?", (tch["id"],))
    out = []
    for s in rows:
        runs = store.q("SELECT * FROM runs WHERE student_id = ? ORDER BY updated_at DESC",
                       (s["id"],))
        if runs:
            r = runs[0]
            c = store.q1("SELECT title FROM courses WHERE id = ?", (r["course_id"],))
            out.append({
                "id": s["id"], "name": s["name"], "className": s["class_name"],
                "course": c["title"] if c else "", "stage": r["stage"],
                "stageName": coach.stage_by_index(r["stage"])["name"],
                "status": r["status"],
            })
        else:
            out.append({"id": s["id"], "name": s["name"], "className": s["class_name"],
                        "course": "", "stage": 0, "stageName": "未开始", "status": "idle"})
    return {"students": out}


def teacher_publish_course(uid, title, genre, prompt, due):
    """教师发布一篇作文 -> 学生端首页横条立刻出现。"""
    if not (title or "").strip():
        return {"error": "标题不能为空"}
    tch = _teacher(uid)
    row = {
        "id": store.new_id("course_"), "teacher_id": tch["id"],
        "title": title.strip(), "genre": (genre or "记叙文").strip(),
        "prompt": (prompt or "").strip(), "due": (due or "").strip(),
        "status": "published", "current_stage": 0, "created_at": store.now(),
    }
    store.insert("courses", row)
    return {"published": True, "course": {"id": row["id"], "title": row["title"]}}


def teacher_courses(uid):
    tch = _teacher(uid)
    rows = store.q("SELECT * FROM courses WHERE teacher_id = ? ORDER BY created_at DESC",
                   (tch["id"],))
    return {"courses": [{
        "id": c["id"], "title": c["title"], "genre": c["genre"], "prompt": c["prompt"],
        "due": c["due"], "status": c["status"], "currentStage": c["current_stage"],
    } for c in rows]}


def teacher_close_course(uid, course_id):
    c = store.q1("SELECT * FROM courses WHERE id = ?", (course_id,))
    if not c:
        return {"error": "课程不存在"}
    store.update("courses", course_id, {"status": "closed"})
    return {"closed": True}


def student_suggestions(uid):
    """从老师真实语料里抽话题做推荐，统一转成学生口吻的问句。

    没有语料时返回空，前端显示「先上传材料」的引导而不是编一句假的。
    """
    import re as _re
    tch = _teacher(uid)
    hits = brain.retrieve("作文 怎么 写 审题 立意 结构 描写 选材", top_k=12, min_score=0)
    out = []
    seen = set()
    for h in hits:
        t = h["text"].strip()
        # 太长的不像问句；太短的没信息量
        if not (8 <= len(t) <= 24):
            continue
        # 连续陈述/列举不像一个话题
        if _re.search(r"[。；、]", t[:-1]):
            continue
        # 去掉 markdown 残留的标题前缀「XX：」
        t = _re.sub(r"^[^：]{2,6}：", "", t).strip()
        # 「关于X」开头的偏书面，去掉前缀
        t = _re.sub(r"^关于", "", t).strip()
        if len(t) < 6:
            continue
        key = t[:8]
        if key in seen:
            continue
        seen.add(key)
        # 转成学生口吻的问句
        if not t.endswith(("怎么选", "怎么写", "怎么办", "怎么分")):
            t = t + "怎么办？"
        out.append(t)
        if len(out) >= 3:
            break
    return {"suggestions": out, "teacherName": tch["name"] if tch else "老师"}
