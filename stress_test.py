import requests
import threading
import time
import argparse
import uuid
import random
import json
import numpy as np
from collections import Counter
from bs4 import BeautifulSoup


# --- 1. 配置 ---
def load_test_config():
    """从 config.json 安全地加载测试配置"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        password = config.get("STRESS_TEST_ADMIN_PASSWORD")
        if not password or password == "changeme":
            raise ValueError("STRESS_TEST_ADMIN_PASSWORD 未设置或为默认值。")
        return password
    except (FileNotFoundError, ValueError) as e:
        print(f"错误: 请在 config.json 中正确配置 'STRESS_TEST_ADMIN_PASSWORD'。 ({e})")
        exit(1)


ADMIN_PASSWORD = load_test_config()

# --- 2. 全局状态 ---
SHARED_STATE = {
    'session': requests.Session(),
    'activation_codes': [],
    'activated_machines': [],
    'csrf_token': None # 新增：用于存储会话期间的CSRF令牌
}
state_lock = threading.Lock()
test_results = {}



# --- 3. 动态负载生成器 ---
def gen_check_status_payload():
    with state_lock:
        # 50% 的几率检查一个已激活的设备，50% 检查一个不存在的设备
        if SHARED_STATE['activated_machines'] and random.random() > 0.5:
            return {"machine_id": random.choice(SHARED_STATE['activated_machines'])}
    return {"machine_id": str(uuid.uuid4())}


def gen_activate_payload():
    with state_lock:
        if not SHARED_STATE['activation_codes']: return None
        code = SHARED_STATE['activation_codes'].pop(0)
        machine_id = str(uuid.uuid4())
        return {"code": code, "machine_id": machine_id}


def gen_search_or_identity_payload():
    with state_lock:
        if not SHARED_STATE['activated_machines']: return None
        machine_id = random.choice(SHARED_STATE['activated_machines'])
    sample_chars = ['龙', '山', '水', '天', '地', '人', '爱', '光', '电']
    char = random.choice(sample_chars)
    return {"machine_id": machine_id, "char": char}


def gen_advanced_search_payload():
    base_payload = gen_search_or_identity_payload()
    if not base_payload: return None
    search_types = ['definition', 'pinyin', 'char_type', 'phonetic_group']
    search_queries = {'definition': base_payload['char'], 'pinyin': 'long', 'char_type': '常用字'}
    search_type = random.choice(search_types)
    query = search_queries.get(search_type, base_payload['char'])
    return {"machine_id": base_payload['machine_id'], "search_type": search_type, "query": query}


# --- 4. 测试场景定义 ---
SCENARIOS = {
    'check_status': {'endpoint': '/check_status', 'method': 'POST', 'payload_generator': gen_check_status_payload},
    'activate': {'endpoint': '/activate', 'method': 'POST', 'payload_generator': gen_activate_payload},
    'get_identities': {'endpoint': '/get_identities', 'method': 'POST',
                       'payload_generator': gen_search_or_identity_payload},
    'advanced_search': {'endpoint': '/advanced_search', 'method': 'POST',
                        'payload_generator': gen_advanced_search_payload},
}
SCENARIO_EXECUTION_ORDER = ['check_status', 'activate', 'get_identities', 'advanced_search']


# --- 5. 核心工作函数 ---
def make_request(base_url, scenario_name):
    """发送单个请求并记录详细结果"""
    scenario = SCENARIOS[scenario_name]
    payload = scenario['payload_generator']()
    if payload is None: return

    url = f"{base_url.rstrip('/')}{scenario['endpoint']}"
    status_code, error_message = None, None
    start_time = time.time()
    try:
        response = SHARED_STATE['session'].request(scenario['method'], url, json=payload, timeout=10)
        status_code = response.status_code
        if status_code != 200:
            error_message = response.text
        if scenario_name == 'activate' and status_code == 200:
            with state_lock:
                SHARED_STATE['activated_machines'].append(payload['machine_id'])
    except requests.exceptions.RequestException as e:
        status_code = -1  # 代表客户端网络异常
        error_message = str(e)
    end_time = time.time()

    with state_lock:
        test_results[scenario_name]['status_codes'][status_code] += 1
        test_results[scenario_name]['response_times'].append(end_time - start_time)
        if error_message:
            test_results[scenario_name]['errors'][error_message] += 1


def run_scenario(base_url, scenario_name, num_requests, concurrency):
    print(f"\n{'=' * 20} 场景: {scenario_name.upper()} {'=' * 20}")
    print(f"  - 端点: {SCENARIOS[scenario_name]['endpoint']}")
    print(f"  - 请求数: {num_requests}, 并发数: {concurrency}")

    test_results[scenario_name] = {
        'start_time': time.time(), 'status_codes': Counter(),
        'response_times': [], 'errors': Counter()
    }
    threads = []
    for _ in range(num_requests):
        thread = threading.Thread(target=make_request, args=(base_url, scenario_name))
        threads.append(thread)
        thread.start()
        if len(threads) >= concurrency:
            for t in threads: t.join()
            threads = []
    for t in threads: t.join()
    test_results[scenario_name]['end_time'] = time.time()


# --- 6. 前置与清理任务 (已修正) ---
def prerequisite_tasks(base_url, num_codes_to_generate):
    print(f"[INFO] 执行前置任务: 登录并生成 {num_codes_to_generate} 个激活码...")

    session = SHARED_STATE['session']
    try:
        # 步骤 1: GET登录页面以获取CSRF令牌
        login_page_res = session.get(f"{base_url}/login", timeout=10)
        login_page_res.raise_for_status()
        soup = BeautifulSoup(login_page_res.text, 'lxml')
        csrf_token = soup.find('input', {'name': 'csrf_token'}).get('value')
        if not csrf_token:
            raise Exception("无法在登录页面上找到CSRF令牌")

        SHARED_STATE['csrf_token'] = csrf_token
        print("[INFO] 已成功获取CSRF令牌。")

        # 步骤 2: POST登录表单
        login_payload = {
            'password': ADMIN_PASSWORD,
            'csrf_token': csrf_token
        }
        login_res = session.post(f"{base_url}/login", data=login_payload, timeout=10)

        if not login_res.url.endswith('/manage'):
            raise Exception("登录失败或重定向错误，请检查密码和服务器日志。")
        print("[SUCCESS] 管理员登录成功。")

        # --- 关键修正：在生成激活码时，同样提交CSRF令牌作为表单数据 ---
        # 我们需要从登录成功后返回的 /manage 页面中，获取一个新的CSRF令牌，
        # 因为Flask-WTF可能为每个表单生成不同的令牌。
        soup = BeautifulSoup(login_res.text, 'lxml')
        form_csrf_token = soup.find('input', {'name': 'csrf_token'}).get('value')
        if not form_csrf_token:
            raise Exception("无法在管理页面上找到生成表单的CSRF令牌")

        SHARED_STATE['csrf_token'] = form_csrf_token  # 更新为最新的令牌

        generate_payload = {
            'quantity': num_codes_to_generate,
            'card_type': random.choice(['monthly', 'yearly']),
            'csrf_token': form_csrf_token
        }
        gen_res = session.post(f"{base_url}/manage", data=generate_payload, timeout=60)

        # 验证是否成功，成功后服务器会重定向回 /manage
        if not gen_res.url.endswith('/manage'):
            raise Exception("生成激活码请求失败")
        print("[SUCCESS] 激活码生成请求已成功发送。")

        # --- 后续API调用流程不变 ---
        api_res = session.get(f"{base_url}/api/management_data",
                              params={'show_unused': 'true', 'code_per_page': num_codes_to_generate}, timeout=20)
        api_res.raise_for_status()
        codes_found = [item['code'] for item in api_res.json()['codes']['items']]
        if not codes_found: raise Exception("API未返回任何可用的激活码")

        SHARED_STATE['activation_codes'] = codes_found
        print(f"[SUCCESS] 成功从API获取了 {len(codes_found)} 个可用激活码。")
        return True
    except Exception as e:
        print(f"[FATAL] 前置任务失败: {e}")
        return False


def cleanup_tasks(base_url):
    activated_machines = SHARED_STATE['activated_machines']
    if not activated_machines:
        print("\n[INFO] 无需清理，测试期间未激活任何设备。")
        return

    print(f"\n[INFO] 开始清理任务：正在撤销 {len(activated_machines)} 个已激活设备的授权...")
    session = SHARED_STATE['session']
    try:
        csrf_token = SHARED_STATE.get('csrf_token')
        if not csrf_token: raise Exception("无法获取CSRF令牌用于清理")

        headers = {'X-CSRFToken': csrf_token}
        revoked_count = 0
        for machine_id in activated_machines:
            revoke_res = session.post(f"{base_url}/api/revoke_authorization", json={'machine_id': machine_id},
                                      headers=headers, timeout=10)
            if revoke_res.status_code == 200:
                revoked_count += 1
        print(f"[SUCCESS] 清理完成！成功撤销 {revoked_count}/{len(activated_machines)} 个授权。")
    except Exception as e:
        print(f"[ERROR] 清理任务失败: {e}")

# --- 7. 报告生成 ---
def generate_report():
    print("\n\n" + "=" * 60 + "\n" + " " * 22 + "最终性能报告" + "\n" + "=" * 60)
    for scenario_name, results in test_results.items():
        total_time = results['end_time'] - results['start_time']
        status_codes, response_times, errors = results['status_codes'], results['response_times'], results['errors']
        total_requests = sum(status_codes.values())
        successful_requests = status_codes.get(200, 0)
        rps = total_requests / total_time if total_time > 0 else 0

        print(f"\n--- 场景: {scenario_name.upper()} ---")
        print(f"  总耗时: {total_time:.2f} 秒  |  RPS: {rps:.2f}")
        print(
            f"  请求总数: {total_requests} (成功: {successful_requests}, 失败: {total_requests - successful_requests})")

        if response_times:
            avg = np.mean(response_times) * 1000
            p90 = np.percentile(response_times, 90) * 1000
            p99 = np.percentile(response_times, 99) * 1000
            max_rt = np.max(response_times) * 1000
            print(f"  响应时间 (ms): 平均={avg:.2f}, P90={p90:.2f}, P99={p99:.2f}, 最大={max_rt:.2f}")

        if errors:
            print("  错误详情 (Top 3):")
            for msg, count in errors.most_common(3):
                print(f"    - [{count}次] {msg[:100]}...")  # 截断过长的错误信息
    print("\n" + "=" * 60)


# --- 8. 主程序入口 ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="对 Flask 服务器进行多场景、有状态的压力测试 (V7 - 专业版)。")
    parser.add_argument("-n", "--num_requests", type=int, default=100, help="每个场景请求数")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--base_url", type=str, default="http://127.0.0.1:5000", help="服务器URL")
    parser.add_argument("--scenarios", nargs='+', choices=SCENARIOS.keys(), default=None, help="指定场景")
    parser.add_argument("--no-cleanup", action="store_true", help="跳过测试结束后的清理步骤")
    args = parser.parse_args()

    scenarios_to_run = args.scenarios or SCENARIO_EXECUTION_ORDER

    if 'activate' in scenarios_to_run:
        if not prerequisite_tasks(args.base_url, args.num_requests):
            exit(1)

    for scenario_name in SCENARIO_EXECUTION_ORDER:
        if scenario_name in scenarios_to_run:
            run_scenario(args.base_url, scenario_name, args.num_requests, args.concurrency)

    if not args.no_cleanup:
        cleanup_tasks(args.base_url)

    generate_report()