from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-plus"

    llm_temperature: float = 0.7
    llm_max_tokens: int = 1024

    server_host: str = "0.0.0.0"
    server_port: int = 8000

    session_ttl_seconds: int = 604800

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


app_config = AppConfig()
