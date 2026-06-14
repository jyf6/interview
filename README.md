# Interview Agent

FastAPI + Redis + DashScope + Vue 3 application for the silver-age biography interview module.

This version follows the current `jin` branch structure:

- Backend owns the Redis-backed state machine, opening dialog, guidance cards, and formal interview turns.
- Frontend is only a lightweight test page that adapts to backend dialog endpoints.
- Guidance-card generation and formal interview replies share `DASHSCOPE_INTERVIEW_MODEL`.
- Interview prompts are managed in `app/prompts/interview/` and referenced through `app/prompts/interview_prompts.py`.
- Formal interview replies use Redis-backed S0-S5 interview stages.

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
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
DASHSCOPE_INTERVIEW_MODEL=qwen-plus
```

`DASHSCOPE_INTERVIEW_MODEL` is used by the opening generator, guidance-card generator, and interview agent. If no DashScope key is configured, the backend returns local fallback replies so the flow can still be tested.

## Start

Start Redis with Docker:

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

The frontend calls these dialog endpoints:

```http
POST /api/v1/interview/dialog/start
POST /api/v1/interview/dialog/actions
POST /api/v1/interview/dialog/text
GET  /api/v1/interview/onboarding/guide
```

Flow:

```text
Opening message
  -> entry cards
  -> optional guidance cards
  -> READY_TO_INTERVIEW
  -> INTERVIEWING
  -> S0-S5 interview stages
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
cd frontend
npm.cmd run build
docker compose -p interview-agent exec -T redis redis-cli ping
```
