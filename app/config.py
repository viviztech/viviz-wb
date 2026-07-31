from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Meta WhatsApp
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_webhook_verify_token: str = "viviz_webhook_secret_2024"
    meta_app_id: str = ""
    meta_app_secret: str = ""

    # App
    app_name: str = "Viviz WhatsApp Business"
    app_url: str = "http://localhost:8000"
    secret_key: str = "change_this_secret_key_minimum_32_characters"
    api_key: str = ""
    admin_email: str = "admin@viviztech.in"
    admin_password: str = "Admin@1234"
    debug: bool = False
    allowed_origins: str = "https://wb.viviz.in"

    # Database
    database_url: str = "sqlite+aiosqlite:///./whatsapp.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Claude AI
    anthropic_api_key: str = ""

    # AWS
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"
    s3_bucket_name: str = "viviz-whatsapp-media"

    # WhatsApp API
    whatsapp_api_version: str = "v21.0"
    whatsapp_api_base: str = "https://graph.facebook.com"

    @property
    def whatsapp_api_url(self) -> str:
        return f"{self.whatsapp_api_base}/{self.whatsapp_api_version}"

    @property
    def messages_url(self) -> str:
        return f"{self.whatsapp_api_url}/{self.whatsapp_phone_number_id}/messages"

    @property
    def media_url(self) -> str:
        return f"{self.whatsapp_api_url}/{self.whatsapp_phone_number_id}/media"

    class Config:
        env_file = ".env"
        extra = "ignore"


# Credential/config fields that are safe to change at runtime (no server restart needed) and are
# therefore editable from the dashboard Settings page, persisted in the app_settings DB table.
# Excluded: anything baked into middleware/engines at process startup (secret_key, debug,
# allowed_origins, database_url, redis_url) or tied to the separate admin-login flow.
EDITABLE_SETTINGS = [
    "whatsapp_phone_number_id",
    "whatsapp_business_account_id",
    "whatsapp_access_token",
    "whatsapp_webhook_verify_token",
    "meta_app_id",
    "meta_app_secret",
    "app_url",
    "anthropic_api_key",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_region",
    "s3_bucket_name",
]


_INSECURE_DEFAULTS = {
    "secret_key": "change_this_secret_key_minimum_32_characters",
    "whatsapp_webhook_verify_token": "viviz_webhook_secret_2024",
    "admin_password": "Admin@1234",
}


def check_insecure_defaults(settings: "Settings") -> list[str]:
    """Return the names of security-sensitive settings still on their placeholder default."""
    return [name for name, default in _INSECURE_DEFAULTS.items() if getattr(settings, name) == default]


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
