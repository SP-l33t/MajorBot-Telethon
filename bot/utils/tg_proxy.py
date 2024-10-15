import os
from opentele.tl import TelegramClient
from pyrogram import Client as PyrogramClient


class TelegramProxy:
    def __init__(self, session_file, api_id, api_hash):
        self.session_file = session_file
        self.api_id = api_id
        self.api_hash = api_hash
        self.client = None
