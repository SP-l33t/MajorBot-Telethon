import sys
from loguru import logger
from bot.config.config import settings
from datetime import date


logger.remove()
logger.add(sink=sys.stdout, format="<white>{time:YYYY-MM-DD HH:mm:ss}</white>"
                                   " | <level>{level}</level>"
                                   " | <white><b>{message}</b></white>")
logger = logger.opt(colors=True)

if settings.DEBUG_LOGGING:
    logger.add(f"logs/err_tracebacks_{date.today()}.txt",
               format="{time:DD.MM.YYYY HH:mm:ss} - {level} - {message}",
               level="ERROR",
               backtrace=True,
               diagnose=True)


def error(text):
    if settings.DEBUG_LOGGING:
        return logger.opt(exception=True).error(text)
    return logger.error(text)
