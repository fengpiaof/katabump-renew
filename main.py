import os
import time
import requests
import zipfile
import io
import datetime
import re
import asyncio # 引入asyncio以备不时之需
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
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, stream=True, timeout=30)
        if resp.status_code == 200:
            if not os.path.exists("extensions"): os.makedirs("extensions")
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
        log(">>> \[插件2\] 正在下载 CF-AutoClick (Master)...")
        try:
            url = "https://codeload.github.com/tenacious6/cf-autoclick/zip/refs/heads/master"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, stream=True, timeout=30)
            if resp.status_code == 200:
                if not os.path.exists("extensions"): os.makedirs("extensions")
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

# ==================== 核心逻辑 ====================
def pass_full_page_shield(page):
    """处理全屏盾"""
    for _ in range(3):
        if "just a moment" in page.title.lower():
            log("--- \[门神\] 全屏盾出现，等待双插件配合过盾...")
            time.sleep(3)
        else:
            return True
    return False

def manual_click_checkbox(modal):
    """【补刀逻辑】手动点击 checkbox"""
    log(">>> \[补刀\] 检查是否需要手动点击...")
    try:
        iframe = modal.ele('css:iframe[src*="cloudflare"], iframe[src*="turnstile"]', timeout=3)
        if iframe:
            checkbox = iframe.ele('css:input[type="checkbox"]', timeout=2)
            if checkbox and checkbox.states.is_visible:
                log(">>> \[补刀\] 🎯 在 iframe 里点击 Checkbox！")
                checkbox.click(by_js=True)
                return True
        checkbox_ext = modal.ele('css:input[type="checkbox"]', timeout=1)
        if checkbox_ext and checkbox_ext.states.is_visible:
            log(">>> \[补刀\] 🎯 在外部点击 Checkbox！")
            checkbox_ext.click(by_js=True)
            return True
    except Exception:
        pass # 找不到元素是正常的
    log(">>> \[补刀\] 未找到需要点击的Checkbox (可能插件已完成点击)")
    return False

def analyze_page_alert(page):
    """解析结果"""
    log(">>> \[系统\] 检查结果...")
    danger = page.ele('css:.alert.alert-danger', timeout=3)
    if danger and danger.states.is_displayed:
        text = danger.text
        log(f"⬇️ 红色提示: {text}")
        if "can't renew" in text.lower():
            match = re.search(r'in (\d+) day', text)
            days = match.group(1) if match else "?"
            log(f"✅ \[结果\] 未到期 (等待 {days} 天)")
            return "SUCCESS_TOO_EARLY"
        elif "captcha" in text.lower():
            return "FAIL_CAPTCHA"
        return "FAIL_OTHER"
    success = page.ele('css:.alert.alert-success', timeout=3)
    if success and success.states.is_displayed:
        log(f"⬇️ 绿色提示: {success.text}")
        log("🎉 \[结果\] 续期成功！")
        return "SUCCESS"
    return "UNKNOWN"

# ==================== 主程序 ====================
def job():
    path_silk = download_silk()
    path_cf = download_cf_autoclick()
    
    co = ChromiumOptions()
    co.set_argument('--headless=new')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--window-size=1920,1080')
    co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
    
    plugin_count = 0
    if path_silk: co.add_extension(path_silk); plugin_count += 1
    if path_cf: co.add_extension(path_cf); plugin_count += 1
    log(f">>> \[浏览器\] 已挂载插件数量: {plugin_count}")
        
    co.auto_port()
    page = ChromiumPage(co)
    page.set.timeouts(15)
    
    try:
        email = os.environ.get("KB_EMAIL")
        password = os.environ.get("KB_PASSWORD")
        target_url = os.environ.get("KB_RENEW_URL")
        
        if not all([email, password, target_url]): log("❌ 配置缺失"); exit(1)

        log(">>> \[Step 1\] 登录...")
        page.get('https://dashboard.katabump.com/auth/login')
        pass_full_page_shield(page)
        if page.ele('css:input[name="email"]'):
            page.ele('css:input[name="email"]').input(email)
            page.ele('css:input[name="password"]').input(password)
            page.ele('css:button#submit').click()
            page.wait.url_change('login', exclude=True, timeout=20)
        
        # Step 2: 循环重试
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            log(f"\n🚀 \[Step 2\] 尝试续期 (第 {attempt} 次)...")
            page.get(target_url)
            pass_full_page_shield(page)
            
            renew_btn = None
            try:
                renew_btn = page.wait.ele_displayed('css:button[data-bs-target="#renew-modal"]', timeout=30)
            except Exception as e:
                log(f"⚠️ 在30秒内未能找到主页面的 Renew 按钮: {e}")

            if renew_btn:
                log(">>> 点击主页面 Renew 按钮...")
                renew_btn.click(by_js=True)
                
                log(">>> 等待弹窗出现...")
                modal = page.ele('css:.modal-content', timeout=10)
                
                if modal:
                    log(">>> \[操作\] 弹窗出现，开始处理Cloudflare验证...")
                    iframe = modal.ele('css:iframe[src*="cloudflare"], iframe[src*="turnstile"]', timeout=10)
                    if not iframe:
                        log("⚠️ 在弹窗中未能找到Cloudflare iframe，流程可能已改变。")
                        continue
                    
                    log(">>> iframe 已找到，给予插件5秒优先处理时间...")
                    time.sleep(5)
                    
                    manual_click_checkbox(modal)

                    log(">>> \[观察\] 正在等待Cloudflare验证通过 (寻找绿勾)...")
                    try:
                        success_indicator = iframe.ele('css:.success, [data-theme="success"]')
                        success_indicator.wait.displayed(timeout=20)
                        log("✅ Cloudflare 验证通过！(已找到绿勾)")
                    except Exception as e:
                        log(f"⚠️ 等待“绿勾”超时: {e}")
                        log("⚠️ 无法确认验证是否成功，但将继续尝试提交...")
                    
                    time.sleep(2)
                    final_renew_btn = modal.ele('css:button[type="submit"].btn-primary:text("Renew")')
                    
                    if final_renew_btn:
                        log(">>> 点击弹窗右下角的 Renew 按钮...")
                        final_renew_btn.click(by_js=True)
                        log(">>> 等待最终响应 (5s)...")
                        time.sleep(5)
                        
                        result = analyze_page_alert(page)
                        if result in ["SUCCESS", "SUCCESS_TOO_EARLY"]:
                            break
                        if result == "FAIL_CAPTCHA":
                            log("⚠️ 提交后，服务器返回验证失败，刷新重试...")
                            time.sleep(2)
                            continue
                    else:
                        log("❌ 找不到弹窗右下角的 Renew 按钮。")
                else:
                    log("❌ 弹窗未出")
            else:
                log("⚠️ 在等待后，依然未找到主页面按钮。检查页面最终状态...")
                result = analyze_page_alert(page)
                if result == "SUCCESS_TOO_EARLY":
                    break
            
            if attempt == max_retries:
                log("❌ 最大重试次数已达，任务终止。")
                exit(1)
                
    except Exception as e:
        log(f"❌ 异常: {e}")
        page.save("debug_page.html") # 保存页面快照以供分析
        log("ℹ️ 异常发生时的页面HTML已保存为 debug_page.html")
        exit(1)
    finally:
        page.quit()

if __name__ == "__main__":
    job()

