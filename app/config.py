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
    admin_email: str = "admin@viviztech.in"
    admin_password: str = "Admin@1234"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./whatsapp.db"

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


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
