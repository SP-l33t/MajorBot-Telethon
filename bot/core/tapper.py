import aiohttp
import asyncio
import functools
import json
import os
import random
import re
from urllib.parse import unquote, parse_qs
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from datetime import timedelta, datetime
from better_proxy import Proxy
from time import time

from bot.utils.universal_telegram_client import UniversalTelegramClient

from bot.config import settings
from typing import Callable
from bot.utils import logger, log_error, config_utils, CONFIG_PATH, first_run
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
    def __init__(self, tg_client: UniversalTelegramClient):
        self.tg_client = tg_client
        self.session_name = tg_client.session_name
        self.headers = headers

        session_config = config_utils.get_session_config(self.session_name, CONFIG_PATH)

        if not all(key in session_config for key in ('api', 'user_agent')):
            logger.critical(self.log_message('CHECK accounts_config.json as it might be corrupted'))
            exit(-1)

        user_agent = session_config.get('user_agent')
        self.headers['user-agent'] = user_agent
        self.headers.update(**get_sec_ch_ua(user_agent))

        self.proxy = session_config.get('proxy')
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            self.tg_client.set_proxy(proxy)

        self.tg_web_data = None
        self.tg_client_id = 0

        self._webview_data = None

    def log_message(self, message) -> str:
        return f"<ly>{self.session_name}</ly> | {message}"

    async def get_tg_web_data(self) -> str:
        webview_url = await self.tg_client.get_app_webview_url('major', "start", "525256526")

        tg_web_data = unquote(string=webview_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0])
        user_data = json.loads(parse_qs(tg_web_data).get('user', [''])[0])

        self.tg_client_id = user_data.get('id')

        return tg_web_data

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://major.bot/api{endpoint or ''}"
        response = await http_client.request(method, full_url, **kwargs)
        response.raise_for_status()
        return await response.json()

    @error_handler
    async def login(self, http_client, init_data):
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

    @staticmethod
    async def get_auxiliary_data():
        async with aiohttp.ClientSession() as session:
            try:
                resp = await session.get('https://raw.githubusercontent.com/SP-l33t/Auxiliary-Data/master/data.json')
                if resp.status == 200:
                    resp_json = json.loads(await resp.text())
                    auxiliary_data = resp_json.get('major', {})
                    return auxiliary_data
                else:
                    logger.error(f"Failed to get data.json: {resp.status}")
                    return None
            except aiohttp.ClientError as e:
                logger.error(f"There was an error upon requesting data.json: {e}")
                return None

    @error_handler
    async def youtube_answers(self, http_client, task_id, task_title):
        auxiliary_data = await self.get_auxiliary_data()
        if auxiliary_data:
            youtube_answers = auxiliary_data.get('youtube', {})
            if task_title in youtube_answers:
                answer = youtube_answers[task_title]
                payload = {
                    "task_id": task_id,
                    "payload": {"code": answer}
                }
                logger.info(self.log_message(f"Attempting YouTube task: <y>{task_title}</y>"))
                response = await self.make_request(http_client, 'POST', endpoint="/tasks/", json=payload)
                if response and response.get('is_completed') is True:
                    logger.success(f"{self.session_name} | Completed YouTube task: <y>{task_title}</y>")
                    return True
        return False

    @error_handler
    async def puvel_puzzle(self, http_client: aiohttp.ClientSession):
        auxiliary_data = await self.get_auxiliary_data()
        if auxiliary_data:
            puzzle_data = auxiliary_data.get('puzzle', {})
            puzzle_answer = puzzle_data.get('answer', [])
            if puzzle_data.get('expires', 0) > int(time()):
                if len(puzzle_answer) == 4:
                    answer = {"choice_1": puzzle_answer[0],
                              "choice_2": puzzle_answer[1],
                              "choice_3": puzzle_answer[2],
                              "choice_4": puzzle_answer[3]}
                    start = await self.make_request(http_client, 'GET', endpoint="/durov/")
                    if start and start.get('success', False):
                        logger.info(self.log_message("Start game <y>Puzzle</y>"))
                        await asyncio.sleep(random.uniform(3, 10))
                        return await self.make_request(http_client, 'POST', endpoint="/durov/", json=answer)
        return None

    async def check_proxy(self, http_client: aiohttp.ClientSession) -> bool:
        proxy_conn = http_client.connector
        if proxy_conn and not hasattr(proxy_conn, '_proxy_host'):
            logger.info(self.log_message(f"Running Proxy-less"))
            return True
        try:
            response = await http_client.get(url='https://ifconfig.me/ip', timeout=aiohttp.ClientTimeout(15))
            logger.info(self.log_message(f"Proxy IP: {await response.text()}"))
            return True
        except Exception as error:
            proxy_url = f"{proxy_conn._proxy_type}://{proxy_conn._proxy_host}:{proxy_conn._proxy_port}"
            log_error(self.log_message(f"Proxy: {proxy_url} | Error: {type(error).__name__}"))
            return False

    @error_handler
    async def run(self) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = random.uniform(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(self.log_message(f"Bot will start in <y>{int(random_delay)}s</y>"))
            await asyncio.sleep(random_delay)

        access_token_created_time = 0
        init_data = None

        token_live_time = random.randint(3500, 3600)

        proxy_conn = {'connector': ProxyConnector.from_url(self.proxy)} if self.proxy else {}
        async with CloudflareScraper(headers=self.headers, timeout=aiohttp.ClientTimeout(60), **proxy_conn) as http_client:
            while True:
                if not await self.check_proxy(http_client=http_client):
                    logger.warning(self.log_message('Failed to connect to proxy server. Sleep 5 minutes.'))
                    await asyncio.sleep(300)
                    continue

                try:
                    if time() - access_token_created_time >= token_live_time:
                        init_data = await self.get_tg_web_data()

                        if not init_data:
                            logger.warning(self.log_message('Failed to get webview URL'))
                            await asyncio.sleep(300)
                            continue

                    access_token_created_time = time()
                    sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])

                    user_data = await self.login(http_client=http_client, init_data=init_data)
                    if not user_data:
                        logger.warning(self.log_message(f"<r>Failed login</r>. Sleep <y>{sleep_time}s</y>"))
                        await asyncio.sleep(delay=sleep_time)
                        continue

                    http_client.headers['Authorization'] = "Bearer " + user_data.get("access_token")
                    if self.tg_client.is_fist_run:
                        await first_run.append_recurring_session(self.session_name)
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
                        random.shuffle(data_daily)
                        for daily in data_daily:
                            await asyncio.sleep(random.uniform(3, 10))
                            id = daily.get('id')
                            title = daily.get('title')
                            data_done = await self.done_tasks(http_client=http_client, task_id=id)
                            if data_done and data_done.get('is_completed') is True:
                                await asyncio.sleep(1)
                                logger.info(self.log_message(
                                    f"Daily Task : <y>{daily.get('title')}</y> | Reward : <y>{daily.get('award')}</y>"))

                    data_task = await self.get_tasks(http_client=http_client)
                    fl = 0
                    subscribed_to = 0
                    if data_task:
                        random.shuffle(data_task)
                        for task in data_task:
                            await asyncio.sleep(random.uniform(3, 10))
                            id = task.get('id')
                            title = task.get("title", "")
                            if task.get("type") == "code":
                                await self.youtube_answers(http_client=http_client, task_id=id, task_title=title)
                                continue

                            if (task.get('type') == 'subscribe_channel' or
                                re.findall(r'(Join|Subscribe|Follow).*?channel', task.get('title', ""),
                                           re.IGNORECASE)) and not fl:
                                if not settings.TASKS_WITH_JOIN_CHANNEL or subscribed_to >= 1:
                                    continue
                                fl = await self.tg_client.join_and_mute_tg_channel(link=task.get('payload').get('url'))
                                await asyncio.sleep(random.uniform(10, 20))
                                subscribed_to += 1

                            data_done = await self.done_tasks(http_client=http_client, task_id=id)
                            if data_done and data_done.get('is_completed') is True:
                                await asyncio.sleep(1)
                                logger.info(self.log_message(
                                    f"Task : <y>{task.get('title')}</y> | Reward : <y>{task.get('award')}</y>"))

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    log_error(self.log_message(f"Unknown error: {error}"))
                    await asyncio.sleep(delay=3)

                logger.info(self.log_message(f"Sleep <y>{sleep_time}s</y>"))
                await asyncio.sleep(delay=sleep_time)


async def run_tapper(tg_client: UniversalTelegramClient):
    runner = Tapper(tg_client=tg_client)
    try:
        await runner.run()
    except InvalidSession as e:
        logger.error(runner.log_message(f"Invalid Session: {e}"))
