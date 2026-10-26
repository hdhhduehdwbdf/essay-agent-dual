# -*- coding: utf-8 -*-
"""五环节作文教练：每个环节做单点诊断，通过才放行。

关键设计（来自产品决策，不是技术选择）：
- 一次只给一处真问题。一次倒四个维度的意见，学生不会看。
- 每个环节都要学生交一次东西才往前走，不能自动跑完——教育要留学习动作。
- 诊断要引用老师语料，没命中就退回通用规则，并标记 grounded=False。
"""
import re

from . import brain

STAGES = [
    {
        "key": "draft",
        "name": "交一稿",
        "hint": "把完整一稿发我",
        "greeting": "你好。这篇我们先不急着改，你先把完整一稿发给我，我通读一遍再说。",
        "ask": "把完整一稿贴进来就行。",
    },
    {
        "key": "topic",
        "name": "审题",
        "hint": "你觉得题目在问什么",
        "greeting": "一稿看完了。先确认题目：你觉得这个题最关键的限定是什么？",
        "ask": "说说你理解的题意，一句话就行。",
    },
    {
        "key": "material",
        "name": "选材与立意",
        "hint": "你写的是什么事",
        "greeting": "审题清楚了。现在说说：你写了一件什么事？想表达什么？",
        "ask": "讲一下你选的那件事。",
    },
    {
        "key": "structure",
        "name": "篇章结构",
        "hint": "把情节按顺序列出来",
        "greeting": "立意清晰了。把你想写的关键情节按顺序列出来，不用写完整句子。",
        "ask": "按顺序列几个情节就行。",
    },
    {
        "key": "describe",
        "name": "叙述与描写",
        "hint": "挑一个重点段写透",
        "greeting": "结构搭好了。挑一个重点段，把它写具体。",
        "ask": "把那个重点段写出来。",
    },
]

# 每个环节的诊断规则：命中即作为「这一处真问题」
RULES = {
    "draft": [
        (r"我很难过|我很开心|我很生气|我特别|非常难过", "情绪直接说出来，没有换成动作。",
         "把「我很难过」这种句子找出来，改成她做了什么、你怎么看见的。"),
        (r"从此以后|这件事让我明白|我懂得了一个道理", "结尾在讲道理，不在写事。",
         "把最后一段的道理删掉，换成一个画面收尾。"),
        (r"在生活中|我们常常|每个人都会", "开头是套话，不是场景。",
         "第一句直接写一个具体时刻，别铺垫。"),
    ],
    "topic": [
        (r"就是|无非|指的|意思", "你把题意收窄成了一种解释。",
         "题目往往给了好几条路，先确认你走的是哪一条，再动笔。"),
        (r"我觉得|应该是|大概是", "你在猜题意，不是在读题。",
         "把题目的限定词圈出来：谁、在什么关系里、发生了什么变化。"),
    ],
    "material": [
        (r"他原谅|她原谅|道歉|认错", "故事写成了单向道歉，立意天花板在二类。",
         "给对方一个也退了一步的动作，双向让步才到一类。"),
        (r"绝症|车祸|去世|转学|重逢", "选材踩了高频套路。",
         "换一个更小、更真、有转折的切口。"),
    ],
    "structure": [
        (r"然后|接着|后来|最后", "情节是直线推进，缺一个停顿。",
         "在转折前加一次「你以为不会好了」的时刻。"),
    ],
    "describe": [
        (r"^(?!.*[，。])", "内容太短，还看不出描写。", "多写两句具体的动作和环境。"),
        (r"很|非常|特别|十分", "你在用程度词代替描写。",
         "把程度词换成一个可观察的动作。"),
    ],
}

DEFAULT_DIAG = {
    "draft": ("先把文章完整读一遍，再谈改哪里。", "把一稿贴全，包括你觉得写得不好的部分。"),
    "topic": ("题意的关键在限定词，不在题眼。", "圈出题目里的限定词：谁、在什么关系里、发生了什么变化。"),
    "material": ("素材要真、要小、要有一个能写的变化瞬间。", "找一个真实发生过、切口还小的瞬间。"),
    "structure": ("结构要有节奏，不能一路平推。", "把情节按「冲突—停顿—松动」三段摆一遍。"),
    "describe": ("描写是把情绪换成动作。", "挑一处情绪，只写动作、神态和环境，不写你怎么想。"),
}


def _pick_rule(stage_key, text):
    for pattern, problem, action in RULES.get(stage_key, []):
        if re.search(pattern, text, flags=re.M):
            return problem, action
    return DEFAULT_DIAG[stage_key]


def diagnose(stage_key, student_text, course_title=""):
    """单点诊断。返回 {problem, action, grounded, hits, excerpt}。"""
    problem, action = _pick_rule(stage_key, student_text)

    # 从老师语料里找同样话题的原话，作为「老师说过」的依据
    probe = "%s %s %s" % (course_title, STAGES_BY_KEY[stage_key]["name"], problem)
    hits = brain.retrieve(probe, top_k=2, min_score=2)

    excerpt = ""
    if hits:
        excerpt = hits[0]["text"]

    return {
        "problem": problem,
        "action": action,
        "grounded": bool(hits),
        "hits": hits,
        "excerpt": excerpt,
    }


STAGES_BY_KEY = {s["key"]: s for s in STAGES}


def stage_by_index(i):
    if 0 <= i < len(STAGES):
        return STAGES[i]
    return STAGES[-1]


def total_stages():
    return len(STAGES)
