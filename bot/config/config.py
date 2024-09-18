from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str
    GLOBAL_CONFIG_PATH: str = "TG_FARM"
   
    REF_ID: str = '525256526'
    TASKS_WITH_JOIN_CHANNEL: bool = True
    HOLD_COIN: list[int] = [915, 915]
    SWIPE_COIN: list[int] = [2000, 3000]
    SUBSCRIBE_SQUAD: str = ''
    USE_RANDOM_DELAY_IN_RUN: bool = True
    RANDOM_DELAY_IN_RUN: list[int] = [0, 30]
    SLEEP_TIME: list[int] = [1800, 3600]
    
    USE_PROXY_FROM_FILE: bool = False

    DEVICE_PARAMS: bool = False

    DEBUG_LOGGING: bool = False


settings = Settings()
