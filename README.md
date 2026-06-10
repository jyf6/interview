# 银发传记采访引导 Demo

这是一个用于验证「银发传记」采访引导模块的最小可用 Demo。当前版本包含后端 FastAPI 服务、静态测试前端、产品入场引导、开场白生成、卡片引导、采访对话和每轮情绪分析展示。

## 功能概览

- 自动入场：打开测试页后自动创建会话并展示开场白。
- 产品使用说明：每次进入页面自动弹出 5 步使用引导。
- 开场白生成：调用 DashScope 兼容 OpenAI 接口生成温和开场白。
- 卡片引导：支持「直接开始采访」和「我还没想好怎么说」两条路径。
- 采访对话：进入采访后持续与用户对话，引导补充经历细节。
- 情绪分析：每轮用户输入后调用模型做单条情绪分析，并把中文摘要展示在 AI 回复末尾。
- 测试页面：`demo/test_page.html` 是纯静态 HTML，可直接作为联调验证页面。

## 项目结构

```text
demo/
  main.py                     FastAPI 入口
  test_page.html              前端测试页面
  test_integration.py         集成测试脚本
  requirements.txt            Python 依赖
  .env.example                环境变量示例
  config/
    app_config.py             应用配置
    cards_config.py           卡片配置
    onboarding_config.py      产品使用说明配置
    prompts_config.py         提示词配置
  core/
    llm_client.py             DashScope LLM 客户端
    models.py                 Pydantic 数据模型
    session_manager.py        内存会话管理
    state_machine.py          状态机
  handlers/
    opening_handler.py        开场白处理
    guidance_handler.py       卡片引导处理
    interview_handler.py      采访对话处理
    emotion_handler.py        情绪分析处理
    onboarding_handler.py     产品使用说明处理
```

## 环境准备

建议使用 Python 3.12。

```powershell
cd demo
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

复制环境变量文件：

```powershell
Copy-Item .env.example .env
```

然后在 `demo/.env` 中填写：

```text
DASHSCOPE_API_KEY=你的 DashScope API Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
```

注意：`.env` 已加入 `.gitignore`，不要把真实 Key 提交到仓库。

## 启动后端

```powershell
cd demo
venv\Scripts\Activate.ps1
python main.py
```

服务默认运行在：

```text
http://127.0.0.1:8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

## 打开前端测试页

直接用浏览器打开：

```text
demo/test_page.html
```

如果浏览器跨域或文件协议限制影响测试，也可以在 `demo` 目录启动静态服务：

```powershell
python -m http.server 8010 --bind 127.0.0.1
```

然后访问：

```text
http://127.0.0.1:8010/test_page.html
```

## 主要接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/onboarding/guide` | 获取产品使用说明配置 |
| POST | `/api/session/start` | 创建会话并生成开场白 |
| POST | `/api/session/{id}/card` | 选择卡片 |
| POST | `/api/session/{id}/guidance` | 展示心理状态卡片 |
| POST | `/api/session/{id}/enter` | 进入采访阶段 |
| POST | `/api/session/{id}/chat` | 发送采访对话 |
| GET | `/api/session/{id}/status` | 查询会话状态 |

## 当前流程

```text
页面打开
  -> 自动加载产品使用说明
  -> 自动创建会话
  -> 生成开场白
  -> 用户选择开始采访或引导卡片
  -> 进入采访
  -> 每轮用户输入
      -> 单条情绪分析
      -> 采访回复生成
      -> 在回复末尾展示中文情绪摘要
```

情绪摘要示例：

```text
（情绪=怀念；风险=低；参与度=高；动作=柔和追问）
```

## 集成测试

先启动后端，然后运行：

```powershell
cd demo
venv\Scripts\Activate.ps1
python test_integration.py
```

## 后续可扩展方向

- 将内存会话存储替换为 Redis。
- 将长期状态和情绪报告沉淀到数据库。
- 将情绪分析与采访回复并行，降低每轮延迟。
- 接入专用采访 Agent 模型和独立情绪分析模型。
- 将 `test_page.html` 替换为正式产品前端模块。
