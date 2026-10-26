# -*- coding: utf-8 -*-
"""分身大脑：检索教师语料 → 组织回答（带出处）→ 没命中就明说没讲过。

设计原则（这是产品的核心承诺，不是技术细节）：
1. 每句回答都要能追溯到某份材料的原文片段，否则不回答；
2. 检索不到就返回 grounded=False，前端展示「老师没讲过 + 转给老师」；
3. 不依赖任何 LLM 即可完整跑通；配置了 LLM_API_KEY 则用它把片段组织得更自然。
"""
import json
import os
import re
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.environ.get("APP_KNOWLEDGE_DIR") or os.path.join(BASE_DIR, "knowledge")

# 分句：中文标点。检索粒度到「句」，因为出处要精确到老师原话。
_SPLIT_RE = re.compile(r"[。！？\n]+")
_token_re = re.compile(r"[一-龥]{2,}|[A-Za-z]{2,}")

_CACHE = {"sig": None, "chunks": []}

# 常见虚词，参与检索会拉低准确率
_STOP = set("这个 那个 什么 怎么 我们 你们 他们 可以 应该 因为 所以 但是 如果 就是 "
            "一个 没有 不是 这样 那样 现在 还是 已经 自己 时候 问题 老师 学生".split())


def _signature():
    parts = []
    if not os.path.isdir(KNOWLEDGE_DIR):
        return "empty"
    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for fn in sorted(files):
            if fn.lower().endswith((".md", ".txt")):
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                    parts.append("%s:%d:%d" % (fn, st.st_size, int(st.st_mtime)))
                except OSError:
                    pass
    return "|".join(parts) or "empty"


def _load_chunks():
    sig = _signature()
    if _CACHE["sig"] == sig:
        return _CACHE["chunks"]

    chunks = []
    if os.path.isdir(KNOWLEDGE_DIR):
        for root, _, files in os.walk(KNOWLEDGE_DIR):
            for fn in sorted(files):
                if not fn.lower().endswith((".md", ".txt")):
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, KNOWLEDGE_DIR).replace("\\", "/")
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        raw = f.read()
                except OSError:
                    continue
                # 去掉 markdown 标记，正文才是老师原话
                body = re.sub(r"^#{1,6}\s*", "", raw, flags=re.M)
                body = re.sub(r"[*_`>]", "", body)
                for sent in _SPLIT_RE.split(body):
                    sent = sent.strip()
                    if len(sent) < 8:
                        continue
                    chunks.append({
                        "text": sent,
                        "source": rel,
                        "tokens": _tokens(sent),
                    })
    _CACHE["sig"] = sig
    _CACHE["chunks"] = chunks
    return chunks


def _tokens(text):
    out = set()
    for t in _token_re.findall(text):
        if t not in _STOP:
            out.add(t)
        # 中文再切双字，提升召回
        if len(t) > 2 and re.match(r"[一-龥]", t):
            for i in range(len(t) - 1):
                bg = t[i:i + 2]
                if bg not in _STOP:
                    out.add(bg)
    return out


def stats():
    chunks = _load_chunks()
    sources = sorted({c["source"] for c in chunks})
    return {"chunks": len(chunks), "documents": len(sources), "sources": sources[:200]}


def retrieve(query, top_k=4, min_score=1):
    """BM25 风格打分：词重合 + 长度归一。返回按相关度排序的片段。"""
    chunks = _load_chunks()
    if not chunks:
        return []
    q_tokens = _tokens(query)
    if not q_tokens:
        return []

    # 文档频率，用于降权高频词
    df = {}
    for c in chunks:
        for t in c["tokens"]:
            df[t] = df.get(t, 0) + 1
    n = len(chunks)

    scored = []
    for c in chunks:
        hit = q_tokens & c["tokens"]
        if not hit:
            continue
        score = 0.0
        for t in hit:
            idf = 1.0 + (n / (1.0 + df.get(t, 1)))
            score += idf
        score = score / (1.0 + (len(c["tokens"]) ** 0.5) * 0.06)
        if score >= min_score:
            scored.append((score, c))

    scored.sort(key=lambda p: -p[0])
    out, seen = [], set()
    for score, c in scored:
        if c["text"] in seen:
            continue
        seen.add(c["text"])
        out.append({"text": c["text"], "source": c["source"], "score": round(score, 2)})
        if len(out) >= top_k:
            break
    return out


def _llm_compose(question, hits):
    """可选：用 LLM 把片段组织成老师口吻。失败或未配置就返回 None。"""
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    ctx = "\n".join("[%d] %s" % (i + 1, h["text"]) for i, h in enumerate(hits))
    prompt = (
        "你是这位老师的教学分身。只能依据下面这些老师的原话回答，"
        "不要补充材料里没有的内容，不要编造。用老师自己的口吻，先给判断再给理由。\n\n"
        "老师的原话：\n%s\n\n学生问：%s\n\n"
        "要求：回答在 120 字内；每处引用后面标 [序号]。" % (ctx, question)
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 400,
    }).encode("utf-8")

    req = urllib.request.Request(
        base, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return None


def answer(question, top_k=4):
    """返回 {grounded, text, hits, mode}。grounded=False 表示老师没讲过。"""
    hits = retrieve(question, top_k=top_k)

    if not hits:
        return {
            "grounded": False,
            "text": "老师的材料里没有讲过这个话题，我不替他猜。",
            "hits": [],
            "mode": "ungrounded",
        }

    composed = _llm_compose(question, hits)
    if composed:
        return {"grounded": True, "text": composed, "hits": hits, "mode": "llm"}

    # 无 LLM 时的确定性组织：引用最相关的两段原话
    lead = hits[0]["text"]
    parts = ["老师讲过这个，原话是：", "「%s」[1]" % lead]
    if len(hits) > 1 and hits[1]["text"] != lead:
        parts.append("「%s」[2]" % hits[1]["text"])
    return {"grounded": True, "text": "\n\n".join(parts), "hits": hits, "mode": "extractive"}
