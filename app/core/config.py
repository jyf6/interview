from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "interview-agent-demo"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    redis_url: str = "redis://localhost:6379/0"
    session_ttl_seconds: int = Field(default=86_400, ge=60)
    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3-8b_210samples"
    dashscope_interview_model: str = "qwen3-8b_210samples"
    dashscope_emotion_model: str = "qwen-turbo"
    dashscope_timeout_seconds: int = Field(default=60, ge=5)
    dashscope_system_prompt: str = "你是一位传记采访引导助手。回答必须温和、尊重、低压力，并严格输出 JSON。"
    dashscope_interview_system_prompt: str = (
        "你是一位面向银发用户的传记采访助手。"
        "你的回答要温和、尊重、有陪伴感，先承接用户刚刚讲述的内容，再只提出一个简单具体的问题。"
        "不要像问卷，不要连续追问多个问题，不要触碰用户明确表示不愿意讲的内容。"
    )
    dashscope_emotion_system_prompt: str = (
        "你是银发传记采访系统中的情绪分析器。"
        "你只分析用户最新一条输入的情绪和对话信号，不负责生成采访回复。"
        "不要做医学诊断，不要输出解释文字，必须输出合法 JSON。"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
