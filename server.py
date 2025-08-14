import json
import os
import uuid
import secrets
import hashlib
import hmac
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import logging
from functools import wraps
import sqlite3 # 导入SQLite3库

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
# 导入 Flask-WTF 相关模块
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, IntegerField, SelectField, PasswordField
from wtforms.validators import DataRequired, NumberRange

# FileLock 不再需要，SQLite自带更高效的锁机制
import psutil
from waitress import serve

# --- 1. 应用初始化与配置 ---
app = Flask(__name__)
csrf = CSRFProtect(app)

# --- 核心文件路径 ---
CONFIG_FILE = 'config.json'
# 【V3版】数据库文件路径
DATABASE_FILE = 'database.db' 
# 旧的JSON文件路径，仅用于迁移
OLD_DEVICES_DB_FILE = 'activated_devices.json'
OLD_CODES_DB_FILE = 'activation_codes.json'
OLD_DICTIONARY_FILE = 'dictionary_database.json'

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 加载配置 ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        logging.warning(f"配置文件未找到: {CONFIG_FILE}，正在创建默认配置。")
        default_config = {
            "FLASK_SECRET_KEY": secrets.token_hex(24),
            "ADMIN_PASSWORD_HASH": "",
            "STRESS_TEST_ADMIN_PASSWORD": "changeme",
            "CARD_DURATIONS": {"monthly": 30, "quarterly": 90, "yearly": 365, "trial": 7},
            "GENERATE_CODE_LIMIT": 5000
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()
# Flask-WTF 和 session 都需要这个
app.config['SECRET_KEY'] = config.get('FLASK_SECRET_KEY')
ADMIN_PASSWORD_HASH = config.get('ADMIN_PASSWORD_HASH')
CARD_DURATIONS = {k: timedelta(days=v) for k, v in config.get("CARD_DURATIONS", {}).items()}
GENERATE_CODE_LIMIT = config.get("GENERATE_CODE_LIMIT", 5000)

if not ADMIN_PASSWORD_HASH:
    logging.warning("管理员密码未设置！管理功能将无法使用。请运行 create_admin.py 生成。")

# --- 2. 定义WTForms表单 ---
class LoginForm(FlaskForm):
    password = PasswordField('密码', validators=[DataRequired()])

class GenerateCodesForm(FlaskForm):
    quantity = IntegerField('生成数量', default=10, validators=[DataRequired(), NumberRange(min=1, max=GENERATE_CODE_LIMIT, message=f"数量必须在1到{GENERATE_CODE_LIMIT}之间")])
    card_type = SelectField('卡类型', choices=list(CARD_DURATIONS.keys()))

# --- 3. 【全新】SQLite数据库辅助函数 ---
def get_db_connection():
    """创建并返回一个数据库连接，并设置行工厂为 sqlite3.Row"""
    conn = sqlite3.connect(DATABASE_FILE, timeout=10) # 增加超时以应对高并发
    conn.row_factory = sqlite3.Row # 这样可以像访问字典一样访问列
    return conn

def create_schema(conn):
    """创建数据库表结构"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            used_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_codes_used_by ON codes(used_by);

        CREATE TABLE IF NOT EXISTS devices (
            machine_id TEXT PRIMARY KEY,
            activation_code TEXT NOT NULL,
            card_type TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (activation_code) REFERENCES codes (code)
        );

        CREATE TABLE IF NOT EXISTS dictionary (
            glyph TEXT PRIMARY KEY,
            data TEXT NOT NULL
        );
    """)
    conn.commit()

