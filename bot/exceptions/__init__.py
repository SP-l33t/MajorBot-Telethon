class InvalidSession(BaseException):
    ...


class GamesNotReady(Exception):
    def __init__(self, time: int | float):
        self.seconds = time
        super().__init__(f"Games aren't ready yet. Available in: {time}")
