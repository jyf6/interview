# Interview Agent

FastAPI + Redis + DashScope + Vue 3 application for the silver-age biography interview module.

This version implements an outline-driven, text-only biography interview flow:

- A typed highlight story generates a draft outline of chapters and collection points.
- Draft outlines can be edited and published before an interview starts.
- Redis stores resumable session state; SQLAlchemy ORM persists outlines and archived material in PostgreSQL.
- Text turns follow hook, detail follow-up, meaning, and explainable close conditions.
- Cross-topic memories use an interrupt/resume thread stack and are archived by target stage.

## Environment

Create and install dependencies in the project-local virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm.cmd ci --cache .\.npm-cache
```

## Configuration

Copy `.env.example` to `.env` and fill your local values:

```env
REDIS_URL=redis://localhost:6379/0
BIOGRAPHY_DATABASE_URL=postgresql://interview:interview@localhost:5432/interview
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
DASHSCOPE_INTERVIEW_MODEL=qwen-plus
```

`DASHSCOPE_API_KEY` and `DASHSCOPE_INTERVIEW_MODEL` are required. Missing configuration or any model invocation failure is returned as an error; the application does not generate local substitute content.

## Start

Start PostgreSQL and Redis with Docker:

```powershell
.\scripts\start-redis.bat
```

Then start the backend. The backend script also ensures Redis is running:

```powershell
.\scripts\start-backend.bat
```

Start the frontend test page:

```powershell
.\scripts\start-frontend.bat
```

Useful URLs:

- Frontend: http://127.0.0.1:5173
- API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/v1/health

You can also start both windows together:

```powershell
.\scripts\start-all.bat
```

## Main Flow

The frontend calls these endpoints:

```http
POST /api/v1/biographies
POST /api/v1/biographies/{biography_id}/highlight-sessions
POST /api/v1/biographies/{biography_id}/highlight-sessions/{session_id}/messages
GET  /api/v1/outlines/{outline_id}
PUT  /api/v1/outlines/{outline_id}
POST /api/v1/outlines/{outline_id}/publish
POST /api/v1/interview/sessions
POST /api/v1/interview/dialog/text
POST /api/v1/interview/sessions/{session_id}/commands
GET  /api/v1/interview/sessions/{session_id}/materials
```

Flow:

```text
Text highlight
  -> draft outline
  -> edit and publish
  -> collection point interview
  -> interrupt/resume and silent archive
  -> next point
  -> end
```

Redis state machine states:

```text
INIT
OPENING_GENERATING
OPENING_DELIVERED
GUIDANCE_CARD
READY_TO_INTERVIEW
INTERVIEWING
end
```

## Verification

Commands used for local verification:

```powershell
.\.venv\Scripts\python.exe -m py_compile app\core\config.py app\core\llm_client.py app\prompts\loader.py app\schemas\interview.py app\services\dashscope_llm.py app\services\interview_agent_service.py app\services\interview_state_machine.py app\services\langgraph_redis_checkpoint.py app\services\opening_service.py app\api\v1\routes\interview.py app\main.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_biography_flow.py tests/test_collection_point_evaluator.py tests/test_semantic_router.py tests/test_thread_stack.py
cd frontend
npm.cmd run build
docker compose -p interview-agent exec -T postgres pg_isready -U interview -d interview
docker compose -p interview-agent exec -T redis redis-cli ping
```