def convert_json_to_sqlite():
    """
    【一次性迁移函数】
    如果SQLite数据库不存在，则自动从旧的JSON文件导入数据。
    """
    if os.path.exists(DATABASE_FILE):
        return # 数据库已存在，无需迁移

    logging.info("未找到SQLite数据库，开始从JSON文件进行一次性数据迁移...")
    
    try:
        with get_db_connection() as conn:
            create_schema(conn)
            
            # 迁移激活码
            if os.path.exists(OLD_CODES_DB_FILE):
                with open(OLD_CODES_DB_FILE, 'r', encoding='utf-8-sig') as f:
                    codes_data = json.load(f) if os.path.getsize(OLD_CODES_DB_FILE) > 0 else []
                if codes_data:
                    # 确保每个code对象都有type字段
                    for code in codes_data:
                        if 'type' not in code:
                            code['type'] = 'monthly' # 为旧数据提供默认值
                    conn.executemany(
                        "INSERT OR IGNORE INTO codes (code, type, used_by) VALUES (:code, :type, :used_by)",
                        codes_data
                    )
                logging.info(f"成功迁移 {len(codes_data)} 条激活码数据。")

            # 迁移设备
            if os.path.exists(OLD_DEVICES_DB_FILE):
                with open(OLD_DEVICES_DB_FILE, 'r', encoding='utf-8-sig') as f:
                    devices_data = json.load(f) if os.path.getsize(OLD_DEVICES_DB_FILE) > 0 else {}
                if devices_data:
                    device_list = [
                        {**v, "machine_id": k} for k, v in devices_data.items()
                    ]
                    conn.executemany(
                        "INSERT OR IGNORE INTO devices (machine_id, activation_code, card_type, activated_at, expires_at) VALUES (:machine_id, :activation_code, :card_type, :activated_at, :expires_at)",
                        device_list
                    )
                logging.info(f"成功迁移 {len(devices_data)} 条设备数据。")

            # 迁移字典
            if os.path.exists(OLD_DICTIONARY_FILE):
                with open(OLD_DICTIONARY_FILE, 'r', encoding='utf-8-sig') as f:
                    dict_data = json.load(f) if os.path.getsize(OLD_DICTIONARY_FILE) > 0 else {}
                if dict_data:
                    dict_list = [
                        {"glyph": k, "data": json.dumps(v, ensure_ascii=False)} for k, v in dict_data.items()
                    ]
                    conn.executemany(
                        "INSERT OR IGNORE INTO dictionary (glyph, data) VALUES (:glyph, :data)",
                        dict_list
                    )
                logging.info(f"成功迁移 {len(dict_data)} 条字典数据。")
            
            conn.commit()
            logging.info("✅ 数据迁移成功！建议您现在可以备份并删除旧的.json文件。")

    except Exception as e:
        logging.error(f"数据迁移失败: {e}")
        # 如果失败，删除可能已创建的不完整的数据库文件
        if os.path.exists(DATABASE_FILE):
            os.remove(DATABASE_FILE)
        raise

