from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AgentSessionCreate(BaseModel):
    user_id: str = Field(min_length=1, examples=["demo-user"])
    goal: str = Field(min_length=1, examples=["Prepare a LangGraph interview demo"])
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentSessionRead(BaseModel):
    session_id: str
    user_id: str
    goal: str
    metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime


class AgentMessageCreate(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str = Field(min_length=1)


class AgentMessageRead(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    created_at: datetime


class AgentChatRequest(BaseModel):
    content: str = Field(min_length=1, examples=["请帮我梳理一下面试自我介绍"])


class AgentChatResponse(BaseModel):
    session_id: str
    model: str
    user_message: AgentMessageRead
    assistant_message: AgentMessageRead
