from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    environment: str = "development"

settings = Settings()
