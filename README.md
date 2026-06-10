# Interview Agent Demo

FastAPI + Redis + DashScope + Vue3 demo for a conversation-style interview guidance flow.

The project has been merged into a single app:

- Backend owns the Redis-backed state machine and card guidance flow.
- Frontend uses a chat-style interface with message bubbles and selectable cards.
- The imported `-` demo has been folded into this project as the opening-dialog flow.

## Runtime

The original `.venv` points to a missing local Python 3.12.10 installation on this machine. A working project-local Python 3.12 environment has been created at:

```powershell
.\.venv312\python.exe
```

Verified versions:

```text
Python 3.12.13
FastAPI 0.136.3
LangChain 1.3.6
LangGraph 1.2.4
Redis 6.4.0
```

## Start Backend

Make sure Redis is running at `redis://localhost:6379/0`, then start the backend:

```powershell
.\scripts\start-backend.bat
```

API docs:

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/api/v1/health

## Start Frontend

```powershell
.\scripts\start-frontend.bat
```

Frontend URL:

- http://127.0.0.1:5173

You can also start both backend and frontend together:

```powershell
.\scripts\start-all.bat
```

## Main Flow

The frontend calls the dialog endpoints:

```http
POST /api/v1/interview/dialog/start
POST /api/v1/interview/dialog/actions
```

Flow:

```text
Opening message
  -> entry cards
  -> guidance cards when user needs help
  -> DashScope/fallback comfort message
  -> entry cards again
  -> READY_TO_INTERVIEW
```

Redis state machine states:

```text
INIT
OPENING_GENERATING
OPENING_DELIVERED
GUIDANCE_CARD
READY_TO_INTERVIEW
INTERVIEWING
```

## Dialog Response Shape

```json
{
  "session_id": "...",
  "current_state": "GUIDANCE_CARD",
  "previous_state": "OPENING_DELIVERED",
  "action": "show_guidance_cards",
  "message": {
    "role": "assistant",
    "content": "没关系，您可以先选一个最接近现在感受的卡片..."
  },
  "cards": [
    {
      "card_id": "dont_know_process",
      "label": "我不太了解采访会怎么进行"
    }
  ],
  "card_group": "guidance",
  "guidance_round": 0,
  "max_guidance_rounds": 3,
  "can_continue_guidance": true,
  "response_source": "none"
}
```

## Verification

Commands already run successfully:

```powershell
.\.venv312\python.exe -m pip check
.\.venv312\python.exe -m compileall app
cmd /c npm run build
```

The FastAPI route flow was also verified with a test client:

```text
/api/v1/interview/dialog/start
  -> /api/v1/interview/dialog/actions need_guidance
  -> /api/v1/interview/dialog/actions dont_know_process
  -> /api/v1/interview/dialog/actions start_interview
```
