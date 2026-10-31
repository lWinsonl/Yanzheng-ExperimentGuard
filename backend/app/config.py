"""服务端配置。API 密钥仅存在于服务端环境变量,绝不下发前端。"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """全局配置。所有敏感项通过环境变量或 .env 注入。"""

    app_name: str = "研证"
    # 模型调用配置(骨架阶段规则先行,模型复核为预留接口)
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    # 存储目录(骨架阶段用 JSON 文件持久化)
    data_dir: str = "./data"

    # 前端构建产物目录(生产单容器部署时由后端同源托管;本地开发该目录不存在则不托管)
    static_dir: str = "./static"

    # 允许的来源(前端开发服务器;生产同源部署不触发 CORS)
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()