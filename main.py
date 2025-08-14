# --- START OF FILE main.py (Final Corrected Version) ---

import asyncio
import json
import os
import uuid
from datetime import datetime

import bleach
import flet as ft
import requests

# --- 常量与辅助函数 ---
SERVER_URL = "http://103.217.184.120:5000/"
CLIENT_CONFIG_FILE = "client_config.json"


def get_persistent_machine_id():
    """
    获取一个持久化的、基于UUID的设备ID。
    首次运行时生成并保存，后续从本地文件读取。
    """
    if os.path.exists(CLIENT_CONFIG_FILE):
        try:
            with open(CLIENT_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                machine_id = config.get("machine_id")
                if machine_id:
                    return machine_id
        except (IOError, json.JSONDecodeError):
            pass

    new_machine_id = str(uuid.uuid4())
    try:
        with open(CLIENT_CONFIG_FILE, 'w') as f:
            json.dump({"machine_id": new_machine_id}, f)
    except IOError:
        print(f"警告：无法将设备ID写入到 {CLIENT_CONFIG_FILE}。本次运行将使用临时ID。")

    return new_machine_id


class AppState:
    """集中管理应用状态"""

    def __init__(self):
        self.machine_id = get_persistent_machine_id()
        self.is_activated = False
        self.expires_at = None
        self.card_type = None


# --- 【新增】结果显示辅助函数 ---
def create_result_display(data):
    """
    根据单条查询结果数据，构建一个信息完整的显示卡片。
    这个函数的功能复刻自 old_main.py 中的 create_result_card。
    """
    parts = []

    # 1. 标题：字形和拼音
    glyph = data.get("glyph", "")
    pinyin = data.get("pinyin", "")
    if glyph:
        parts.append(f"### {glyph} ({pinyin})")

    # 2. 类型
    char_type = data.get("char_type")
    if char_type and isinstance(char_type, list):
        parts.append(f'**类型:** `{" / ".join(char_type)}`')

    # 3. 分析（结构和解析）
    analysis = data.get("analysis", {})
    if isinstance(analysis, dict):
        structure = analysis.get("structure")
        if structure:
            parts.append(f'**结构:** {structure}')
        explanation = analysis.get("explanation")
        if explanation:
            # 清理HTML以安全显示
            safe_explanation = bleach.clean(explanation)
            parts.append(f'**解析:** {safe_explanation}')

    # 4. 本意/定义
    definition = data.get("definition")
    if definition:
        safe_definition = bleach.clean(definition)
        parts.append(f'**本意:** {safe_definition}')

    # 5. 组词
    phrases = data.get("phrases")
    if phrases and isinstance(phrases, list):
        parts.append(f'**组词:** `{"、".join(phrases)}`')

    # 将所有部分用换行符合并成最终的Markdown文本
    final_text = "\n\n".join(parts)

    # 返回一个带边框和内边距的容器，使其成为一个卡片
    return ft.Container(
        content=ft.Markdown(final_text, selectable=True, extension_set=ft.MarkdownExtensionSet.COMMON_MARK),
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=ft.border_radius.all(5),
        padding=10,
        margin=ft.margin.only(bottom=10)  # 增加卡片间的间距
    )


# --- 主应用 ---
async def main(page: ft.Page):
    page.title = "字典查询工具"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.window_width = 400
    page.window_height = 600
    page.theme_mode = ft.ThemeMode.LIGHT

    state = AppState()

    # --- 核心网络请求函数 ---
    async def perform_request(url, payload, timeout=15):
        try:
            response = await asyncio.to_thread(
                requests.post, url, json=payload, timeout=timeout, data=None)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            try:
                error_data = e.response.json()
                return {"error": error_data.get("error", "服务器返回了一个未知错误")}
            except json.JSONDecodeError:
                return {"error": f"服务器错误 (状态码: {e.response.status_code})"}
        except requests.exceptions.ConnectionError:
            return {"error": "网络错误：无法连接到服务器。"}
        except requests.exceptions.Timeout:
            return {"error": "网络错误：服务器响应超时。"}
        except Exception as e:
            return {"error": f"发生了一个意外错误: {e}"}

    # --- UI更新与业务逻辑 ---
    def update_ui_sync():
        is_activated = state.is_activated
        activation_view.visible = not is_activated
        main_view.visible = is_activated

        status_value, status_color = ("检查中...", ft.Colors.GREY)
        if state.is_activated:
            status_value, status_color = (f"已激活 ({state.card_type})", ft.Colors.GREEN_700)
        else:
            status_value, status_color = ("未激活", ft.Colors.RED_700)

        status_text.value = f"状态: {status_value}"
        status_text.color = status_color
        expires_text.value = f"到期时间: {state.expires_at}" if state.expires_at else ""
        page.update()

    async def check_activation_status(show_success=False):
        status_progress.visible = True
        page.update()

        result = await perform_request(f"{SERVER_URL}/check_status", {"machine_id": state.machine_id})

        status_progress.visible = False
        if "error" in result:
            status_text.value = f"错误: {result['error']}"
            state.is_activated = False
        else:
            if result.get("status") == "activated":
                state.is_activated = True
                expires_dt = datetime.fromisoformat(result.get("expires_at").replace('Z', '+00:00'))
                state.expires_at = expires_dt.strftime('%Y-%m-%d %H:%M:%S')
                state.card_type = result.get("card_type")
                if show_success:
                    page.snack_bar = ft.SnackBar(content=ft.Text("激活成功！"), bgcolor=ft.Colors.GREEN_700)
                    page.snack_bar.open = True
            else:
                state.is_activated = False
                state.expires_at = None
                state.card_type = None

        update_ui_sync()

    async def activate_with_code(e):
        code = activation_code_input.value.strip().upper()
        if not code:
            activation_code_input.error_text = "激活码不能为空"
            page.update()
            return

        activation_button.disabled = True
        activation_button.text = "激活中..."
        page.update()

        result = await perform_request(f"{SERVER_URL}/activate", {"machine_id": state.machine_id, "code": code})

        if "error" in result:
            activation_code_input.error_text = result["error"]
        else:
            activation_code_input.value = ""
            activation_code_input.error_text = None
            await check_activation_status(show_success=True)

        activation_button.disabled = False
        activation_button.text = "激 活"
        page.update()

    async def copy_machine_id(e):
        page.set_clipboard(state.machine_id)
        page.snack_bar = ft.SnackBar(content=ft.Text("设备ID已复制到剪贴板！"), duration=2000)
        page.snack_bar.open = True
        page.update()

    # 【重大修改】此函数现在使用 create_result_display 来显示完整信息
    async def handle_identity_click(e):
        search_type = e.control.data["type"]
        query = e.control.data["query"]

        results_view.controls = [ft.Row([ft.ProgressRing()], alignment=ft.MainAxisAlignment.CENTER)]
        page.update()

        result = await perform_request(f"{SERVER_URL}/advanced_search",
                                       {"machine_id": state.machine_id, "search_type": search_type, "query": query})

        results_view.controls.clear()
        if "error" in result:
            results_view.controls.append(ft.Text(result["error"], color=ft.Colors.RED))
        elif result and isinstance(result, list):
            # 对返回的每一个结果，都使用新的辅助函数创建卡片
            for item in result:
                result_card = create_result_display(item)
                results_view.controls.append(result_card)
        else:
            results_view.controls.append(ft.Text("未找到结果。"))

        page.update()

    async def perform_search(e):
        query = search_input.value.strip()
        if not query: return

        results_view.controls = [ft.Row([ft.ProgressRing()], alignment=ft.MainAxisAlignment.CENTER)]
        page.update()

        result = await perform_request(f"{SERVER_URL}/get_identities",
                                       {"machine_id": state.machine_id, "char": query})

        results_view.controls.clear()
        if "error" in result:
            results_view.controls.append(ft.Text(result["error"], color=ft.Colors.RED))
        elif result:
            results_view.controls.append(
                ft.Text(f"请选择您要查询“{query}”的哪个身份：", weight=ft.FontWeight.BOLD)
            )
            for identity in result:
                btn = ft.ElevatedButton(
                    text=identity.get("label"),
                    data={"type": identity.get("type"), "query": identity.get("query")},
                    on_click=handle_identity_click,
                    width=350
                )
                results_view.controls.append(btn)
        else:
            results_view.controls.append(ft.Text(f"未找到与“{query}”相关的操作。"))

        page.update()

    # --- UI 控件定义 ---
    status_text = ft.Text("状态: 检查中...", weight=ft.FontWeight.BOLD)
    expires_text = ft.Text("")
    status_progress = ft.ProgressRing(width=16, height=16, visible=False)

    activation_code_input = ft.TextField(label="请输入激活码", width=280, on_submit=activate_with_code)
    activation_button = ft.ElevatedButton(text="激 活", on_click=activate_with_code, icon=ft.Icons.KEY)

    machine_id_text = ft.TextField(value=state.machine_id, read_only=True, label="本机设备ID", expand=True)
    copy_button = ft.IconButton(icon=ft.Icons.COPY, on_click=copy_machine_id, tooltip="复制设备ID")

    search_input = ft.TextField(label="输入查询的字词", expand=True, on_submit=perform_search)
    search_button = ft.IconButton(icon=ft.Icons.SEARCH, on_click=perform_search, tooltip="查询")
    results_view = ft.ListView(expand=True, spacing=0, auto_scroll=True)  # spacing=0,间距由卡片margin控制

    # --- 视图定义 ---
    activation_view = ft.Column(
        visible=False,
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=20,
        controls=[
            ft.Text("软件未激活", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("请输入激活码以解锁全部功能", color=ft.Colors.GREY_600),
            activation_code_input,
            activation_button,
            ft.Divider(),
            ft.Row([machine_id_text, copy_button], alignment=ft.MainAxisAlignment.CENTER),
        ]
    )

    main_view = ft.Column(
        visible=False,
        expand=True,
        controls=[
            ft.Row([search_input, search_button]),
            results_view,
        ]
    )

    # --- 页面布局 ---
    page.add(
        ft.Row([status_text, status_progress]),
        expires_text,
        ft.Divider(),
        ft.Container(
            content=ft.Stack([activation_view, main_view]),
            expand=True,
        ),
    )

    # --- 初始加载 ---
    await check_activation_status()


if __name__ == "__main__":
    ft.app(target=main)

# --- END OF FILE main.py (Final Corrected Version) ---