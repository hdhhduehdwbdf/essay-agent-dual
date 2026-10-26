# -*- coding: utf-8 -*-
"""把原语料清洗后导入 essay-agent-dual/backend/knowledge/。

只收「老师原话」类内容（视频转写 + 课程目录 + 其他），
排除第三方平台页、人格调研总结、付费教材 PDF 全文。
品牌名与可核实个人事实全部清洗。

用法：python tools/import_corpus.py
"""
import os
import re

SRC = r"D:\自用型数字分身\原型\my_agent\knowledge"
DST = r"D:\自用型数字分身\essay-agent-dual\backend\knowledge"

# 收录的顶层目录
ALLOWED = {"视频文案", "课程", "其他"}

# 内容里出现这些关键词的文件直接排除（第三方平台页/盗版资源站/商业敏感信息）
BAN_WORDS = (
    "黑猫投诉", "天眼查", "投诉编号", "统一社会信用代码", "注册资本",
    "粉丝数", "获赞超", "万粉", "热浪数据",
    # 网盘盗版资源站页面，不能作为正式语料上线
    "百度网盘", "转存下载", "收集整理", "资源合计", "提取码", "VIP会员可",
)

# 品牌词替换（顺序很重要：先长后短）
BRAND_SUBS = [
    ("叁月聚粮", "私人教师"),
    ("三月聚粮", "私人教师"),
    ("武汉叁月聚粮教育科技有限公司", "私人教师"),
    ("叁月老师", "老师"),
    ("三月老师", "老师"),
    ("三月巨浪老师", "老师"),
    ("叁月", ""),
    ("三月", ""),
    ("聚粮", ""),
    ("sanyuejuliang", ""),
]

DATE_TAIL = re.compile(r"[（(]\d{4}-\d{1,2}-\d{1,2}[）)]")
URL_RE = re.compile(r"https?://\S+")
MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")

# 引流/营销句式：整句剔除（只删话术，不整篇排除）
PROMO_PAT = re.compile(
    r"[^。！？\n]*(?:蓝色链接|助教老师|助教阵容|答疑助教|资深助教|真人助教|自习老师|"
    r"试听我们的|免费领取|没有报名的同学|扫码|私信我|评论区.{0,6}链接|添加我们的|"
    r"换购|粉丝群|成为会员购买付费会员)[^。！？\n]*[。！？]?")


def clean_name(name):
    stem, ext = os.path.splitext(name)
    for a, b in BRAND_SUBS:
        stem = stem.replace(a, b)
    stem = stem.replace("聚粮", "").replace("叁", "").replace("#", " ").strip(" -_#")
    stem = re.sub(r"\s+", " ", stem)
    return (stem or "材料") + ".md"


# 与正文同一套替换
BRAND_SUBS = [
    ("叁月聚粮", ""), ("三月聚粮", ""),
    ("叁月老师", "老师"), ("三月老师", "老师"),
    ("三月巨浪老师", "老师"), ("三元老师", "老师"),
    ("叁月", ""), ("三月", ""),
]


def force_scrub(text):
    """品牌名强制替换：出现即改，绝不因此排除整篇。

    规则：完整品牌名 -> 「老师」；零散字词 -> 删除。
    改完再兜一次，确保不残留。
    """
    # 完整品牌名（含常见变体、错别字）先统一成「老师」
    for pat in ("叁月聚粮", "三月聚粮", "叁月聚粮教育", "武汉叁月聚粮教育科技有限公司",
                "三月巨浪", "叁月老师", "三月老师", "三元老师", "叁月姐姐", "三月姐姐"):
        text = text.replace(pat, "老师")
    # 平台账号名
    text = re.sub(r"@?\S*(?:聚粮|sanyuejuliang)\S*", "老师", text, flags=re.I)
    # 零散残留（「叁思」等课程名里的字）
    text = text.replace("叁思", "思辨").replace("叁", "").replace("聚粮", "")
    return text


def clean_content(text):
    # markdown 外链 -> 纯文本（去 URL）
    text = MD_LINK.sub(lambda m: m.group(1), text)
    text = URL_RE.sub("", text)
    text = DATE_TAIL.sub("", text)
    # 引流话术整句剔除
    text = PROMO_PAT.sub("", text)
    for a, b in BRAND_SUBS:
        text = text.replace(a, b)
    text = text.replace("聚粮", "")
    text = text.replace("三元老师", "老师")
    # 音转错别字
    text = text.replace("繁景式", "范式").replace("一力万用", "一例万用")

    # 去掉视频源文件行、平台抓取元数据
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if re.search(r"video\.mp4|\.mp4\b|Uz[A-Za-z0-9_]+|userfiles|\bvideo\b", s):
            continue
        if re.match(r"^(source|crawled_at|task_id|expert_name|dimension|title):", s):
            continue
        if re.match(r"^-?\s*(课程编号|课程标签|课程大小|课程格式|下载方式)", s):
            continue
        lines.append(ln)
    text = "\n".join(lines)

    # 清掉品牌删除后留下的空壳：【】、《》、##、@@、连续空格
    text = re.sub(r"【\s*】|《\s*》|\(\s*\)|（\s*）", "", text)
    text = re.sub(r"[#@]{1,}[\s\d]*#", "", text)
    text = re.sub(r"[#@]+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([，。！？、])", r"\1", text)
    # 标题开头残留的省略号
    text = re.sub(r"^\s*[.．·]{2,}\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    os.makedirs(DST, exist_ok=True)
    # 清空目标目录（保留现有示例语料会被同名覆盖）
    for root, dirs, files in os.walk(DST, topdown=False):
        for fn in files:
            os.remove(os.path.join(root, fn))
        for d in dirs:
            os.rmdir(os.path.join(root, d))

    kept, excluded = 0, []
    for top in sorted(os.listdir(SRC)):
        top_path = os.path.join(SRC, top)
        if not os.path.isdir(top_path) or top not in ALLOWED:
            continue
        out_dir = os.path.join(DST, top)
        os.makedirs(out_dir, exist_ok=True)
        for fn in sorted(os.listdir(top_path)):
            if not fn.lower().endswith((".md", ".txt")):
                continue
            src_path = os.path.join(top_path, fn)
            try:
                with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw = f.read()
            except OSError:
                continue

            if any(w in raw for w in BAN_WORDS):
                print("  [排除-第三方平台页] " + fn)
                continue

            body = clean_content(raw)
            # 品牌残留：强制替换掉，不排除整篇
            body = force_scrub(body)
            if len(body) < 60:
                print("  [排除-内容过短] " + fn)
                continue

            stem, ext = os.path.splitext(fn)
            cname = stem
            for a, b in BRAND_SUBS:
                cname = cname.replace(a, b)
            cname = cname.replace("聚粮", "").replace("#", " ").strip(" -_") or "材料"

            out_path = os.path.join(out_dir, cname + ext)
            i = 2
            while os.path.exists(out_path):
                out_path = os.path.join(out_dir, "%s (%d)%s" % (cname, i, ext))
                i += 1

            with open(out_path, "w", encoding="utf-8") as f:
                f.write(body)
            kept += 1

    print("导入完成：%d 份 -> %s" % (kept, DST))


if __name__ == "__main__":
    main()
