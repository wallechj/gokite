import requests
from colorama import init, Fore, Style
import json
import random
import time
import os
from pathlib import Path
import signal
import sys
import schedule
from urllib.parse import urlparse
import asyncio
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from fake_useragent import UserAgent
import logging
import re

init(autoreset=True)

# 配置日志
logging.basicConfig(
    filename='kite_ai.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration
wallet_config = {
    'min_success_count': 20,
    'max_success_count': 22
}

ua = UserAgent()
useragent = ua.random

GLOBAL_HEADERS = {
    'Accept-Language': 'en-GB,en;q=0.9,en-US;q=0.8,id;q=0.7',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json',
    'Origin': 'https://agents.testnet.gokite.ai',
    'Referer': 'https://agents.testnet.gokite.ai/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'User-Agent': useragent,
    'sec-ch-ua': '"Not(A:Brand";v="99", "Microsoft Edge";v="133", "Chromium";v="133"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"'
}

rate_limit_config = {
    'max_retries': 5,
    'base_delay': 10000,
    'max_delay': 30000,
    'requests_per_minute': 4,
    'interval_between_cycles': 20000,
    'wallet_verification_retries': 3
}

last_request_time = time.time()
is_running = True
is_task_running = False

# Agent configurations
agents = {
    "deployment-kazqlqgrjw8hbr8blptnpmtj": "教授 🧠",
    "deployment-0ovyzutzgttaydzu6eqn9bxi": "加密伙伴 💰",
    "deployment-tqgv8vboiwipbkgsmzgdmwpm": "福尔摩斯 🔎"
}

agent_ids = {
    "教授 🧠": "deployment_JtmpnULoMfudGPRhHjTWQlS7",
    "加密伙伴 💰": "deployment_fseGykIvCLs3m9Nrpe9Zguy9",
    "福尔摩斯 🔎": "deployment_MK9ej2jNz2rFuzuWZjdb1UmR"
}

proxy_config = {
    'enabled': True,
}

# Handle Ctrl+C gracefully
def signal_handler(sig, frame):
    print(f"{Fore.YELLOW}\n\n🛑 正在优雅地停止脚本...")
    logging.info("脚本被用户终止")
    global is_running
    is_running = False
    time.sleep(1)
    print(f"{Fore.GREEN}👋 感谢使用 Kite AI！")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def sleep(ms):
    time.sleep(ms / 1000)

def calculate_delay(attempt):
    return min(
        rate_limit_config['max_delay'],
        rate_limit_config['base_delay'] * (2 ** attempt)
    )

async def verify_wallet(wallet):
    try:
        return True
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️ 正在跳过钱包验证继续执行...")
        logging.warning(f"钱包验证跳过: {wallet}, 错误: {e}")
        return True

async def check_rate_limit():
    global last_request_time
    now = time.time()
    time_since_last_request = now - last_request_time
    minimum_interval = 60 / rate_limit_config['requests_per_minute']

    if time_since_last_request < minimum_interval:
        wait_time = minimum_interval - time_since_last_request
        time.sleep(wait_time)
    
    last_request_time = time.time()

def parse_proxy(proxy_str):
    try:
        protocol = 'http'
        username = None
        password = None
        host = None
        port = None

        if not proxy_str.startswith(('http://', 'https://', 'socks5://')):
            proxy_str = f'http://{proxy_str}'

        parsed = urlparse(proxy_str)
        protocol = parsed.scheme or 'http'
        
        if parsed.netloc:
            if '@' in parsed.netloc:
                auth, host_port = parsed.netloc.split('@', 1)
                username, password = auth.split(':', 1) if ':' in auth else (auth, '')
            else:
                host_port = parsed.netloc
            
            if ':' in host_port:
                host, port = host_port.split(':', 1)
                port = int(port)
            else:
                host = host_port
                port = 8080

        if not host or not port:
            raise ValueError("Invalid proxy format: missing host or port")

        proxy_dict = {
            'protocol': protocol,
            'host': host,
            'port': port,
            'username': username,
            'password': password
        }
        return proxy_dict
    except Exception as e:
        print(f"{Fore.RED}⚠️ 解析代理 {proxy_str} 失败: {e}")
        logging.error(f"代理解析失败: {proxy_str}, 错误: {e}")
        return None

def format_proxy_for_requests(proxy_dict):
    if not proxy_dict:
        return None
    
    protocol = proxy_dict['protocol']
    host = proxy_dict['host']
    port = proxy_dict['port']
    username = proxy_dict.get('username')
    password = proxy_dict.get('password')

    proxy_url = f"{protocol}://{host}:{port}"
    if username and password:
        proxy_url = f"{protocol}://{username}:{password}@{host}:{port}"
    
    return {
        'http': proxy_url,
        'https': proxy_url
    }

def load_proxies_from_file():
    try:
        with open('proxies.txt', 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        if not proxies:
            print(f"{Fore.YELLOW}⚠️ proxies.txt 为空，将不使用代理")
            logging.info("proxies.txt 为空，不使用代理")
            return []
        
        parsed_proxies = []
        for proxy in proxies:
            proxy_dict = parse_proxy(proxy)
            if proxy_dict:
                parsed_proxies.append(proxy_dict)
            else:
                print(f"{Fore.YELLOW}⚠️ 跳过无效代理: {proxy}")
        
        if not parsed_proxies:
            print(f"{Fore.YELLOW}⚠️ 没有有效的代理，将不使用代理")
            logging.info("没有有效的代理，不使用代理")
            return []
        
        print(f"{Fore.GREEN}✅ 加载了 {len(parsed_proxies)} 个代理")
        logging.info(f"加载了 {len(parsed_proxies)} 个代理")
        return parsed_proxies
    except FileNotFoundError:
        print(f"{Fore.YELLOW}⚠️ 未找到 proxies.txt 文件，将不使用代理")
        logging.info("未找到 proxies.txt 文件，不使用代理")
        return []

def validate_wallets_and_proxies(wallets, proxies):
    if not proxies:
        return True, []
    if len(wallets) != len(proxies):
        print(f"{Fore.RED}❌ 错误：钱包数量({len(wallets)})与代理数量({len(proxies)})不对应")
        logging.error(f"钱包数量({len(wallets)})与代理数量({len(proxies)})不对应")
        return False, []
    return True, proxies

def get_proxy_for_wallet(wallet_index, proxies):
    if not proxies:
        return None
    return proxies[wallet_index]

def display_app_title():
    print(f"{Fore.LIGHTBLACK_EX}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"{Fore.YELLOW}启动中...............................")
    print(f"{Fore.LIGHTBLACK_EX}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    logging.info("显示应用标题")

def send_inference_request(interaction_id,proxy_dict=None):
    try:
        url = f'https://neo.prod.zettablock.com/v1/inference?id={interaction_id}'
        with requests.Session() as session:
            if proxy_dict:
                proxies = format_proxy_for_requests(proxy_dict)
                if proxies:
                    session.proxies = proxies
            
            response = session.get(url, headers=GLOBAL_HEADERS, timeout=10)
            response.raise_for_status()
        
        print(f"{Fore.GREEN}✅ 推理请求发送成功！")
        logging.info("推理请求发送成功")
        return True
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}⚠️ 推理请求失败: {e}")
        logging.error(f"推理请求失败: {e}")
        return False

async def send_random_question(agent, proxy_dict=None):
    try:
        await check_rate_limit()

        ttft = 0
        total_time = 0
        with open('questions.json', 'r', encoding='utf-8') as f:
            random_questions = json.load(f)
        random_question = random.choice(random_questions)
        start_time = time.time()

        payload = {'message': random_question, 'stream': False}
        
        with requests.Session() as session:
            if proxy_dict:
                proxies = format_proxy_for_requests(proxy_dict)
                if proxies:
                    session.proxies = proxies
            
            response = session.post(
                f"https://{agent.lower().replace('_', '-')}.staging.gokite.ai/main",
                json=payload,
                headers=GLOBAL_HEADERS
            )
            response.raise_for_status()

        ttft = (time.time() - start_time) * 1000 
        multiplier = random.uniform(1.5, 3) 
        total_time = ttft * multiplier 

        ttft_decimal_places = random.randint(8, 13)
        total_time_decimal_places = random.randint(1,7)

        formatted_ttft = float(f"{ttft:.{ttft_decimal_places}f}")
        formatted_total_time = float(f"{total_time:.{total_time_decimal_places}f}")

        response_content = response.json()['choices'][0]['message']['content']

        print(f"{Fore.BLUE}TTFT: {formatted_ttft}ms | Total Time: {formatted_total_time}ms")
        logging.info(f"发送问题成功: {random_question[:50]}..., TTFT: {formatted_ttft}ms, Total Time: {formatted_total_time}ms")

        return {
            'question': random_question,
            'response': response_content,
            'ttft': formatted_ttft,
            'total_time': formatted_total_time
        }
    except Exception as e:
        print(f"{Fore.RED}⚠️ 错误: {e}")
        logging.error(f"发送问题失败: {e}")
        return None

async def report_usage(wallet, options, proxy_dict=None, retry_count=0):
    try:
        await check_rate_limit()

        payload = {
            'wallet_address': wallet,
            'agent_id': agent_ids[agents[options['agent_id']]],
            'request_text': options['question'],
            'response_text': options['response'],
            'request_metadata': {},
            'ttft': options['ttft'],
            'total_time': options['total_time']
        }

        interaction_id = None
        with requests.Session() as session:
            if proxy_dict:
                Proxies = format_proxy_for_requests(proxy_dict)
                if Proxies:
                    session.proxies = Proxies

            response = session.post(
                'https://quests-usage-dev.prod.zettablock.com/api/report_usage',
                json=payload,
                headers=GLOBAL_HEADERS,
                timeout=200
            )
            response.raise_for_status()
            interaction_id = response.json()['interaction_id']

        print(f"{Fore.GREEN}✅ 使用数据上报成功！\n")
        logging.info(f"使用数据上报成功: 钱包 {wallet}")
        return True,interaction_id

    except requests.exceptions.Timeout:
        print(f"{Fore.RED}⏰ 请求超时，已跳过当前上报。\n")
        logging.warning(f"上报超时: 钱包 {wallet}")
        return False,None
    except Exception as e:
        is_rate_limit = 'Rate limit exceeded' in str(e)

        if is_rate_limit and retry_count < rate_limit_config['max_retries']:
            base_delay = 2000
            jitter = random.randint(0, 1000)
            delay = base_delay * (2 ** retry_count) + jitter / 1000

            print(f"{Fore.YELLOW}⏳ 检测到速率限制，{delay:.1f} 秒后重试...")
            logging.info(f"速率限制，{delay:.1f} 秒后重试: 钱包 {wallet}")
            time.sleep(delay)
            return await report_usage(wallet, options, proxy_dict, retry_count + 1)

        print(f"{Fore.YELLOW}⚠️ 使用报告存在问题，继续执行...")
        logging.error(f"上报失败: 钱包 {wallet}, 错误: {e}")
        return False,None

def load_wallets_from_file():
    try:
        with open('wallets.txt', 'r', encoding='utf-8') as f:
            wallets = [line.strip().lower() for line in f if line.strip()]
        logging.info(f"加载了 {len(wallets)} 个钱包")
        return wallets
    except FileNotFoundError:
        print(f"{Fore.RED}⚠️ 错误: 未找到wallets.txt文件")
        logging.error("未找到 wallets.txt 文件")
        return []

async def process_agent_cycle(wallet, agent_id, agent_name, proxy_dict=None):
    try:
        nanya = await send_random_question(agent_id, proxy_dict)
        
        if nanya:
            print(f"❓ 问题: {nanya['question']}")
            print(f"💡 答案:{nanya['response']}")

            report_success,interaction_id = await report_usage(wallet, {
                'agent_id': agent_id,
                'question': nanya['question'],
                'response': nanya['response'],
                'ttft': nanya['ttft'],
                'total_time': nanya['total_time']
            }, proxy_dict)

            if report_success:
                # 在 report_usage 成功后发送推理请求
                inference_success = send_inference_request(interaction_id,proxy_dict)
                return 1 if inference_success else 0
            return 0
        return 0
    except Exception as e:
        print(f"{Fore.RED}⚠️ 代理周期错误: {e}")
        logging.error(f"代理周期错误: 钱包 {wallet}, 代理 {agent_name}, 错误: {e}")
        return 0

async def process_wallet(wallet, wallet_index, use_proxy, assigned_proxy=None):
    global is_running
    print(f"{Fore.BLUE}\n📌 开始处理钱包: {wallet}")
    logging.info(f"开始处理钱包: {wallet}")
    
    if use_proxy and assigned_proxy:
        proxy_url = format_proxy_for_requests(assigned_proxy)
        print(f"{Fore.CYAN}🔗 分配代理: {proxy_url['http'] if proxy_url else '无效代理'}")
        logging.info(f"分配代理: {proxy_url['http'] if proxy_url else '无效代理'}")
    else:
        print(f"{Fore.CYAN}🔗 不使用代理")
        logging.info("不使用代理")

    target_success = random.randint(wallet_config['min_success_count'], wallet_config['max_success_count'])
    print(f"{Fore.MAGENTA}🎯 目标成功次数: {target_success} 次")
    logging.info(f"目标成功次数: {target_success}")

    success_count = 0
    cycle_count = 1

    while is_running and success_count < target_success:
        print(f"{Fore.MAGENTA}\n🔄 第 {cycle_count} 轮循环 | 当前成功: {success_count}/{target_success}")
        logging.info(f"第 {cycle_count} 轮循环, 当前成功: {success_count}/{target_success}")

        for agent_id, agent_name in agents.items():
            if not is_running or success_count >= target_success:
                break
            
            print(f"{Fore.MAGENTA}\n🤖 使用代理: {agent_name}")
            increment = await process_agent_cycle(wallet, agent_id, agent_name, assigned_proxy)
            success_count += increment

            if is_running and success_count < target_success:
                random_wait_time = random.randint(8000, 13000)
                print(f"{Fore.YELLOW}⏳ 等待 {random_wait_time/1000} 秒后进行下一次交互...")
                time.sleep(random_wait_time / 1000)

        cycle_count += 1
        print(f"{Fore.LIGHTBLACK_EX}────────────────────────────────────────")

    print(f"{Fore.GREEN}\n🎉 钱包 {wallet} 已完成 {success_count} 次成功上报，切换下一个钱包")
    logging.info(f"钱包 {wallet} 完成 {success_count} 次成功上报")

async def main():
    logging.info("程序启动")
    display_app_title()

    def ask_mode():
        return input(f"{Fore.YELLOW}🔄 选择连接模式 (1: 直连, 2: 代理): ")

    def ask_wallet_mode():
        print(f"{Fore.YELLOW}\n📋 选择钱包模式:")
        print(f"{Fore.YELLOW}1. 手动输入")
        print(f"{Fore.YELLOW}2. 加载钱包")
        return input(f"{Fore.YELLOW}\n请选择: ")

    def ask_wallet():
        return input(f"{Fore.YELLOW}🔑 输入你的钱包地址: ")

    try:
        # mode = ask_mode()
        mode = '2'  # Hardcoded for testing
        proxy_config['enabled'] = mode == '2'
        
        proxies = load_proxies_from_file() if proxy_config['enabled'] else []
        
        wallet_mode = '2'  # Hardcoded for testing
        wallets = []
        
        if wallet_mode == '2':
            wallets = load_wallets_from_file()
            if not wallets:
                print(f"{Fore.RED}❌ 没有加载到钱包，停止程序")
                logging.error("没有加载到钱包，程序停止")
                return
        else:
            wallet = ask_wallet()
            wallets = [wallet.lower()]

        is_valid, assigned_proxies = validate_wallets_and_proxies(wallets, proxies)
        if not is_valid:
            return

        wallet_index = 0
        for wallet in wallets:
            if not is_running:
                break
            proxy = get_proxy_for_wallet(wallet_index, assigned_proxies)
            await process_wallet(wallet, wallet_index, proxy_config['enabled'], proxy)
            wallet_index += 1

        print(f"{Fore.GREEN}\n✅ 所有钱包处理完成！")
        logging.info("所有钱包处理完成")
        
    except Exception as e:
        print(f"{Fore.RED}⚠️ 发生错误: {e}")
        logging.error(f"程序错误: {e}")
    finally:
        pass


def get_user_time():
    while True:
        print(f"{Fore.YELLOW}⏰ 请输入每天运行任务的时间，格式为 HH:MM（例如 16:52）")
        time_input = input(f"{Fore.YELLOW}时间: ").strip()
        
        # Validate format using regex
        if not re.match(r'^\d{2}:\d{2}$', time_input):
            print(f"{Fore.RED}❌ 格式错误！请输入 HH:MM 格式，例如 16:52")
            continue
        
        try:
            hour, minute = map(int, time_input.split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                print(f"{Fore.RED}❌ 无效时间！小时必须在 0-23 之间，分钟必须在 0-59 之间")
                continue
            return hour, minute
        except ValueError:
            print(f"{Fore.RED}❌ 格式错误！请输入有效的数字，例如 16:52")
            continue


def create_task(hour, minute, task_func):
    def wrapper():
        global is_task_running
        if is_task_running:
            print(f"{Fore.YELLOW}⚠️ 上次任务尚未完成，跳过本次执行")
            logging.warning("上次任务尚未完成，跳过本次执行")
            return
        is_task_running = True
        try:
            asyncio.run(task_func())
        finally:
            is_task_running = False
    
    print("启动定时任务")
    logging.info(f"创建定时任务: 每天 {hour:02d}:{minute:02d}")
    schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(wrapper)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    hour, minute = get_user_time()
    create_task(hour, minute, main)
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print(f"{Fore.YELLOW}🛑 脚本已停止")
        logging.info("脚本被终止")
