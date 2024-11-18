from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str
    GLOBAL_CONFIG_PATH: str = "TG_FARM"

    FIX_CERT: bool = False

    REF_ID: str = '525256526'
    TASKS_WITH_JOIN_CHANNEL: bool = True
    PLAY_GAMES: bool = True
    HOLD_COIN: list[int] = [915, 915]
    SWIPE_COIN: list[int] = [1200, 2000]
    SUBSCRIBE_SQUAD: str = ''
    SESSION_START_DELAY: int = 3600
    SLEEP_TIME: list[int] = [7200, 18400]
    
    SESSIONS_PER_PROXY: int = 1
    USE_PROXY_FROM_FILE: bool = True
    DISABLE_PROXY_REPLACE: bool = False
    USE_PROXY_CHAIN: bool = False

    DEVICE_PARAMS: bool = False

    DEBUG_LOGGING: bool = False


settings = Settings()