# --- 4. 授权检查装饰器 (已修复) ---
def require_activated_device(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        machine_id = str(request.json.get('machine_id'))
        if not machine_id: return jsonify({"error": "无效请求"}), 400
        
        with get_db_connection() as conn:
            device_info = conn.execute("SELECT expires_at FROM devices WHERE machine_id = ?", (machine_id,)).fetchone()

        if not device_info: return jsonify({"error": "未经授权"}), 403
        
        expires_at = datetime.fromisoformat(device_info['expires_at'].replace('Z', '+00:00'))
        if expires_at <= datetime.now(timezone.utc):
            logging.warning(f"已过期的设备尝试访问: {machine_id}")
            return jsonify({"error": "订阅已过期"}), 403
        
        return f(*args, **kwargs)
    
    return decorated_function

# --- 字典索引构建 (已更新为从SQLite加载) ---
dictionary_data, pinyin_index, char_type_index = {}, {}, {}
def build_indexes():
    global dictionary_data, pinyin_index, char_type_index
    logging.info("正在从SQLite构建字典索引...")
    with get_db_connection() as conn:
        rows = conn.execute("SELECT glyph, data FROM dictionary").fetchall()
    for row in rows:
        entry = json.loads(row['data'])
        dictionary_data[row['glyph']] = entry
        pinyin = (entry.get("pinyin") or "").lower()
        if pinyin: pinyin_index.setdefault(pinyin, []).append(entry)
        for char_type in entry.get("char_type", []):
            char_type_index.setdefault(char_type, []).append(entry)
    logging.info(f"索引构建完成，共加载 {len(dictionary_data)} 条目。")

# --- 监控相关代码 ---
stats_lock = threading.Lock()
total_requests, endpoint_counts = 0, Counter()
cpu_history, net_history = deque(maxlen=30), deque(maxlen=30)
last_net_io, last_net_time = psutil.net_io_counters(), time.time()

@app.after_request
def record_request_stats(response):
    excluded_endpoints = ('monitoring', 'management_data', 'revoke_authorization', 'manage', 'login', 'logout', 'static')
    if request.endpoint in excluded_endpoints:
        return response
    global total_requests
    with stats_lock:
        total_requests += 1
        endpoint_counts[request.endpoint or 'notfound'] += 1
    return response

@app.route('/api/monitoring_data')
def monitoring_data():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    global last_net_io, last_net_time
    with stats_lock:
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_history.append(cpu_percent)
        memory = psutil.virtual_memory()
        current_net_io = psutil.net_io_counters()
        current_time = time.time()
        time_diff = current_time - last_net_time
        bytes_sent_per_sec = (current_net_io.bytes_sent - last_net_io.bytes_sent) / time_diff if time_diff > 0 else 0
        bytes_recv_per_sec = (current_net_io.bytes_recv - last_net_io.bytes_recv) / time_diff if time_diff > 0 else 0
        last_net_io, last_net_time = current_net_io, time.time()
        net_history.append({"sent_kbps": bytes_sent_per_sec / 1024, "recv_kbps": bytes_recv_per_sec / 1024})
        top_5 = endpoint_counts.most_common(5)
        pie_labels = [item[0] for item in top_5]
        pie_data = [item[1] for item in top_5]
        other_count = total_requests - sum(pie_data)
        if other_count > 0:
            pie_labels.append('other')
            pie_data.append(other_count)
        response_data = {
            "system": {
                "cpu_percent": cpu_percent, "cpu_history": list(cpu_history),
                "mem_percent": memory.percent, "mem_used_mb": round(memory.used / 1e6, 2),
                "mem_total_mb": round(memory.total / 1e6, 2), "net_history": list(net_history)
            },
            "app": {
                "total_requests": total_requests,
                "endpoint_pie_chart": {"labels": pie_labels, "data": pie_data}
            }
        }
    return jsonify(response_data)

@app.route('/monitoring')
def monitoring():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('monitoring.html')

# --- 5. 核心业务路由 (已全面更新为SQLite) ---
def verify_password(stored_hash, provided_password):
    try:
        salt_hex, original_key_hex = stored_hash.split('$')
        salt = bytes.fromhex(salt_hex)
        derived_key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 260000)
        return hmac.compare_digest(bytes.fromhex(original_key_hex), derived_key)
    except (ValueError, IndexError):
        return False

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        if verify_password(ADMIN_PASSWORD_HASH, form.password.data):
            session['logged_in'] = True
            flash('登录成功！', 'success')
            logging.info("管理员登录成功。")
            return redirect(url_for('manage'))
        else:
            flash('密码错误。', 'error')
            logging.warning("失败的管理员登录尝试。")
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('您已成功登出。', 'success')
    return redirect(url_for('login'))

@app.route('/check_status', methods=['POST'])
def check_status():
    machine_id = str(request.json.get('machine_id'))
    if not machine_id: return jsonify({"error": "无效请求"}), 400
    
    with get_db_connection() as conn:
        device_info = conn.execute("SELECT card_type, expires_at FROM devices WHERE machine_id = ?", (machine_id,)).fetchone()

    if not device_info: return jsonify({"status": "unactivated"})
    
    expires_at = datetime.fromisoformat(device_info['expires_at'].replace('Z', '+00:00'))
    if expires_at > datetime.now(timezone.utc):
        return jsonify({"status": "activated", "expires_at": device_info['expires_at'], "card_type": device_info['card_type']})
    else:
        return jsonify({"status": "expired", "expires_at": device_info['expires_at']})

