# -*- coding: utf-8 -*-
"""端到端联调测试：覆盖学生端与教师端的全部接口。

用法（先启动 server.py）：
    python backend/smoke_test.py
    python backend/smoke_test.py --port 8901
"""
import json
import sys
import urllib.request
from urllib.parse import quote

BASE = "http://127.0.0.1:%d"


def call(port, path, body=None, uid="student_demo", method=None):
    url = (BASE % port) + path
    headers = {"X-User-Id": uid, "Content-Type": "application/json"}
    data = None
    m = method
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        m = m or "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=m or "GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  [OK]   %s" % name)
    else:
        FAIL.append(name)
        print("  [FAIL] %s  %s" % (name, detail))


def main():
    port = 8901
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ("--port", "-p") and i + 1 < len(args):
            port = int(args[i + 1])

    print("=" * 62)
    print(" 作文分身 · 端到端联调测试  (port %d)" % port)
    print("=" * 62)

    print("\n[学生端]")
    h = call(port, "/api/student/home")
    check("首页返回学生与教师", h["ok"] and h["data"]["student"]["name"])
    # 课程由教师真实发布后才出现；全新库首页横条应为空
    check("全新库首屏无预置课程", h["data"]["notice"] is None,
          "notice=%s" % h["data"].get("notice"))

    # 教师发布一篇 -> 学生端横条立刻出现
    pub = call(port, "/api/teacher/publish",
               {"title": "窗外", "genre": "记叙文", "prompt": "观察与抒情。", "due": "周五"},
               uid="teacher_demo")
    check("教师可发布作文", pub["ok"] and pub["data"]["published"])
    h2 = call(port, "/api/student/home")
    check("发布后学生端横条出现", h2["data"]["notice"] is not None
          and "窗外" in h2["data"]["notice"]["title"])

    # 关闭课程 -> 横条消失
    course_id = pub["data"]["course"]["id"]
    cl = call(port, "/api/teacher/course/close", {"courseId": course_id},
              uid="teacher_demo")
    check("教师可关闭课程", cl["ok"] and cl["data"]["closed"])
    h3 = call(port, "/api/student/home")
    check("关闭后学生端横条消失", h3["data"]["notice"] is None)

    # 再发布一篇供后续流程测试
    call(port, "/api/teacher/publish",
         {"title": "和解", "genre": "记叙文", "prompt": "以和解为题。", "due": "周日 22:00"},
         uid="teacher_demo")
    cs = call(port, "/api/student/courses")
    check("课程列表可读", cs["ok"] and len(cs["data"]["courses"]) >= 1)
    course_id = cs["data"]["courses"][0]["id"]

    m = call(port, "/api/student/memory")
    check("记忆接口可读（新用户可为空）", m["ok"] and "groups" in m["data"])
    all_items = [i for g in m["data"]["groups"] for i in g["items"]]

    sg = call(port, "/api/student/suggestions")
    check("推荐问句来自真实语料", sg["ok"] and isinstance(sg["data"]["suggestions"], list))

    # 命中语料
    r = call(port, "/api/student/chat", {"text": "老师，记叙文怎么审题？"})
    check("对话命中语料", r["ok"] and r["data"]["grounded"] is True)
    check("命中时带回出处", len(r["data"]["cites"]) > 0,
          "cites=%d" % len(r["data"].get("cites", [])))
    check("出处带原文片段", r["data"]["cites"] and r["data"]["cites"][0]["text"])

    # 未命中语料 -> 兜底不编造
    r2 = call(port, "/api/student/chat", {"text": "2026 新高考卷会考什么方向？"})
    check("未命中时不编造", r2["ok"] and r2["data"]["grounded"] is False)
    check("未命中时说没讲过", "没有讲过" in r2["data"]["text"])

    # 五环节
    f = call(port, "/api/student/flow?courseId=" + quote(course_id))
    check("流程初始在第 1 环节", f["ok"] and f["data"]["stage"] == 0)
    check("流程有开场白", bool(f["data"]["greeting"]))

    s1 = call(port, "/api/student/flow/submit",
              {"courseId": course_id, "text": "我写了我跟妈妈吵架，最后我认错，她原谅我。我很难过。"})
    check("提交一稿有诊断结果", s1["ok"] and "diagnosis" in s1["data"])
    check("诊断只给一处问题", bool(s1["data"]["diagnosis"]["problem"]))
    check("诊断给出可执行动作", bool(s1["data"]["diagnosis"]["action"]))
    check("提交后推进到下一环节", s1["data"]["stage"] == 1,
          "stage=%s" % s1["data"].get("stage"))

    s2 = call(port, "/api/student/flow/submit",
              {"courseId": course_id, "text": "我觉得就是消除争议，重归于好。"})
    check("第二环节可继续提交", s2["ok"] and s2["data"]["stage"] == 2)

    # 对话与提交都应长出记忆（不再预置）
    m2 = call(port, "/api/student/memory")
    all_items2 = [i for g in m2["data"]["groups"] for i in g["items"]]
    check("记忆由真实交互产生", len(all_items2) >= 1,
          "items=%d" % len(all_items2))

    # 记忆修正
    if all_items2:
        mem_id = all_items2[0]["id"]
        fx = call(port, "/api/student/memory/fix",
                  {"id": mem_id, "content": "在准备 2028 年高考", "confidence": 0.99})
        check("记忆可修改", fx["ok"] and fx["data"]["updated"] is True)

    # 听课：学生自己写哪里没懂，不是预置文案
    mk = call(port, "/api/student/listen/mark",
              {"courseId": course_id, "text": "老师刚说的那个新词我没听清", "atSec": 12})
    check("听课标记保存", mk["ok"] and mk["data"]["saved"])
    fin = call(port, "/api/student/listen/finish",
               {"courseId": course_id, "seconds": 25})
    check("听课结束返回笔记", fin["ok"] and "marks" in fin["data"])
    check("没懂点转成笔记", len(fin["data"]["marks"]) >= 1)

    print("\n[教师端]")
    t = call(port, "/api/teacher/state", uid="teacher_demo")
    check("教师状态可读", t["ok"] and t["data"]["teacher"]["name"])
    check("材料统计非空", t["data"]["stats"]["materials"] >= 1)
    check("答不上来的清单存在", isinstance(t["data"]["unanswered"], list))
    check("L1 已上线", t["data"]["tiers"]["l1"]["state"] == "online")
    check("L2 明确未开启", t["data"]["tiers"]["l2"]["state"] == "off")

    mats = call(port, "/api/teacher/materials", uid="teacher_demo")
    check("材料列表可读", mats["ok"] and mats["data"]["documents"] >= 1)

    # 上传材料 -> 应能被检索到
    up = call(port, "/api/teacher/upload",
              {"filename": "99-测试材料.md",
               "content": "# 关于书单\n\n我推荐学生先读《活着》和《边城》，这两本的语言最适合学描写。"},
              uid="teacher_demo")
    check("上传材料成功", up["ok"] and up["data"]["uploaded"])
    hit = call(port, "/api/student/chat", {"text": "老师有没有推荐的书单？"})
    check("上传后立即可检索", hit["ok"] and hit["data"]["grounded"] is True,
          "grounded=%s" % (hit["data"].get("grounded") if hit["ok"] else "err"))

    pv = call(port, "/api/teacher/preview?q=" + quote("立意怎么写"), uid="teacher_demo")
    check("教师试聊可用", pv["ok"] and "text" in pv["data"])

    st = call(port, "/api/teacher/students", uid="teacher_demo")
    check("学生列表可读", st["ok"] and len(st["data"]["students"]) >= 1)
    stu0 = st["data"]["students"][0]
    check("学生带环节进度", "stageName" in stu0)

    rs = call(port, "/api/teacher/resolve",
              {"question": "2026 新高考卷会考什么方向？"}, uid="teacher_demo")
    check("答不上来的问题可标记已解决", rs["ok"] and rs["data"]["resolved"])

    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项：")
        for f in FAIL:
            print("   - %s" % f)
    print("=" * 62)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
