import os
import time
import requests
import zipfile
import io
import datetime
import re
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 基础工具 (保持不变) ====================
def log(message):
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\[{current_time}\] {message}", flush=True)

def download_silk():
    extract_dir = "extensions/silk_ext";
    if os.path.exists(extract_dir): return os.path.abspath(extract_dir)
    log(">>> \[插件1\] 正在下载 Silk Privacy Pass...");
    try:
        url="https://clients2.google.com/service/update2/crx?response=redirect&prodversion=122.0&acceptformat=crx2,crx3&x=id%3Dajhmfdgkijocedmfjonnpjfojldioehi%26uc";
        resp=requests.get(url,stream=True,timeout=30);
        if resp.status_code==200: os.makedirs("extensions",exist_ok=True); zipfile.ZipFile(io.BytesIO(resp.content)).extractall(extract_dir); return os.path.abspath(extract_dir)
    except Exception as e: log(f"❌ \[插件1\] 下载异常: {e}"); return None

def download_cf_autoclick():
    extract_root="extensions/cf_autoclick_root";
    if not os.path.exists(extract_root):
        log(">>> \[插件2\] 正在下载 CF-AutoClick...");
        try:
            url="https://codeload.github.com/tenacious6/cf-autoclick/zip/refs/heads/master";
            resp=requests.get(url,stream=True,timeout=30);
            if resp.status_code==200: os.makedirs("extensions",exist_ok=True); zipfile.ZipFile(io.BytesIO(resp.content)).extractall(extract_root)
            else: log(f"❌ \[插件2\] 下载失败: {resp.status_code}");return None
        except Exception as e: log(f"❌ \[插件2\] 异常: {e}"); return None
    for r,_,f in os.walk(extract_root):
        if "manifest.json" in f: log(f"✅ \[插件2\] 路径锁定: {os.path.basename(r)}"); return os.path.abspath(r)
    return None

# ==================== 截图上传与通知 (保持不变) ====================
class Reporter:
    def __init__(self):
        self.screenshots = []
        self.session = requests.Session()

    def add_screenshot(self, page, name):
        try:
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            filename = f"{timestamp}_{name}.png"
            page.get_screenshot(path=filename, full_page=True)
            self.screenshots.append(filename)
            log(f"📸 已保存截图: {filename}")
        except Exception as e:
            log(f"⚠️ 截图失败: {e}")

    def upload_to_telegraph(self) -> str:
        if not self.screenshots: return "没有可上传的截图。"
        log(">>> 正在上传截图到 Telegra.ph...")
        try:
            valid_screenshots = [f for f in self.screenshots if os.path.exists(f)]
            if not valid_screenshots: return "没有有效的截图文件可上传。"
            files_to_upload = [('file', (os.path.basename(f), open(f, 'rb'), 'image/png')) for f in valid_screenshots]
            upload_resp = self.session.post('https://telegra.ph/upload', files=files_to_upload, timeout=45)
            if upload_resp.status_code != 200: return f"上传失败: {upload_resp.text}"
            content_nodes = []
            for i, item in enumerate(upload_resp.json()):
                src = item.get('src')
                if src: content_nodes.append({"tag": "figure", "children": [{"tag": "img", "attrs": {"src": src}}, {"tag": "figcaption", "children": [os.path.basename(valid_screenshots[i])]}]})
            create_page_resp = self.session.post('https://api.telegra.ph/createPage', data={'access_token': 'd525af2963a7633918569c76192a83e0c03423b98471415053f40f0653d9', 'title': f'Katabump 续期调试报告 - {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}', 'author_name': 'Auto-Renew Script', 'content': str(content_nodes).replace("'", '"')}, timeout=20)
            if create_page_resp.status_code == 200 and create_page_resp.json().get('ok'):
                page_url = create_page_resp.json()['result']['url']; log(f"✅ 截图报告已生成: {page_url}"); return page_url
            else: return f"创建页面失败: {create_page_resp.text}"
        except Exception as e:
            log(f"❌ 上传异常: {e}"); return f"上传截图时发生异常: {e}"
        finally:
            for f in self.screenshots:
                try: os.remove(f)
                except: pass

    def send_telegram_notification(self, message: str):
        token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if not all([token, chat_id]): log("⚠️ Telegram Token 或 Chat ID 未设置，跳过通知。"); return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
        try:
            requests.post(url, json=data, timeout=20); log("✅ Telegram 通知已发送。")
        except Exception as e:
            log(f"❌ Telegram 发送异常: {e}")

# ==================== 核心逻辑 (保持不变) ====================
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

# ==================== 主程序（最终“黑盒等待”版） ====================
def job():
    reporter = Reporter()
    page = None
    final_status_message = "任务因未知原因中断"
    
    try:
        reporter.send_telegram_notification("🚀 **Katabump 自动续期任务开始...**")
        
        path_silk = download_silk(); path_cf = download_cf_autoclick()
        co = ChromiumOptions(); co.set_argument('--headless=new'); co.set_argument('--no-sandbox'); co.set_argument('--disable-gpu'); co.set_argument('--disable-dev-shm-usage'); co.set_argument('--window-size=1920,1080'); co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        plugin_count = 0
        if path_silk: co.add_extension(path_silk); plugin_count += 1
        if path_cf: co.add_extension(path_cf); plugin_count += 1
        log(f">>> \[浏览器\] 已挂载插件数量: {plugin_count}")
        co.auto_port(); page = ChromiumPage(co); page.set.timeouts(20)
        
        email = os.environ.get("KB_EMAIL"); password = os.environ.get("KB_PASSWORD"); target_url = os.environ.get("KB_RENEW_URL")
        if not all([email, password, target_url]): raise Exception("环境变量KB_EMAIL, KB_PASSWORD, KB_RENEW_URL未设置")

        log(">>> \[Step 1\] 登录..."); page.get('https://dashboard.katabump.com/auth/login'); pass_full_page_shield(page)
        reporter.add_screenshot(page, "01_login_page")
        if page.ele('css:input[name="email"]'):
            page.ele('css:input[name="email"]').input(email); page.ele('css:input[name="password"]').input(password); page.ele('css:button#submit').click()
            page.wait.url_change('login', exclude=True, timeout=20)
        
        max_retries = 3; success = False
        for attempt in range(1, max_retries + 1):
            log(f"\n🚀 \[Step 2\] 尝试续期 (第 {attempt} 次)..."); page.get(target_url); pass_full_page_shield(page)
            reporter.add_screenshot(page, f"02_attempt_{attempt}_main_page")
            
            try:
                renew_btn = page.wait.ele_displayed('css:button[data-bs-target="#renew-modal"]', timeout=30)
                if not renew_btn:
                    if analyze_page_alert(page) == "SUCCESS_TOO_EARLY": success = True; final_status_message = "任务成功完成！状态: SUCCESS_TOO_EARLY"; break
                    continue

                log(">>> 点击主页面 Renew 按钮..."); renew_btn.click(by_js=True)
                modal = page.wait.ele_displayed('css:.modal-content', timeout=10)
                if not modal: log("❌ 弹窗未出"); continue
                
                reporter.add_screenshot(page, f"03_attempt_{attempt}_modal_opened")
                
                # ========== 最终的“黑盒等待”策略 ==========
                log(">>> \[操作\] 弹窗出现，进入“黑盒”等待模式...")
                log(">>> \[黑盒等待\] 给予插件 20 秒的独立工作时间，期间脚本不进行任何干扰...")
                time.sleep(20)
                log(">>> \[黑盒等待\] 等待结束。现在，我们假设验证已成功。")
                reporter.add_screenshot(page, f"04_attempt_{attempt}_after_wait")
                # ==========================================
                
                final_renew_btn = modal.ele('css:button[type="submit"].btn-primary:text("Renew")')
                if final_renew_btn and final_renew_btn.states.is_enabled:
                    log(">>> Renew 按钮已激活，直接点击..."); 
                    final_renew_btn.click(by_js=True)
                else:
                    log("⚠️ Renew 按钮未激活或未找到，尝试强制点击（如果存在）...");
                    if final_renew_btn: final_renew_btn.click(by_js=True)
                    else: raise Exception("在黑盒等待后，依然找不到最终的Renew按钮。")

                log(">>> 等待最终响应 (8s)..."); time.sleep(8)
                reporter.add_screenshot(page, f"05_attempt_{attempt}_after_submit")
                
                result = analyze_page_alert(page)
                if result in ["SUCCESS", "SUCCESS_TOO_EARLY"]:
                    final_status_message = f"任务成功完成！状态: {result}"; log(f"🎉 {final_status_message}"); success = True; break
                elif result == "FAIL_CAPTCHA": log("⚠️ 提交后服务器返回验证失败，刷新重试..."); time.sleep(3); continue
                else: log("❓ 发生未知错误，重试..."); continue

            except Exception as e_inner:
                log(f"⚠️ 第 {attempt} 次尝试中发生错误: {e_inner}"); reporter.add_screenshot(page, f"06_attempt_{attempt}_error"); continue

        if not success:
            final_status_message = "所有重试均失败"
            raise Exception(final_status_message)

    except Exception as e_outer:
        final_status_message = f"发生严重异常: {e_outer}"
        log(f"❌ {final_status_message}")
        if page: reporter.add_screenshot(page, "99_CRITICAL_ERROR")
    
    finally:
        log(f"🏁 任务结束。最终状态: {final_status_message}")
        report_url = reporter.upload_to_telegraph()
        
        if "成功" in final_status_message or "未到期" in final_status_message:
            notification_message = f"✅ **Katabump 续期任务成功！**\n\n<b>状态:</b>\n<code>{final_status_message}</code>\n\n<b>调试报告:</b>\n{report_url}"
        else:
            notification_message = f"❌ **Katabump 续期任务失败**\n\n<b>错误:</b>\n<code>{final_status_message}</code>\n\n<b>调试报告:</b>\n{report_url}"
            
        reporter.send_telegram_notification(notification_message)
        
        if page: page.quit()
        
        if "成功" not in final_status_message and "未到期" not in final_status_message:
            exit(1)

if __name__ == "__main__":
    job()