@app.route('/activate', methods=['POST'])
def activate():
    data = request.json
    machine_id, code_str = str(data.get('machine_id')), data.get('code')
    if not all([machine_id, code_str]): return jsonify({"error": "无效请求"}), 400

    try:
        with get_db_connection() as conn:
            # 检查激活码
            code_info = conn.execute("SELECT type, used_by FROM codes WHERE code = ?", (code_str,)).fetchone()
            if not code_info or code_info['used_by']:
                logging.warning(f"失败的激活尝试，激活码: {code_str}, 设备ID: {machine_id}")
                return jsonify({"error": "无效的激活码"}), 403
            # 检查设备
            device_info = conn.execute("SELECT 1 FROM devices WHERE machine_id = ?", (machine_id,)).fetchone()
            if device_info:
                logging.warning(f"重复激活尝试，设备ID: {machine_id}")
                return jsonify({"error": "操作失败"}), 409

            card_type = code_info['type']
            duration = CARD_DURATIONS.get(card_type)
            if not duration:
                logging.error(f"发现无效的卡类型 '{card_type}' 在激活码 {code_str} 中。")
                return jsonify({"error": "无效的卡类型"}), 500

            now = datetime.now(timezone.utc)
            expires_at = now + duration
            
            # 使用事务确保数据一致性
            cursor = conn.cursor()
            cursor.execute("UPDATE codes SET used_by = ? WHERE code = ?", (machine_id, code_str))
            cursor.execute(
                "INSERT INTO devices (machine_id, activation_code, card_type, activated_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (machine_id, code_str, card_type, now.isoformat().replace('+00:00', 'Z'), expires_at.isoformat().replace('+00:00', 'Z'))
            )
            conn.commit()

    except sqlite3.Error as e:
        logging.error(f"激活操作数据库错误: {e}")
        return jsonify({"error": "服务器内部错误"}), 500

    logging.info(f"设备 {machine_id} 使用激活码 {code_str} 成功激活。")
    return jsonify({"message": "激活成功！", "expires_at": expires_at.isoformat()})

@app.route('/get_identities', methods=['POST'])
@require_activated_device
def get_identities():
    char = request.json.get('char')
    entry = dictionary_data.get(char)
    if not entry: return jsonify({"error": f"字典中未找到 '{char}'"}), 404
    identities = [{"type": "definition", "query": char, "label": f"查看“{char}”的定义"}]
    if entry.get("is_phonetic_radical") or entry.get("components", {}).get("phonetic_radical"):
        identities.append({"type": "phonetic_group", "query": char, "label": f"查看“{char}”所属的形声字组"})
    return jsonify(identities)

@app.route('/advanced_search', methods=['POST'])
@require_activated_device
def advanced_search():
    search_type, query = request.json.get('search_type'), request.json.get('query')
    results = []
    if search_type == 'definition':
        if query in dictionary_data: results.append(dictionary_data[query])
    elif search_type == 'pinyin':
        results = pinyin_index.get(query.lower(), [])
    elif search_type == 'char_type':
        results = char_type_index.get(query, [])
    elif search_type == 'phonetic_group':
        entry = dictionary_data.get(query)
        radical = entry.get("components", {}).get("phonetic_radical") if entry else None
        if entry and entry.get("is_phonetic_radical"): radical = query
        if radical:
            results = [e for e in dictionary_data.values() if e.get("components", {}).get("phonetic_radical") == radical or e.get('glyph') == radical]
        elif entry:
            results = [entry]
    unique_results = list({item['glyph']: item for item in results}.values())
    return jsonify(unique_results)

# --- 6. 管理面板路由 (已全面更新为SQLite) ---
@app.route('/manage', methods=['GET', 'POST'])
def manage():
    if not session.get('logged_in'): return redirect(url_for('login'))
    form = GenerateCodesForm()
    if form.validate_on_submit():
        quantity = form.quantity.data
        card_type = form.card_type.data
        new_codes = [{"code": str(uuid.uuid4()).split('-')[0].upper(), "type": card_type, "used_by": None} for _ in range(quantity)]
        
        try:
            with get_db_connection() as conn:
                conn.executemany("INSERT INTO codes (code, type, used_by) VALUES (:code, :type, :used_by)", new_codes)
                conn.commit()
            flash(f"成功生成 {quantity} 个新的 {card_type} 激活码！", "success")
            logging.info(f"管理员生成了 {quantity} 个类型为 {card_type} 的新激活码。")
        except sqlite3.Error as e:
            flash("生成激活码时发生数据库错误。", "error")
            logging.error(f"生成激活码数据库错误: {e}")
            
        return redirect(url_for('manage'))
    return render_template('manage.html', form=form)

