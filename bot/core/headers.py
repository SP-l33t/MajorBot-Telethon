import base64
import re
from google.protobuf.internal import encoder
from time import time
from random import randint


headers = {
    'Cache-Control': 'no-cache',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://major.bot',
    'Referer': 'https://major.bot/',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Ch-Ua-Mobile': '?1',
    'Sec-Ch-Ua-Platform': '"Android"',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'en-US,en;q=0.9',
    'Priority': 'u=1, i',
    "X-Requested-With": "org.telegram.messenger"
}


def get_sec_ch_ua(user_agent):
    pattern = r'(Chrome|Chromium)\/(\d+)\.(\d+)\.(\d+)\.(\d+)'

    match = re.search(pattern, user_agent)

    if match:
        browser = match.group(1)
        version = match.group(2)

        if browser == 'Chrome':
            sec_ch_ua = f'"Chromium";v="{version}", "Not;A=Brand";v="24", "Google Chrome";v="{version}"'
        else:
            sec_ch_ua = f'"Chromium";v="{version}", "Not;A=Brand";v="24"'

        return {'Sec-Ch-Ua': sec_ch_ua}
    else:
        return {}


def create_correlation_id():
    current_timestamp = int(time())*1000 + randint(0, 999)
    buffer = encoder._VarintBytes(current_timestamp)
    complete_message = bytes([8]) + bytes(buffer)
    base64_result = base64.b64encode(complete_message).decode('utf-8')
    return base64_result
