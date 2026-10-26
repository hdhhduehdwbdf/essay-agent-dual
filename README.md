# 作文分身 · Essay Agent Dual

一个**教师端 + 学生端分离**的作文教学 Agent 应用。

老师把手上的讲义、录课文案传进来，系统生成一个**只会引用老师原话**的分身：学生问到讲过的，它带出处回答；问到没讲过的，它明说「老师没讲过」并转给老师。

> 核心承诺：**每句话都能追溯到老师，做不到的地方明说。** 这是产品与通用助手的根本区别，也是本仓库所有技术选择的出发点。

---

## 这是什么

两端同一套液态玻璃视觉，共用同一个后端：

| 端 | 入口 | 做什么 |
|---|---|---|
| 学生端 | `/` | 首页作业横条、五环节作文打磨、分身对话（带出处）、记忆画像、帮我听课 |
| 教师端 | `/teacher.html` | 三份材料冷启动、分身初稿可编辑、以学生视角试聊、发布班级码、控制台 |

### 五个关键产品决策（都写进了代码）

1. **首屏绝不空** —— 学生进来时老师的作业已经在等他了。通用助手的首页是空的，教育产品不是。
2. **没讲过就直说** —— 检索不到语料返回 `grounded: false`，前端展示「老师没讲过 + 转给老师」，绝不编造。
3. **引用可追溯** —— 回答里的 `[1][2]` 能点开，看到的是老师材料里的真实原文片段和文件名。
4. **一次只给一处问题** —— 五环节每步只诊断一个真问题 + 一个可执行动作。一次倒四个维度，学生不会看。
5. **冷启动不假装** —— 三份材料就能开工；L2「学得像」明确标「未开启 · 差得远」，不吹「越用越像」。

---

## 快速开始

只需要 **Python 3.8+**，零第三方依赖。

```bash
cd essay-agent-dual
python backend/server.py
```

然后打开：

- 学生端 <http://localhost:8900/>
- 教师端 <http://localhost:8900/teacher.html>

换端口：

```bash
python backend/server.py --port 8901
```

> Windows 上如果 `python` 找不到，用完整路径或先确认 Python 已加入 PATH。

### 可选：接入大模型

不配也能完整跑通（用确定性的抽取式组织：直接引用最相关的老师原话）。想让回答更自然，配置环境变量即可：

```bash
# DeepSeek 为例，任何 OpenAI 兼容端点都行
set LLM_API_KEY=sk-xxxx
set LLM_BASE_URL=https://api.deepseek.com/v1/chat/completions
set LLM_MODEL=deepseek-chat
```

配了之后，回答由模型基于检索到的老师原话组织；**检索不到时仍然拒绝回答**。

---

## 自己跑一遍联调测试

后端启动后，另开一个终端：

```bash
python backend/smoke_test.py --port 8900
```

覆盖学生端与教师端全部接口，共 35 项断言，包含「命中带出处」「未命中不编造」「上传后立即可检索」等关键行为。

```
通过 35 项，失败 0 项
```

---

## 目录结构

```
essay-agent-dual/
├─ backend/
│  ├─ server.py        # 零依赖 HTTP 服务：静态文件 + JSON API
│  ├─ api.py           # 业务接口层，含种子数据
│  ├─ brain.py         # 分身大脑：检索语料 → 组织带出处的回答
│  ├─ coach.py         # 五环节作文教练：单点诊断规则
│  ├─ memory.py        # 记忆层：综合分淘汰、冲突消解、容量控制
│  ├─ store.py         # SQLite 存储层（标准库 sqlite3）
│  ├─ smoke_test.py    # 端到端联调测试
│  └─ knowledge/       # 老师语料（示例为原创虚构内容）
├─ web/
│  ├─ student.html     # 学生端（单文件）
│  ├─ teacher.html     # 教师端（单文件）
│  └─ api.js           # 共用 API 客户端
└─ data/               # SQLite 数据库（自动生成，不入库）
```

---

## 接口一览

所有响应统一为 `{"ok": true, "data": ...}` 或 `{"ok": false, "error": "..."}`。
当前用户从请求头 `X-User-Id` 取（演示级鉴权，无密码）。

### 学生端

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/student/home` | 学生、老师、作业横条 |
| GET | `/api/student/courses` | 课程列表与环节进度 |
| GET | `/api/student/memory` | 记忆分组 + 今天我学到的 |
| POST | `/api/student/memory/fix` | 修改一条记忆 |
| POST | `/api/student/chat` | 分身对话（带出处 / 未命中兜底） |
| GET | `/api/student/flow` | 五环节当前状态与历史消息 |
| POST | `/api/student/flow/submit` | 提交并获取单点诊断 |
| POST | `/api/student/listen/mark` | 记录一个「没懂」点 |
| POST | `/api/student/listen/finish` | 生成课后笔记 |

### 教师端

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/teacher/state` | 控制台：材料数、答不上来清单、L1/L2 |
| GET | `/api/teacher/materials` | 已加载的语料统计 |
| GET | `/api/teacher/students` | 学生与各自环节进度 |
| GET | `/api/teacher/preview?q=` | 以学生视角试聊 |
| POST | `/api/teacher/upload` | 上传一份材料，立即参与检索 |
| POST | `/api/teacher/resolve` | 标记某个答不上来的问题已处理 |

---

## 检索是怎么工作的

`brain.py` 里没有向量库，也没有外部依赖：

1. 把 `knowledge/` 下所有 `.md`/`.txt` 按中文标点切成句子（出处要精确到「老师原话」这一级）。
2. 分词：中文按词组 + 双字滑窗，英文按单词，去掉常见虚词。
3. 打分：命中词的 IDF 加权和，除以长度归一（BM25 风格的简化版）。
4. 低于阈值 → `grounded: false`，不回答。

材料改动会自动失效缓存（按文件名 + 大小 + 修改时间做签名），上传后立刻能检索到。

---

## 记忆是怎么淘汰的

不是「最旧先死」。每条记忆算一个 0~1 的综合分：

```
score = 0.35 × 置信度
      + 0.25 × 新鲜度（半衰期 60 天）
      + 0.25 × 被想起次数
      + 0.15 × 是否置顶
```

容量满了淘汰分数最低的。这样「用户在准备 2027 年高考」这种 89 天没再提但极重要的画像，不会先被删掉。

新旧冲突显式消解：新记忆取代旧记忆时，旧的那条保留但标记 `superseded_by`，前端显示「↑ 替换了『主攻议论文』」。

---

## 说明

- **语料**：`backend/knowledge/` 里是**原创虚构**的示例教学内容，用于演示检索链路。换成你自己的讲义即可，格式要求 `.md` 或 `.txt`，纯文本。
- **鉴权**：演示级。正式使用需接入真实登录，并把 `X-User-Id` 换成服务端会话。
- **数据**：默认存 SQLite（`data/app.db`），删掉即可重置。
- 本项目为产品原型与工程演示，不含真实用户数据。

## License

MIT
