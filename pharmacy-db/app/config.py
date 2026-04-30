from pydantic_settings import BaseSettings, SettingsConfigDict

# Inherit from BaseSettings, which automatically reads values
# from environment variables and/or .env files
class Settings(BaseSettings):
    database_url: str
    test_database_url: str
    log_level: str = "INFO"
    environment: str = "development"


    # tells Pydantic to load values from a .env file and to ignore any extra fields 
    # that are not defined in the Settings class
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()  # type: ignore[call-arg]