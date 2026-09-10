from pathlib import Path

from pydantic import SecretStr, model_validator
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
    exports_enabled: bool = False
    floci_endpoint: str = ""

    @model_validator(mode="after")
    def local_exports(self):
        if self.exports_enabled:
            from app.aws import ENDPOINTS, environment_name

            if self.floci_endpoint not in ENDPOINTS:
                raise ValueError("Exports require an explicit approved local Floci endpoint")
            environment_name(self.environment_name)
        return self

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
