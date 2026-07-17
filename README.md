# 传记采集平台

这是一个面向口述传记素材采集的 FastAPI + Vue 3 应用。当前可执行主链路不是按人生阶段逐轮提问，而是先由用户讲述一段高光经历，生成并发布传记大纲，再按大纲中的“采集点”逐段收集素材。

本文只描述当前代码实际可达的运行行为。仓库中仍保留开场卡片、S1-S7 人生阶段和 LangGraph 父子图等旧实现；它们的状态与当前主链路见“保留的旧链路”。

## 技术组成

| 层级 | 实现 | 职责 |
| --- | --- | --- |
| Web 前端 | Vue 3、Vite、Lucide | 高光访谈、大纲编辑发布、采集点文本对话 |
| HTTP API | FastAPI | 会话、传记、大纲和采集点接口 |
| 临时状态 | Redis | 高光访谈会话、文本会话、消息和进度 |
| 持久化 | PostgreSQL + SQLAlchemy | 传记、大纲版本、采集点与已归档素材 |
| 模型 | DashScope OpenAI 兼容接口 | 仅用于生成大纲草稿；旧链路还会用于开场、引导和阶段采访 |

入口文件 [app/main.py](app/main.py) 在生命周期内创建 Redis 客户端和 `BiographyStore`，后者会执行 `Base.metadata.create_all()` 创建表。前端从 [frontend/src/App.vue](frontend/src/App.vue) 启动，首屏固定为“大纲”页。

## 当前主链路

```text
大纲页
  -> 创建传记
  -> 启动高光访谈
  -> 规则驱动的多轮补问
  -> LLM 生成大纲草稿
  -> 修改并发布大纲
  -> 创建采集点会话
  -> 逐采集点收集/归档素材
  -> 所有采集点完成，结束会话
```

### 1. 创建传记和高光访谈

1. 用户点击“开始聊天”，`useOutlineConsole.startHighlight()` 依次调用：
   - `POST /api/v1/biographies` 创建 `biographies` 记录；
   - `POST /api/v1/biographies/{biography_id}/highlight-sessions` 创建高光访谈会话。
2. `HighlightInterviewService.start()` 在 Redis 的 `interview:highlight:{session_id}` 保存会话。初始消息固定为“从一段最自豪、最难忘或最想留下来的经历说起”。
3. 每次 `POST .../highlight-sessions/{session_id}/messages`：
   - 将用户文本和已有消息交给 `CollectionPointEvaluator`；
   - 用关键词识别 `when/where/people/trigger/action/outcome/feeling/meaning` 等槽位；
   - 未满足结束条件时，按第一个缺失槽位返回固定追问；
   - 用户文本包含“说完了、没有了、就这些、差不多”，或至少两轮且覆盖率不低于 `0.65` 并包含 `meaning` 时，进入大纲生成。
4. 收束时，`OutlineService.create_draft()` 调用 DashScope，要求模型返回 3-8 章、每章 1-3 个采集点的 JSON。`BiographyStore.save_outline()` 将其保存为一份 `draft` 版本。

### 2. 编辑、发布和创建采集点会话

1. 大纲页可直接编辑章节标题、采集点标题和引入问题，调用 `PUT /api/v1/outlines/{outline_id}` 覆盖草稿的全部采集点。
2. `POST /api/v1/outlines/{outline_id}/publish` 仅在至少有一个采集点时将状态从 `draft` 改为 `published`。
3. 点击“开始采集点采访”后，前端调用 `POST /api/v1/interview/sessions`。
4. `InterviewStateMachine.start_outline_session()` 校验大纲已发布且属于传入的 `biography_id`，删除该 `session_id` 的旧 Redis 访谈进度和消息，将状态设为 `INTERVIEWING`，并把扁平化大纲中的第一个采集点写入 `active_point`。
5. 接口返回该采集点的 `hook`；前端切换到聊天页并将其加入本地消息列表。

### 3. 采集点文本回合

前端发送 `POST /api/v1/interview/dialog/text`。`InterviewStateMachine.handle_dialog_text()` 的实际分支如下：

1. 若会话没有 `outline_id` 或 `active_point`，记录用户文本后返回“请先在大纲页面生成并发布大纲”；不会进入阶段采访。
2. 若当前存在 `diversion`，进入岔题素材收集。
3. 否则 `UnifiedSemanticRouter.classify_outline()` 先做确定性路由：
   - 文本为空、很短、包含“跳过/不想说/别问了/换个话题”等，分别产生低参与、跳过或抵触结果；
   - 文本中精确包含另一个采集点标题且有事件标记，或命中 S1-S7 关键词且事件边界足够，可能产生 `cross_topic_event`；
   - 其他情况留在当前采集点。
4. 正常采集使用 `CollectionPointEvaluator` 检查本轮文本与已覆盖槽位，返回第一个缺失槽位对应的固定问题。这里不调用 LLM。
5. 出现跳过/抵触、用户主动收束，或覆盖达到结束规则时：
   - 通过 `BiographyStore.archive_material()` 将当前采集点的用户文本、覆盖率与槽位结果写入 `material_fragments`；
   - 使用 `next_point()` 切换到下一个采集点；最后一个采集点结束时将会话状态转为 `end`。
6. 用户跨题时，`ThreadStack.push()` 保存当前采集点快照并创建 `diversion`。岔题素材达到结束条件后写入 `material_fragments`，再由 `ThreadStack.pop()` 恢复原采集点。

`POST /api/v1/interview/sessions/{session_id}/commands` 还支持 `complete_point`、`push` 和 `pop` 命令。当前前端的“完成本段”按钮位于被隐藏的信息页，因此正常页面只能依赖自动收束来推进采集点。

## 数据与会话

### PostgreSQL

| 表 | 作用 |
| --- | --- |
| `biographies` | 传记根记录及可选采访对象 ID |
| `outline_versions` | 高光故事生成的大纲版本和发布状态 |
| `collection_points` | 章节下的采集点、引入问题和目标槽位 |
| `material_fragments` | 完成采集点或岔题后归档的素材与槽位评估 |

数据模型位于 [app/db/models.py](app/db/models.py)，数据库读写边界位于 [app/services/biography_store.py](app/services/biography_store.py)。

### Redis

| Key | 内容 | TTL |
| --- | --- | --- |
| `interview:highlight:{session_id}` | 高光访谈的消息、槽位、评估和草稿 | `SESSION_TTL_SECONDS` |
| `interview:state:{session_id}` | 当前流程状态字符串 | `SESSION_TTL_SECONDS` |
| `interview:state_interview:{session_id}` | 采集点、岔题栈、槽位和进度 JSON | `SESSION_TTL_SECONDS` |
| `interview:messages:{session_id}` | 文本访谈消息列表 | `SESSION_TTL_SECONDS` |
| `userinfo:{user_id}` | 旧开场功能使用的用户资料 Hash | `SESSION_TTL_SECONDS` |

`InterviewSessionStore` 对 Redis 网络错误进行一次重试，对 `WRONGTYPE` 会删除冲突键后继续。当前状态只持久化为字符串；`created_at`、`updated_at` 和 `previous_state` 并不会跨请求恢复。

## API 一览

| 方法 | 路径 | 当前用途 |
| --- | --- | --- |
| POST | `/biographies` | 创建传记 |
| POST | `/biographies/{id}/highlight-sessions` | 创建或恢复高光访谈 |
| POST | `/biographies/{id}/highlight-sessions/{session_id}/messages` | 发送高光故事文本 |
| GET/PUT | `/outlines/{outline_id}` | 读取或整体替换草稿 |
| POST | `/outlines/{outline_id}/publish` | 发布大纲 |
| POST | `/interview/sessions` | 基于已发布大纲创建采集点会话 |
| POST | `/interview/dialog/text` | 当前采集点的文本回合 |
| POST | `/interview/sessions/{session_id}/commands` | 完成采集点或操作岔题栈 |
| GET | `/interview/sessions/{session_id}/materials` | 列出已归档素材 |

另有 `/interview/dialog/start`、`/interview/dialog/opening/{session_id}`、`/interview/dialog/actions`、用户资料和状态查询接口。它们服务于保留的旧链路，不是当前前端首屏所走的流程。

## 保留的旧链路

仓库仍有一套阶段式采访实现：

- `app/graphs/interview_parent_graph.py` 与 `app/graphs/interview_stage_subgraph.py` 定义 LangGraph 父子图；
- `app/data/interview_stage_config.py` 定义 S1-S7 人生阶段；
- `app/services/interview_agent_service.py`、`app/prompts/interview/founder-*.md` 和情绪提示词实现模型路由、主问题、扩展追问和阶段总结；
- `POST /interview/dialog/start`、开场 SSE 与卡片接口仍可创建旧会话。

但在 `handle_dialog_text()` 中，采集点校验后的 `return await self._handle_outline_turn(...)` 位于旧 LangGraph 调用之前。因此旧会话第一次发送文本只会得到“请先在大纲页面生成并发布大纲”，其后的阶段图代码无法到达。当前实现应把这套代码视为待处理的历史实现，而不是已上线能力。

## 本地运行

### 前置条件

- Python 3.12；
- Node.js 22（Vite 7 的锁定版本要求 Node `^20.19.0 || >=22.12.0`）；
- Docker，用于 PostgreSQL 16 与 Redis 7；
- DashScope API Key。只有生成大纲草稿需要它；旧开场/引导/阶段链路也需要它。

### 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

docker compose -p interview-agent up -d postgres redis

cd frontend
npm.cmd ci --cache .\.npm-cache
cd ..

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端启动前端：

```powershell
cd frontend
npm.cmd run dev
```

可使用 `scripts/start-backend.bat`、`scripts/start-frontend.bat` 或 `scripts/start-all.bat`。尽管脚本名为 `start-redis.bat`，它实际上会同时启动 PostgreSQL 和 Redis。

服务地址：

- 前端：`http://127.0.0.1:5173`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

关于现有测试、CI、旧链路与工程治理问题，见 [整改方向.md](整改方向.md)。