@app.route('/api/management_data')
def management_data():
    if not session.get('logged_in'): return jsonify({"error": "未经授权"}), 401
    
    code_page = request.args.get('code_page', 1, type=int)
    code_per_page = request.args.get('code_per_page', 10, type=int)
    code_search = request.args.get('code_search', '', type=str)
    show_unused = request.args.get('show_unused', 'false', type=str).lower() == 'true'
    
    device_page = request.args.get('device_page', 1, type=int)
    device_per_page = request.args.get('device_per_page', 10, type=int)
    device_search = request.args.get('device_search', '', type=str)
    
    with get_db_connection() as conn:
        # 构建激活码查询
        code_query_base = "FROM codes"
        code_params = []
        conditions = []
        if code_search:
            conditions.append("(code LIKE ? OR used_by LIKE ?)")
            code_params.extend([f"%{code_search}%", f"%{code_search}%"])
        if show_unused:
            conditions.append("used_by IS NULL")
        if conditions:
            code_query_base += " WHERE " + " AND ".join(conditions)
        
        total_codes = conn.execute(f"SELECT COUNT(*) {code_query_base}", code_params).fetchone()[0]
        codes_query = f"SELECT * {code_query_base} ORDER BY code DESC LIMIT ? OFFSET ?"
        code_params.extend([code_per_page, (code_page - 1) * code_per_page])
        codes_items = [dict(row) for row in conn.execute(codes_query, code_params).fetchall()]

        # 构建设备查询
        device_query_base = "FROM devices"
        device_params = []
        if device_search:
            device_query_base += " WHERE machine_id LIKE ?"
            device_params.append(f"%{device_search}%")
            
        total_devices = conn.execute(f"SELECT COUNT(*) {device_query_base}", device_params).fetchone()[0]
        devices_query = f"SELECT * {device_query_base} ORDER BY activated_at DESC LIMIT ? OFFSET ?"
        device_params.extend([device_per_page, (device_page - 1) * device_per_page])
        devices_items = [dict(row) for row in conn.execute(devices_query, device_params).fetchall()]

    return jsonify({
        "codes": {"items": codes_items, "total": total_codes, "page": code_page, "per_page": code_per_page},
        "devices": {"items": devices_items, "total": total_devices, "page": device_page, "per_page": device_per_page}
    })

@app.route('/api/revoke_authorization', methods=['POST'])
def revoke_authorization():
    if not session.get('logged_in'): return jsonify({"error": "未经授权"}), 401
    machine_id = request.json.get('machine_id')
    if not machine_id: return jsonify({"error": "无效请求"}), 400
    
    try:
        with get_db_connection() as conn:
            # 先找到对应的激活码
            device_info = conn.execute("SELECT activation_code FROM devices WHERE machine_id = ?", (machine_id,)).fetchone()
            if not device_info:
                return jsonify({"error": "设备未找到"}), 404
            
            code_to_reset = device_info['activation_code']
            
            # 使用事务确保原子性
            cursor = conn.cursor()
            cursor.execute("DELETE FROM devices WHERE machine_id = ?", (machine_id,))
            if code_to_reset:
                cursor.execute("UPDATE codes SET used_by = NULL WHERE code = ?", (code_to_reset,))
            conn.commit()

    except sqlite3.Error as e:
        logging.error(f"撤销授权数据库错误: {e}")
        return jsonify({"error": "服务器内部错误"}), 500

    logging.info(f"设备 {machine_id} 的授权已被撤销。")
    return jsonify({"message": "授权已成功撤销。"})

# --- CSRF 豁免 ---
csrf.exempt(check_status)
csrf.exempt(activate)
csrf.exempt(get_identities)
csrf.exempt(advanced_search)

# --- 7. 应用启动入口 ---
if __name__ == '__main__':
    # 【关键】在应用启动前执行一次性数据迁移
    convert_json_to_sqlite()
    
    build_indexes()
    threads = (os.cpu_count() or 1) * 2
    logging.info(f"✅ 启动生产级服务器 Waitress (http://0.0.0.0:5000)，使用 {threads} 个线程。")
    serve(app, host='0.0.0.0', port=5000, threads=threads)
