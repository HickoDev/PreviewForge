from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_host: str = "db"
    database_port: int = 5432
    database_name: str = "previewforge"
    database_user: str = "previewforge"
    database_password_file: Path = Path("/run/secrets/db_password")
    environment_name: str = "local"
    source_sha: str = "local-uncommitted"
    enable_failure_exercise: bool = False

    def database_url(self) -> URL:
        password = SecretStr(self.database_password_file.read_text().strip())
        if not password.get_secret_value():
            raise ValueError("Database password file must not be empty")
        return URL.create(
            "postgresql+psycopg",
            username=self.database_user,
            password=password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )
