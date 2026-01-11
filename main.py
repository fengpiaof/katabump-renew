import os
import time
import requests
import zipfile
import io
import datetime
import re
import asyncio
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 基础工具 ====================
def log(message):
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\[{current_time}\] {message}", flush=True)

def download_silk():
    """【插件1】Silk Privacy Pass"""
    extract_dir = "extensions/silk_ext"
    if os.path.exists(extract_dir): return os.path.abspath(extract_dir)
    log(">>> \[插件1\] 正在下载 Silk Privacy Pass...")
    try:
        url = "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=122.0&acceptformat=crx2,crx3&x=id%3Dajhmfdgkijocedmfjonnpjfojldioehi%26uc"
        resp = requests.get(url, stream=True, timeout=30)
        if resp.status_code == 200:
            os.makedirs("extensions", exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                zf.extractall(extract_dir)
            return os.path.abspath(extract_dir)
    except Exception as e:
        log(f"❌ \[插件1\] 下载异常: {e}")
    return None

def download_cf_autoclick():
    """【插件2】CF-AutoClick"""
    extract_root = "extensions/cf_autoclick_root"
    if not os.path.exists(extract_root):
        log(">>> \[插件2\] 正在下载 CF-AutoClick...")
        try:
            url = "https://codeload.github.com/tenacious6/cf-autoclick/zip/refs/heads/master"
            resp = requests.get(url, stream=True, timeout=30)
            if resp.status_code == 200:
                os.makedirs("extensions", exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    zf.extractall(extract_root)
            else:
                log(f"❌ \[插件2\] 下载失败: {resp.status_code}")
                return None
        except Exception as e:
            log(f"❌ \[插件2\] 异常: {e}")
            return None
    for root, _, files in os.walk(extract_root):
        if "manifest.json" in files:
            log(f"✅ \[插件2\] 路径锁定: {os.path.basename(root)}")
            return os.path.abspath(root)
    return None

# ==================== 新增：截图上传与通知 ====================
class Reporter:
    def __init__(self):
        self.screenshots = []
        self.session = requests.Session()

    def add_screenshot(self, page, name):
        try:
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            filename = f"{timestamp}_{name}.png"
            # DrissionPage 使用 save 方法保存截图
            page.save(save_path='.', file_name=filename)
            self.screenshots.append(filename)
            log(f"📸 已保存截图: {filename}")
        except Exception as e:
            log(f"⚠️ 截图失败: {e}")

    def upload_to_telegraph(self) -> str:
        if not self.screenshots:
            return "没有可上传的截图。"
        log(">>> 正在上传截图到 Telegra.ph...")
        try:
            files_to_upload = [('file', (os.path.basename(f), open(f, 'rb'), 'image/png')) for f in self.screenshots]
            upload_resp = self.session.post('https://telegra.ph/upload', files=files_to_upload, timeout=45)
            if upload_resp.status_code != 200:
                return f"上传失败: {upload_resp.text}"

            content_nodes = []
            for i, item in enumerate(upload_resp.json()):
                src = item.get('src')
                if src:
                    content_nodes.append({"tag": "figure", "children": [
                        {"tag": "img", "attrs": {"src": src}},
                        {"tag": "figcaption", "children": [os.path.basename(self.screenshots[i])]}
                    ]})
            
            # 使用 requests.post 替代，因为 aiohttp 在这个同步函数中不适用
            create_page_resp = self.session.post('https://api.telegra.ph/createPage', data={
                'access_token': 'd525af2963a7633918569c76192a83e0c03423b98471415053f40f0653d9', # 匿名token
                'title': f'Katabump 续期调试报告 - {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}',
                'author_name': 'Auto-Renew Script',
                'content': str(content_nodes).replace("'", '"')
            }, timeout=20)
            
            if create_page_resp.status_code == 200 and create_page_resp.json().get('ok'):
                page_url = create_page_resp.json()['result']['url']
                log(f"✅ 截图报告已生成: {page_url}")
                return page_url
            else:
                return f"创建页面失败: {create_page_resp.text}"
        except Exception as e:
            log(f"❌ 上传异常: {e}")
            return f"上传截图时发生异常: {e}"
        finally:
            for f in self.screenshots:
                try: os.remove(f)
                except: pass

    def send_telegram_notification(self, message: str):
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not all([token, chat_id]):
            log("⚠️ Telegram Token 或 Chat ID 未设置，跳过通知。")
            return
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
        
        try:
            # 在同步函数中使用 requests
            requests.post(url, json=data, timeout=20)
            log("✅ Telegram 通知已发送。")
        except Exception as e:
            log(f"❌ Telegram 发送异常: {e}")

# ==================== 核心逻辑 ====================
def pass_full_page_shield(page):
    for _ in range(3):
        if "just a moment" in page.title.lower(): log("--- \[门神\] 全屏盾出现，等待..."); time.sleep(3)
        else: return True
    return False

def analyze_page_alert(page):
    log(">>> \[系统\] 检查结果...");
    danger = page.ele('css:.alert.alert-danger', timeout=3);
    if danger and danger.states.is_displayed:
        text=danger.text;log(f"⬇️ 红色提示: {text}");
        if "can't renew" in text.lower(): log(f"✅ \[结果\] 未到期"); return "SUCCESS_TOO_EARLY"
        elif "captcha" in text.lower(): return "FAIL_CAPTCHA"
        return "FAIL_OTHER"
    success = page.ele('css:.alert.alert-success', timeout=3);
    if success and success.states.is_displayed: log(f"⬇️ 绿色提示: {success.text}");log("🎉 \[结果\] 续期成功！"); return "SUCCESS"
    return "UNKNOWN"

# ==================== 主程序 ====================
def job():
    reporter = Reporter()
    page = None
    final_status_message = "任务因未知原因中断"
    final_result = "UNKNOWN"
    
    try:
        reporter.send_telegram_notification("🚀 **Katabump 自动续期任务开始...**")
        
        # --- 准备工作 ---
        path_silk = download_silk()
        path_cf = download_cf_autoclick()
        co
