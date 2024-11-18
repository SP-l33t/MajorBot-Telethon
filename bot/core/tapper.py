import aiohttp
import asyncio
import json
import re
from urllib.parse import unquote, parse_qs
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from time import time
from random import randint, uniform, shuffle

from bot.utils.universal_telegram_client import UniversalTelegramClient

from bot.config import settings
from bot.utils import logger, log_error, config_utils, CONFIG_PATH, first_run
from bot.exceptions import InvalidSession, GamesNotReady
from .headers import headers, get_sec_ch_ua, create_correlation_id

BASE_URL = "https://major.bot/api"
TASKS_WL = [15027, 29, 16, 5, 15042, 15156, 15171, 15136, 15086]


class Tapper:
    def __init__(self, tg_client: UniversalTelegramClient):
        self.tg_client = tg_client
        self.session_name = tg_client.session_name

        session_config = config_utils.get_session_config(self.session_name, CONFIG_PATH)

        if not all(key in session_config for key in ('api', 'user_agent')):
            logger.critical(self.log_message('CHECK accounts_config.json as it might be corrupted'))
            exit(-1)

        self.headers = headers
        user_agent = session_config.get('user_agent')
        self.headers['User-Agent'] = user_agent
        self.headers.update(**get_sec_ch_ua(user_agent))

        self.proxy = session_config.get('proxy')
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            self.tg_client.set_proxy(proxy)

        self.tg_web_data = None
        self.tg_client_id = 0

        self._webview_data = None
        self.x_correlation_id = None

    def log_message(self, message) -> str:
        return f"<ly>{self.session_name}</ly> | {message}"

    async def get_tg_web_data(self) -> str:
        webview_url = await self.tg_client.get_app_webview_url('major', "start", "525256526")

        tg_web_data = unquote(string=webview_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0])
        user_data = json.loads(parse_qs(tg_web_data).get('user', [''])[0])

        self.tg_client_id = user_data.get('id')

        return tg_web_data

    async def check_proxy(self, http_client: CloudflareScraper) -> bool:
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

    async def make_request(self, http_client: CloudflareScraper, method, endpoint="", url=None, **kwargs):
        full_url = url or f"{BASE_URL}{endpoint}"
        response = await http_client.request(method, full_url, **kwargs)
        if response.status in range(200, 300):
            return await response.json() if 'json' in response.content_type else await response.text()
        else:
            error_json = await response.json() if 'json' in response.content_type else {}
            error_text = f"Error: {error_json}" if error_json else ""
            logger.warning(self.log_message(
                f"{method} Request to {full_url} failed with {response.status} code. {error_text}"))
            return error_json

    async def login(self, http_client: CloudflareScraper, init_data):
        return await self.make_request(http_client, 'POST', endpoint="/auth/tg/", json={"init_data": init_data})

    async def get_tasks(self, http_client: CloudflareScraper):
        regular = await self.make_request(http_client, 'GET', endpoint="/tasks/?is_daily=false") or []
        daily = await self.make_request(http_client, 'GET', endpoint="/tasks/?is_daily=true") or []
        return daily + regular

    async def done_tasks(self, http_client, task_id):
        return await self.make_request(http_client, 'POST', endpoint="/tasks/", json={"task_id": task_id})

    async def claim_swipe_coins(self, http_client: CloudflareScraper):
        g_headers = {'Referer': 'https://major.bot/games'}
        response = await self.make_request(http_client, 'GET', endpoint="/swipe_coin/", headers=g_headers)
        if response.get('detail', {}).get('blocked_until'):
            raise GamesNotReady(int(response.get('detail', {}).get('blocked_until') - time()))
        if response and response.get('success') is True:
            g_headers['Referer'] = 'https://major.bot/games/swipe-coin'
            await self.make_request(http_client, 'GET', endpoint="/swipe_coin/", headers=g_headers)
            logger.info(self.log_message("Started <y>SwipeCoins</y> game"))
            coins = randint(settings.SWIPE_COIN[0], settings.SWIPE_COIN[1])
            payload = {"coins": coins}
            await asyncio.sleep(uniform(60, 61))
            g_headers['X-Correlation-Id'] = self.x_correlation_id
            response = await self.make_request(http_client, 'POST', endpoint="/swipe_coin/", json=payload,
                                               headers=g_headers)
            if response and response.get('success') is True:
                return coins
        return 0

    async def claim_hold_coins(self, http_client: CloudflareScraper):
        g_headers = {'Referer': 'https://major.bot/games'}
        response = await self.make_request(http_client, 'GET', endpoint="/bonuses/coins/", headers=g_headers)
        if response.get('detail', {}).get('blocked_until'):
            raise GamesNotReady(int(response.get('detail', {}).get('blocked_until') - time()))
        if response and response.get('success') is True:
            g_headers['Referer'] = 'https://major.bot/games/hold-coin'
            await self.make_request(http_client, 'GET', endpoint="/bonuses/coins/", headers=g_headers)
            logger.info(self.log_message("Started <y>HoldCoins</y> game"))
            coins = randint(settings.HOLD_COIN[0], settings.HOLD_COIN[1])
            payload = {"coins": coins}
            await asyncio.sleep(uniform(60, 61))
            g_headers['X-Correlation-Id'] = self.x_correlation_id
            response = await self.make_request(http_client, 'POST', endpoint="/bonuses/coins/", json=payload,
                                               headers=g_headers)
            if response and response.get('success') is True:
                return coins
        return 0

    async def claim_roulette(self, http_client: CloudflareScraper):
        g_headers = {'Referer': 'https://major.bot/games'}
        response = await self.make_request(http_client, 'GET', endpoint="/roulette/", headers=g_headers)
        if response.get('detail', {}).get('blocked_until'):
            raise GamesNotReady(int(response.get('detail', {}).get('blocked_until') - time()))
        if response.get('success'):
            logger.info(self.log_message(f"Started <y>Roulette</y> game"))
            await asyncio.sleep(uniform(0, 1))
            g_headers = {'X-Correlation-Id': self.x_correlation_id,
                       'Referer': 'https://major.bot/games/roulette'}
            response = await self.make_request(http_client, 'POST', endpoint="/roulette/",
                                               headers=g_headers)
            return response.get('rating_award', 0)
        return 0

    async def visit(self, http_client: CloudflareScraper):
        return await self.make_request(http_client, 'POST', endpoint="/user-visits/visit/")

    async def streak(self, http_client: CloudflareScraper):
        return await self.make_request(http_client, 'GET', endpoint="/user-visits/streak/")

    async def get_detail(self, http_client: CloudflareScraper):
        detail = await self.make_request(http_client, 'GET', endpoint=f"/users/{self.tg_client_id}/")
        return detail.get('rating', 0)

    async def get_user_position(self, http_client: CloudflareScraper):
        detail = await self.make_request(http_client, 'GET', endpoint=f"/users/top/position/{self.tg_client_id}/?")
        return detail.get('position', 0)

    async def get_top_users(self, http_client: CloudflareScraper):
        return await self.make_request(http_client, 'GET', endpoint=f"/users/top/?limit=100")

    async def join_squad(self, http_client: CloudflareScraper, squad_id):
        return await self.make_request(http_client, 'POST', endpoint=f"/squads/{squad_id}/join/?")

    async def get_squad(self, http_client: CloudflareScraper, squad_id):
        return await self.make_request(http_client, 'GET', endpoint=f"/squads/{squad_id}?")

    async def get_top_squads(self, http_client: CloudflareScraper):
        return await self.make_request(http_client, 'GET', endpoint=f"/squads/?limit=100")

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

    async def youtube_answers(self, http_client: CloudflareScraper, task_id, task_title):
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
                if response.get('is_completed') is True:
                    logger.success(f"{self.session_name} | Completed YouTube task: <y>{task_title}</y>")
                    return True
        return False

    async def puvel_puzzle(self, http_client: CloudflareScraper):
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
                    g_headers = {'Referer': 'https://major.bot/games'}
                    start = await self.make_request(http_client, 'GET', endpoint="/durov/", headers=g_headers)
                    if start.get('detail', {}).get('blocked_until'):
                        raise GamesNotReady(int(start.get('detail', {}).get('blocked_until') - time()))
                    if start.get('success'):
                        g_headers['Referer'] = 'https://major.bot/games/puzzle-durov'
                        await self.make_request(http_client, 'GET', endpoint="/durov/")
                        g_headers['X-Correlation-Id'] = self.x_correlation_id
                        logger.info(self.log_message("Started <y>Puzzle</y> game"))
                        await asyncio.sleep(uniform(3, 10))
                        return await self.make_request(http_client, 'POST', endpoint="/durov/", json=answer,
                                                       headers=g_headers)
        return None

    # async def play_games(self, http_client: CloudflareScraper):
    #     await asyncio.sleep(uniform(3, 15))
    #     hold_coins = await self.claim_hold_coins(http_client=http_client)
    #     if hold_coins:
    #         logger.info(self.log_message(f"Reward HoldCoins: <y>+{hold_coins}⭐</y>"))
    #
    #     await asyncio.sleep(uniform(3, 15))
    #     swipe_coins = await self.claim_swipe_coins(http_client=http_client)
    #     if swipe_coins:
    #         logger.info(self.log_message(f"Reward SwipeCoins: <y>+{swipe_coins}⭐</y>"))
    #
    #     await asyncio.sleep(uniform(3, 15))
    #     roulette = await self.claim_roulette(http_client=http_client)
    #     if roulette:
    #         logger.info(self.log_message(f"Reward Roulette : <y>+{roulette}⭐</y>"))
    #
    #     await asyncio.sleep(uniform(3, 15))
    #     puzzle = await self.puvel_puzzle(http_client=http_client)
    #     if puzzle:
    #         logger.info(self.log_message(f"Reward Puzzle Pavel: <y>+5000⭐</y>"))

    async def play_games(self, http_client: CloudflareScraper):
        games = [
            {
                'func': self.claim_hold_coins,
                'name': 'HoldCoins',
                'reward_text': lambda x: f"+{x}⭐"
            },
            {
                'func': self.claim_swipe_coins,
                'name': 'SwipeCoins',
                'reward_text': lambda x: f"+{x}⭐"
            },
            {
                'func': self.claim_roulette,
                'name': 'Roulette',
                'reward_text': lambda x: f"+{x}⭐"
            },
            {
                'func': self.puvel_puzzle,
                'name': 'Puzzle Pavel',
                'reward_text': lambda x: "+5000⭐"
            }
        ]

        shuffle(games)

        try:
            for game in games:
                await asyncio.sleep(uniform(3, 15))
                reward = await game['func'](http_client=http_client)
                if reward:
                    logger.info(self.log_message(f"Reward {game['name']}: <y>{game['reward_text'](reward)}</y>"))
        except GamesNotReady as e:
            logger.info(self.log_message(str(e)))
            return e.seconds
        return 0

    async def run(self) -> None:
        random_delay = uniform(0, settings.SESSION_START_DELAY)
        logger.info(self.log_message(f"Bot will start in <light-red>{int(random_delay)}s</light-red>"))
        await asyncio.sleep(delay=random_delay)

        access_token_created_time = 0
        init_data = None

        token_live_time = randint(3500, 3600)

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
                    sleep_time = uniform(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])

                    user_data = await self.login(http_client=http_client, init_data=init_data)
                    if not user_data:
                        logger.warning(self.log_message(f"<r>Failed to login</r>. Sleep <y>{int(sleep_time)}s</y>"))
                        await asyncio.sleep(sleep_time)
                        continue

                    self.x_correlation_id = create_correlation_id()
                    http_client.headers['Authorization'] = f"Bearer {user_data.get('access_token')}"
                    if self.tg_client.is_fist_run:
                        await first_run.append_recurring_session(self.session_name)
                    logger.info(self.log_message(f"<y>⭐ Logged in successfuly</y>"))
                    user = user_data.get('user')
                    squad_id = user.get('squad_id')

                    rating = await self.get_detail(http_client)
                    position = await self.get_user_position(http_client)
                    logger.info(self.log_message(
                        f"ID: <y>{user.get('id')}</y> | Position: <ly>{position}</ly> | Points : <y>{rating}</y>"))

                    streak = (await self.streak(http_client=http_client)).get('streak')
                    if streak:
                        logger.info(self.log_message(f"Daily Streak : <y>{streak}</y>"))

                    await self.get_top_users(http_client)

                    await self.visit(http_client=http_client)

                    await self.get_top_squads(http_client)
                    if not squad_id and settings.SUBSCRIBE_SQUAD:
                        await asyncio.sleep(uniform(5, 10))
                        await self.join_squad(http_client=http_client, squad_id=settings.SUBSCRIBE_SQUAD)
                        await asyncio.sleep(uniform(0, 1))

                        data_squad = await self.get_squad(http_client=http_client, squad_id=settings.SUBSCRIBE_SQUAD)
                        if data_squad:
                            logger.info(self.log_message(f"Squad : <y>{data_squad.get('name')}</y> | "
                                                         f"Member : <y>{data_squad.get('members_count')}</y> | "
                                                         f"Ratings : <y>{data_squad.get('rating')}</y>"))

                    if settings.PLAY_GAMES:
                        sleep_time = await self.play_games(http_client) * uniform(1.02, 1.2) or sleep_time

                    await asyncio.sleep(uniform(3, 15))

                    data_task = await self.get_tasks(http_client=http_client)
                    subscribed_to = 0
                    if data_task:
                        shuffle(data_task)
                        for task in data_task:
                            task_id = task.get('id')
                            title = task.get("title", "")

                            if task.get('is_completed', False) or task_id not in TASKS_WL:
                                continue

                            if randint(0, 3):
                                logger.info(self.log_message(f"Randomly stopping doing tasks"))
                                break

                            await asyncio.sleep(uniform(3, 10))
                            if task.get("type") == "code":
                                await self.youtube_answers(http_client=http_client, task_id=task_id, task_title=title)
                                continue

                            if (task.get('type') == 'subscribe_channel' or
                                re.findall(r'(Join|Subscribe|Follow).*?channel', task.get('title', ""),
                                           re.IGNORECASE)):
                                if not settings.TASKS_WITH_JOIN_CHANNEL or subscribed_to >= 1:
                                    continue
                                if not (streak > 1 and task_id == 29):
                                    await self.tg_client.join_and_mute_tg_channel(link=task.get('payload').get('url'))
                                await asyncio.sleep(uniform(10, 20))
                                subscribed_to += 1

                            data_done = await self.done_tasks(http_client=http_client, task_id=task_id)
                            if data_done and data_done.get('is_completed') is True:
                                logger.info(self.log_message(
                                    f"Task : <y>{task.get('title')}</y> | Reward : <y>{task.get('award')}</y>"))

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    sleep_time = uniform(60, 120)
                    log_error(self.log_message(f"Unknown error: {error}. Sleeping for {int(sleep_time)}"))
                    await asyncio.sleep(sleep_time)

                logger.info(self.log_message(f"Sleep <y>{int(sleep_time)}s</y>"))
                await asyncio.sleep(sleep_time)


async def run_tapper(tg_client: UniversalTelegramClient):
    runner = Tapper(tg_client=tg_client)
    try:
        await runner.run()
    except InvalidSession as e:
        logger.error(runner.log_message(f"Invalid Session: {e}"))
