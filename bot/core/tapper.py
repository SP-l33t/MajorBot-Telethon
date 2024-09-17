import aiohttp
import asyncio
import functools
import json
import os
import random
import time
from urllib.parse import unquote
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy

from telethon import TelegramClient
from telethon.errors import *
from telethon.types import InputUser, InputBotAppShortName, InputPeerUser
from telethon.functions import messages, contacts, channels

from .agents import generate_random_user_agent
from bot.config import settings
from typing import Callable
from bot.utils import logger, log_error, proxy_utils, config_utils, CONFIG_PATH
from bot.exceptions import InvalidSession
from .headers import headers, get_sec_ch_ua


def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)

    return wrapper


class Tapper:
    def __init__(self, tg_client: TelegramClient):
        self.tg_client = tg_client
        self.session_name, _ = os.path.splitext(os.path.basename(tg_client.session.filename))
        self.config = config_utils.get_session_config(self.session_name, CONFIG_PATH)
        self.proxy = self.config.get('proxy', None)
        self.tg_web_data = None
        self.tg_client_id = 0
        self.headers = headers
        self.headers['User-Agent'] = self.check_user_agent()
        self.headers.update(**get_sec_ch_ua(self.headers.get('User-Agent', '')))

    def log_message(self, message) -> str:
        return f"<light-yellow>{self.session_name}</light-yellow> | {message}"

    def check_user_agent(self):
        user_agent = self.config.get('user_agent')
        if not user_agent:
            user_agent = generate_random_user_agent()
            self.config['user_agent'] = user_agent
            config_utils.update_config_file(self.session_name, self.config, CONFIG_PATH)

        return user_agent

    async def get_tg_web_data(self) -> tuple[str | None, str | None]:

        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = proxy_utils.to_telethon_proxy(proxy)
        else:
            proxy_dict = None

        self.tg_client.set_proxy(proxy_dict)
        try:
            if not self.tg_client.is_connected():
                try:
                    await self.tg_client.start()
                except (UnauthorizedError, AuthKeyUnregisteredError):
                    raise InvalidSession(self.session_name)
                except (UserDeactivatedError, UserDeactivatedBanError, PhoneNumberBannedError):
                    raise InvalidSession(f"{self.session_name}: User is banned")

            while True:
                try:
                    resolve_result = await self.tg_client(contacts.ResolveUsernameRequest(username='major'))
                    peer = InputPeerUser(user_id=resolve_result.peer.user_id,
                                         access_hash=resolve_result.users[0].access_hash)
                    break
                except FloodWaitError as fl:
                    fls = fl.seconds

                    logger.warning(self.log_message(f"FloodWait {fl}"))
                    logger.info(self.log_message(f"Sleep {fls}s"))
                    await asyncio.sleep(fls + 3)

            ref_id = settings.REF_ID if random.randint(0, 100) <= 85 else "525256526"

            input_user = InputUser(user_id=resolve_result.peer.user_id, access_hash=resolve_result.users[0].access_hash)
            input_bot_app = InputBotAppShortName(bot_id=input_user, short_name="start")

            web_view = await self.tg_client(messages.RequestAppWebViewRequest(
                peer=peer,
                app=input_bot_app,
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0])

            me = await self.tg_client.get_me()
            self.tg_client_id = me.id

            if self.tg_client.is_connected():
                await self.tg_client.disconnect()

            return ref_id, tg_web_data

        except InvalidSession as error:
            log_error(self.log_message("Invalid session"))
            await asyncio.sleep(delay=3)
            return None, None

        except Exception as error:
            log_error(self.log_message(f"Unknown error: {error}"))
            await asyncio.sleep(delay=3)
            return None, None

    async def join_and_mute_tg_channel(self, link: str):
        path = link.replace("https://t.me/", "")
        if path == 'money':
            return

        async with self.tg_client as client:

            if path.startswith('+'):
                try:
                    invite_hash = path[1:]
                    result = await client(messages.ImportChatInviteRequest(hash=invite_hash))
                    logger.info(self.log_message(f"Joined to channel: <y>{result.chats[0].title}</y>"))
                    await asyncio.sleep(random.uniform(10, 20))

                except Exception as e:
                    log_error(self.log_message(f"(Task) Error while join tg channel: {e}"))
            else:
                try:
                    await client(channels.JoinChannelRequest(channel=f'@{path}'))
                    logger.info(self.log_message(f"Joined to channel: <y>{link}</y>"))
                except Exception as e:
                    log_error(self.log_message(f"(Task) Error while join tg channel: {e}"))

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://major.bot/api{endpoint or ''}"
        response = await http_client.request(method, full_url, **kwargs)
        response.raise_for_status()
        return await response.json()

    @error_handler
    async def login(self, http_client, init_data, ref_id):
        response = await self.make_request(http_client, 'POST', endpoint="/auth/tg/", json={"init_data": init_data})
        if response and response.get("access_token", None):
            return response
        return None

    @error_handler
    async def get_daily(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/tasks/?is_daily=true")

    @error_handler
    async def get_tasks(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/tasks/?is_daily=false")

    @error_handler
    async def done_tasks(self, http_client, task_id):
        return await self.make_request(http_client, 'POST', endpoint="/tasks/", json={"task_id": task_id})

    @error_handler
    async def claim_swipe_coins(self, http_client):
        response = await self.make_request(http_client, 'GET', endpoint="/swipe_coin/")
        if response and response.get('success') is True:
            logger.info(self.log_message("Start game <y>SwipeCoins</y>"))
            coins = random.randint(settings.SWIPE_COIN[0], settings.SWIPE_COIN[1])
            payload = {"coins": coins}
            await asyncio.sleep(55)
            response = await self.make_request(http_client, 'POST', endpoint="/swipe_coin/", json=payload)
            if response and response.get('success') is True:
                return coins
            return 0
        return 0

    @error_handler
    async def claim_hold_coins(self, http_client):
        response = await self.make_request(http_client, 'GET', endpoint="/bonuses/coins/")
        if response and response.get('success') is True:
            logger.info(self.log_message("Start game <y>HoldCoins</y>"))
            coins = random.randint(settings.HOLD_COIN[0], settings.HOLD_COIN[1])
            payload = {"coins": coins}
            await asyncio.sleep(55)
            response = await self.make_request(http_client, 'POST', endpoint="/bonuses/coins/", json=payload)
            if response and response.get('success') is True:
                return coins
            return 0
        return 0

    @error_handler
    async def claim_roulette(self, http_client):
        response = await self.make_request(http_client, 'GET', endpoint="/roulette/")
        if response and response.get('success') is True:
            logger.info(self.log_message(f"Start game <y>Roulette</y>"))
            await asyncio.sleep(10)
            response = await self.make_request(http_client, 'POST', endpoint="/roulette/")
            if response:
                return response.get('rating_award', 0)
            return 0
        return 0

    @error_handler
    async def visit(self, http_client):
        return await self.make_request(http_client, 'POST', endpoint="/user-visits/visit/?")

    @error_handler
    async def streak(self, http_client):
        return await self.make_request(http_client, 'POST', endpoint="/user-visits/streak/?")

    @error_handler
    async def get_detail(self, http_client):
        detail = await self.make_request(http_client, 'GET', endpoint=f"/users/{self.tg_client_id}/")

        return detail.get('rating') if detail else 0

    @error_handler
    async def join_squad(self, http_client, squad_id):
        return await self.make_request(http_client, 'POST', endpoint=f"/squads/{squad_id}/join/?")

    @error_handler
    async def get_squad(self, http_client, squad_id):
        return await self.make_request(http_client, 'GET', endpoint=f"/squads/{squad_id}?")

    @error_handler
    async def puvel_puzzle(self, http_client):

        async with aiohttp.ClientSession() as session:
            async with session.get("https://raw.githubusercontent.com/GravelFire/TWFqb3JCb3RQdXp6bGVEdXJvdg/master/answer.py") as response:
                status = response.status
                if status == 200:
                    response_answer = json.loads(await response.text())
                    if response_answer.get('expires', 0) > int(time.time()):
                        answer = response_answer.get('answer')
                        start = await self.make_request(http_client, 'GET', endpoint="/durov/")
                        if start and start.get('success', False):
                            logger.info(self.log_message("Start game <y>Puzzle</y>"))
                            await asyncio.sleep(3)
                            return await self.make_request(http_client, 'POST', endpoint="/durov/", json=answer)
        return None

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: str) -> bool:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
            ip = (await response.json()).get('origin')
            logger.info(self.log_message(f"Proxy IP: {ip}"))
            return True
        except Exception as error:
            log_error(self.log_message(f"Proxy: {proxy} | Error: {error}"))
            return False

    @error_handler
    async def run(self) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = random.randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(self.log_message(f"Bot will start in <y>{random_delay}s</y>"))
            await asyncio.sleep(random_delay)

        proxy_conn = None
        if self.proxy:
            proxy_conn = ProxyConnector().from_url(self.proxy)
            http_client = CloudflareScraper(headers=self.headers, connector=proxy_conn)
            p_type = proxy_conn._proxy_type
            p_host = proxy_conn._proxy_host
            p_port = proxy_conn._proxy_port
            if not await self.check_proxy(http_client=http_client, proxy=f"{p_type}://{p_host}:{p_port}"):
                return
        else:
            http_client = CloudflareScraper(headers=self.headers)

        ref_id, init_data = await self.get_tg_web_data()

        if not init_data:
            if not http_client.closed:
                await http_client.close()
            if proxy_conn and not proxy_conn.closed:
                proxy_conn.close()
            return

        while True:
            try:
                if http_client.closed:
                    if proxy_conn and not proxy_conn.closed:
                        proxy_conn.close()

                    proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
                    http_client = aiohttp.ClientSession(headers=self.headers, connector=proxy_conn)

                user_data = await self.login(http_client=http_client, init_data=init_data, ref_id=ref_id)
                if not user_data:
                    logger.info(self.log_message(f"<r>Failed login</r>"))
                    sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
                    logger.info(self.log_message(f"Sleep <y>{sleep_time}s</y>"))
                    await asyncio.sleep(delay=sleep_time)
                    continue
                http_client.headers['Authorization'] = "Bearer " + user_data.get("access_token")
                logger.info(self.log_message(f"<y>⭐ Login successful</y>"))
                user = user_data.get('user')
                squad_id = user.get('squad_id')
                rating = await self.get_detail(http_client=http_client)
                logger.info(self.log_message(f"ID: <y>{user.get('id')}</y> | Points : <y>{rating}</y>"))

                if not squad_id and settings.SUBSCRIBE_SQUAD:
                    await self.join_squad(http_client=http_client, squad_id=settings.SUBSCRIBE_SQUAD)
                    await asyncio.sleep(1)

                    data_squad = await self.get_squad(http_client=http_client, squad_id=settings.SUBSCRIBE_SQUAD)
                    if data_squad:
                        logger.info(self.log_message(f"Squad : <y>{data_squad.get('name')}</y> | "
                                                     f"Member : <y>{data_squad.get('members_count')}</y> | "
                                                     f"Ratings : <y>{data_squad.get('rating')}</y>"))

                data_visit = await self.visit(http_client=http_client)
                if data_visit:
                    await asyncio.sleep(1)
                    logger.info(self.log_message(f"Daily Streak : <y>{data_visit.get('streak')}</y>"))

                await self.streak(http_client=http_client)

                hold_coins = await self.claim_hold_coins(http_client=http_client)
                if hold_coins:
                    await asyncio.sleep(1)
                    logger.info(self.log_message(f"Reward HoldCoins: <y>+{hold_coins}⭐</y>"))
                await asyncio.sleep(10)

                swipe_coins = await self.claim_swipe_coins(http_client=http_client)
                if swipe_coins:
                    await asyncio.sleep(1)
                    logger.info(self.log_message(f"Reward SwipeCoins: <y>+{swipe_coins}⭐</y>"))
                await asyncio.sleep(10)

                roulette = await self.claim_roulette(http_client=http_client)
                if roulette:
                    await asyncio.sleep(1)
                    logger.info(self.log_message(f"Reward Roulette : <y>+{roulette}⭐</y>"))
                await asyncio.sleep(10)

                puzzle = await self.puvel_puzzle(http_client=http_client)
                if puzzle:
                    await asyncio.sleep(1)
                    logger.info(self.log_message(f"Reward Puzzle Pavel: <y>+5000⭐</y>"))
                await asyncio.sleep(10)

                data_daily = await self.get_daily(http_client=http_client)
                if data_daily:
                    for daily in reversed(data_daily):
                        await asyncio.sleep(10)
                        id = daily.get('id')
                        title = daily.get('title')
                        # if title not in ["Donate rating", "Boost Major channel", "TON Transaction"]:
                        data_done = await self.done_tasks(http_client=http_client, task_id=id)
                        if data_done and data_done.get('is_completed') is True:
                            await asyncio.sleep(1)
                            logger.info(self.log_message(
                                f"Daily Task : <y>{daily.get('title')}</y> | Reward : <y>{daily.get('award')}</y>"))

                data_task = await self.get_tasks(http_client=http_client)
                if data_task:
                    for task in data_task:
                        await asyncio.sleep(10)
                        id = task.get('id')
                        if task.get('type') == 'subscribe_channel':
                            if not settings.TASKS_WITH_JOIN_CHANNEL:
                                continue
                            await self.join_and_mute_tg_channel(link=task.get('payload').get('url'))
                            await asyncio.sleep(5)

                        data_done = await self.done_tasks(http_client=http_client, task_id=id)
                        if data_done and data_done.get('is_completed') is True:
                            await asyncio.sleep(1)

                            logger.info(self.log_message(
                                f"Task : <y>{task.get('title')}</y> | Reward : <y>{task.get('award')}</y>"))
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()

            except InvalidSession as error:
                raise error

            except Exception as error:
                log_error(self.log_message(f"Unknown error: {error}"))
                await asyncio.sleep(delay=3)

            sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
            logger.info(self.log_message(f"Sleep <y>{sleep_time}s</y>"))
            await asyncio.sleep(delay=sleep_time)


async def run_tapper(tg_client: TelegramClient):
    try:
        await Tapper(tg_client=tg_client).run()
    except InvalidSession:
        session_name, _ = os.path.splitext(os.path.basename(tg_client.session.filename))
        logger.error(f"{session_name} | Invalid Session")
