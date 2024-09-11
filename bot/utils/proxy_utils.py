import os
from python_socks import ProxyType
from shutil import copyfile
from better_proxy import Proxy
from bot.config.config import settings


PROXY_TYPES = {
    'socks5': ProxyType.SOCKS5,
    'socks4': ProxyType.SOCKS4,
    'http': ProxyType.HTTP,
    'https': ProxyType.HTTP
}


def get_proxy_type(proxy_type: str):
    return PROXY_TYPES.get(proxy_type.lower())


def to_telethon_proxy(proxy):
    return {
        'proxy_type': get_proxy_type(proxy.protocol),
        'addr': proxy.host,
        'port': proxy.port,
        'username': proxy.login,
        'password': proxy.password
    }


def get_proxies() -> list[str]:
    proxy_template_path = "bot/config/proxies-template.txt"
    proxy_path = "bot/config/proxies.txt"

    if not os.path.isfile(proxy_path):
        copyfile(proxy_template_path, proxy_path)
        return []

    if settings.USE_PROXY_FROM_FILE:
        with open(file=proxy_path, encoding="utf-8-sig") as file:
            return [Proxy.from_str(proxy=row.strip()).as_url
                    for row in file
                    if row.strip() and not row.strip().startswith('type')]
    else:
        return []


def get_unused_proxies(accounts_config):
    used_proxies = list({v['proxy'] for v in accounts_config.values()})
    all_proxies = get_proxies()
    return [proxy for proxy in all_proxies if proxy not in used_proxies]
