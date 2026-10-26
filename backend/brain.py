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
                    real, grams = _tokens(sent)
                    chunks.append({
                        "text": sent,
                        "source": rel,
                        "tokens": real,
                        "grams": grams,
                    })
    _CACHE["sig"] = sig
    _CACHE["chunks"] = chunks
    return chunks


_FRAG_RE = re.compile(
    r"^(?:什么|怎么|这个|那个|我们|你们|他们|可以|应该|因为|所以|但是|如果|就是|"
    r"今天|明天|昨天|现在|还是|已经|时候|的话|是什|么比|什|怎|吧|呢|吗)")
# 明显不属于教学内容领域的高频生活词：命中它们不算「老师讲过」
_OFFTOPIC = set("""
今天 明天 昨天 晚饭 午饭 早饭 吃饭 吃什么 比较好 天气 星期 手机 推荐 哪个好
好吃 睡觉 起床 上班 下班 周末 玩 游戏 电影 音乐 衣服 买 多少钱
""".split())

# 这些双字是疑问/语气/生活碎片，不能单独当作「老师讲过这个词」
_FRAG_HEADS = set("""
该怎 么练 怎么 什么 什 怎 是什 么比 样才 才能 能不 不能 不是 是不
这个 那个 哪些 哪个 如何 为什 么样 一些 一下 可以 应该 需要 是否
天晚 饭吃 天天 气怎 么学 好英 卷考 考什 新高 英语 学好
""".split())


def _tokens(text):
    """分词，返回 (真词集合, 双字召回集合)。

    _token_re 会把一整段连续中文贪婪吞成一个长串，所以列在这里的词
    都是「整句级」的，必须再切：
      - 双字滑窗 -> 召回用
      - 其中 2-4 字且非问句碎片的 -> 真词，用于算覆盖率
    覆盖率只看真词（「该怎」「么练」这类语法碎片不算老师讲过这个词）。
    """
    real, grams = set(), set()
    for t in _token_re.findall(text):
        is_cn = bool(re.match(r"[一-龥]", t))
        if not is_cn:
            if t.lower() not in _STOP:
                real.add(t.lower())
            continue

        # 长串先切双字窗口
        if len(t) >= 2:
            for i in range(len(t) - 1):
                bg = t[i:i + 2]
                if bg not in _STOP and bg not in _OFFTOPIC and not _FRAG_RE.match(bg):
                    grams.add(bg)
        # 整串本身若正好 2-4 字，也算真词（如「练字」「记叙文」）
        if 2 <= len(t) <= 4 and t not in _STOP and t not in _OFFTOPIC \
                and not _FRAG_RE.match(t):
            real.add(t)
    # 双字里那些明显是词（非碎片）的，也提升为真词
    for g in grams:
        if g not in _STOP and g not in _OFFTOPIC and not _FRAG_RE.match(g):
            real.add(g)
    # 疑问/语气类双字不是实词，避免「该怎」「么练」充数
    real = {w for w in real if w not in _FRAG_HEADS}

    # 真词必须「像词」：不接受由常见组合词拼出来的碎片（晚饭/比较/较好）
    real = {w for w in real if not any(w != s and w in s for s in _OFFTOPIC)}
    return real, grams


def stats():
    chunks = _load_chunks()
    sources = sorted({c["source"] for c in chunks})
    return {"chunks": len(chunks), "documents": len(sources), "sources": sources[:200]}


def retrieve(query, top_k=4, min_score=1):
    """BM25 风格打分：词重合 + 长度归一。返回按相关度排序的片段。"""
    chunks = _load_chunks()
    if not chunks:
        return []
    q_real, q_grams = _tokens(query)
    if not q_real and not q_grams:
        return []

    # 文档频率，用于判断词的区分度
    df = {}
    for c in chunks:
        for t in c.get("tokens", set()):
            df[t] = df.get(t, 0) + 1
        for t in c.get("grams", set()):
            df[t] = df.get(t, 0) + 1
    n = len(chunks)

    # 「常见词」：出现在 12% 以上片段里的词，几乎没有区分度
    COMMON_RATIO = 0.12
    common = {t for t, k in df.items() if k / float(n) >= COMMON_RATIO}

    # 问题的实词里，至少要有 1 个「不常见」的词能被命中，
    # 才算「老师真的讲过这个话题」。
    # 这样 「练字」 能命中（罕见词），「今天晚饭吃什么」 不能（全是常见词）。
    q_rare = {t for t in q_real if t not in common}
    if not q_rare:
        # 问题里全是常见词 -> 没有实质话题，判定没讲过
        return []

    scored = []
    for c in chunks:
        hit_rare = q_rare & c.get("tokens", set())
        if not hit_rare:
            continue

        # 打分：区分度越高的词权重越大；双字窗口做召回补充
        score = 0.0
        for t in hit_rare:
            score += 1.0 + (n / (1.0 + df.get(t, 1)))
        gram_hit = (q_grams & c.get("grams", set())) - hit_rare
        for t in gram_hit:
            score += 0.4 * (1.0 + (n / (1.0 + df.get(t, 1))))
        score = score / (1.0 + (len(c.get("tokens", ())) ** 0.5) * 0.06)

        coverage = len(hit_rare) / float(len(q_rare))
        if score < 6.0:
            continue
        scored.append((score, coverage, c))

    scored.sort(key=lambda p: -p[0])
    out, seen = [], set()
    for score, cover, c in scored:
        if c["text"] in seen:
            continue
        seen.add(c["text"])
        out.append({"text": c["text"], "source": c["source"],
                    "score": round(score, 2), "coverage": round(cover, 2)})
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
