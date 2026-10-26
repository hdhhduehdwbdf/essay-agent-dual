# -*- coding: utf-8 -*-
"""零依赖 HTTP 服务：标准库 http.server，同时托管前端静态文件与 JSON API。

启动：python backend/server.py
     python backend/server.py --port 8900
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend import api
else:
    from . import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
}


def _ok(data):
    return {"ok": True, "data": data}


def _err(msg, code="bad_request"):
    return {"ok": False, "error": msg, "code": code}


class Handler(BaseHTTPRequestHandler):
    server_version = "EssayAgentDual/1.0"

    def log_message(self, fmt, *args):
        # 静音默认访问日志，只保留错误
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # -------------------------------------------------- 发送
    def _send(self, status, payload, ctype="application/json; charset=utf-8"):
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _uid(self):
        return (self.headers.get("X-User-Id") or "").strip() or api.DEMO_STUDENT

    # -------------------------------------------------- 静态
    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/student.html"
        rel = path.lstrip("/").replace("..", "")
        full = os.path.join(WEB_DIR, rel)
        if not os.path.isfile(full):
            self._send(404, "<h1>404</h1><p>%s 不存在</p>" % rel,
                       "text/html; charset=utf-8")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))

    # -------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        uid = self._uid()

        if not path.startswith("/api/"):
            return self._serve_static(path)

        try:
            if path == "/api/health":
                return self._send(200, _ok({"status": "up", "time": __import__("time").time()}))

            routes = {
                "/api/student/home": lambda: api.student_home(uid),
                "/api/student/courses": lambda: api.student_courses(uid),
                "/api/student/memory": lambda: api.student_memory(uid),
                "/api/student/flow": lambda: api.flow_state(uid, qs.get("courseId")),
                "/api/teacher/state": lambda: api.teacher_state(uid),
                "/api/teacher/materials": lambda: api.teacher_materials(uid),
                "/api/teacher/students": lambda: api.teacher_students(uid),
                "/api/teacher/preview": lambda: api.teacher_preview(uid, qs.get("q", "")),
            }
            fn = routes.get(path)
            if not fn:
                return self._send(404, _err("未知接口 %s" % path, "not_found"))
            return self._send(200, _ok(fn()))

        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._send(500, _err("%s: %s" % (type(e).__name__, e), "server_error"))

    # -------------------------------------------------- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        uid = self._uid()

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._send(400, _err("请求体不是合法 JSON"))

        try:
            if path == "/api/student/chat":
                text = (body.get("text") or "").strip()
                if not text:
                    return self._send(400, _err("问题不能为空"))
                return self._send(200, _ok(api.student_chat(uid, text)))

            if path == "/api/student/flow/submit":
                text = (body.get("text") or "").strip()
                if not text:
                    return self._send(400, _err("内容不能为空"))
                return self._send(200, _ok(
                    api.flow_submit(uid, body.get("courseId"), text)))

            if path == "/api/student/memory/fix":
                return self._send(200, _ok(api.memory_fix(
                    uid, body.get("id"), body.get("content") or "",
                    float(body.get("confidence") or 0.8))))

            if path == "/api/student/listen/mark":
                return self._send(200, _ok(api.listen_mark(
                    uid, body.get("courseId"), body.get("text") or "",
                    body.get("atSec") or 0)))

            if path == "/api/student/listen/finish":
                return self._send(200, _ok(api.listen_finish(
                    uid, body.get("courseId"), int(body.get("seconds") or 0))))

            if path == "/api/teacher/upload":
                return self._send(200, _ok(api.teacher_upload(
                    uid, body.get("filename") or "material.md",
                    body.get("content") or "")))

            if path == "/api/teacher/resolve":
                return self._send(200, _ok(
                    api.teacher_resolve(uid, body.get("question") or "")))

            return self._send(404, _err("未知接口 %s" % path, "not_found"))

        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._send(500, _err("%s: %s" % (type(e).__name__, e), "server_error"))

    # -------------------------------------------------- OPTIONS
    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")


def main():
    port = 8900
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ("--port", "-p") and i + 1 < len(args):
            port = int(args[i + 1])

    api.seed_if_empty()

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    st = api.brain.stats()
    print("=" * 62)
    print(" 作文分身 · Essay Agent Dual")
    print("=" * 62)
    print(" 学生端  http://localhost:%d/" % port)
    print(" 教师端  http://localhost:%d/teacher.html" % port)
    print(" 语料    %d 份文档 / %d 个片段" % (st["documents"], st["chunks"]))
    print(" LLM     %s" % ("已配置" if os.environ.get("LLM_API_KEY") else "未配置（用确定性组织）"))
    print("=" * 62)
    print("  Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        httpd.server_close()


if __name__ == "__main__":
    main()
