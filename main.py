import os
import time
import requests
import zipfile
import io
import datetime
from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 基础工具 ====================
def log(message):
    """实时日志"""
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{current_time}] {message}", flush=True)

def download_silk():
    """下载插件"""
    extract_dir = "silk_ext"
    if os.path.exists(extract_dir): return os.path.abspath(extract_dir)
    log(">>> [系统] 正在下载过盾插件...")
    try:
        url = "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=122.0&acceptformat=crx2,crx3&x=id%3Dajhmfdgkijocedmfjonnpjfojldioehi%26uc"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, stream=True)
        if resp.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                zf.extractall(extract_dir)
            return os.path.abspath(extract_dir)
    except: pass
    return None

# ==================== 核心逻辑 ====================

def pass_full_page_shield(page):
    """处理全屏 Cloudflare (门神)"""
    # 快速检查，只查 3 秒，避免浪费时间
    for _ in range(3):
        if "just a moment" in page.title.lower():
            log("--- [门神] 正在通过全屏盾...")
            iframe = page.ele('css:iframe[src*="cloudflare"]', timeout=2)
            if iframe: 
                iframe.ele('tag:body').click(by_js=True)
                time.sleep(3)
        else:
            return True
    return False

def pass_modal_captcha(modal):
    """
    【精准定位】处理弹窗内的 CF 盾
    根据您提供的报错信息，我们必须死等这个 iframe 加载出来
    """
    log(">>> [弹窗] 正在扫描验证码 iframe...")
    
    # 尝试找 cloudflare 的 iframe
    # 您的代码提示 challenge.cloudflare.com，所以我们锁定 src
    iframe = modal.wait.ele_displayed('css:iframe[src*="cloudflare"]', timeout=10)
    
    if iframe:
        log(">>> [弹窗] 👁️ 发现验证码，点击...")
        try:
            iframe.ele('tag:body').click(by_js=True)
            log(">>> [弹窗] 👆 已点击，强制等待 5 秒 (变绿)...")
            time.sleep(5) 
            return True
        except: 
            pass
    else:
        log(">>> [弹窗] 未发现验证码 (可能网络卡顿或已通过)")
    return False

def check_result_status(page):
    """检查结果：红条(未到期) 或 绿条(成功)"""
    html = page.html.lower()
    if "can't renew" in html or "too early" in html:
        return "TOO_EARLY"
    if "success" in html or "extended" in html:
        return "SUCCESS"
    return "UNKNOWN"

# ==================== 主程序 ====================
def job():
    ext_path = download_silk()
    
    # 配置浏览器 (Linux 环境防崩必配)
    co = ChromiumOptions()
    co.set_argument('--headless=new')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-dev-shm-usage') # 关键！
    co.set_argument('--window-size=1920,1080')
    co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
    
    if ext_path: co.add_extension(ext_path)
    co.auto_port()

    page = ChromiumPage(co)
    page.set.timeouts(15)

    try:
        email = os.environ.get("KB_EMAIL")
        password = os.environ.get("KB_PASSWORD")
        target_url = os.environ.get("KB_RENEW_URL")
        
        if not all([email, password, target_url]): 
            log("❌ Secrets 配置缺失")
            exit(1)

        # ---------------- Step 1: 登录 ----------------
        log(">>> [1/3] 前往登录页...")
        page.get('https://dashboard.katabump.com/auth/login')
        pass_full_page_shield(page)

        # 【精准定位】根据您的 HTML: name="email"
        if page.ele('css:input[name="email"]'):
            log(">>> 输入账号密码...")
            page.ele('css:input[name="email"]').input(email)
            # 【精准定位】name="password"
            page.ele('css:input[name="password"]').input(password)
            # 【精准定位】id="submit"
            page.ele('css:button#submit').click()
            
            # 等待跳转到 Dashboard
            page.wait.url_change('login', exclude=True, timeout=20)
        
        # ---------------- Step 2: 直达服务器页面 ----------------
        log(">>> [2/3] 跳转至服务器续期页...")
        page.get(target_url)
        pass_full_page_shield(page)
        
        # ---------------- Step 3: 寻找 Renew 按钮 ----------------
        log(">>> 正在定位 Renew 按钮...")
        
        # 【精准定位】根据您提供的: data-bs-target="#renew-modal"
        # 这是绝对唯一的特征，比 class 准多了
        renew_btn = None
        
        # 轮询 10 秒
        for _ in range(10):
            renew_btn = page.ele('css:button[data-bs-target="#renew-modal"]')
            if renew_btn and renew_btn.states.is_displayed: break
            time.sleep(1)

        if renew_btn:
            log(">>> [动作] 点击主 Renew 按钮...")
            renew_btn.click(by_js=True)
            
            log(">>> 等待弹窗加载...")
            # 【精准定位】等待 modal-content 出来
            modal = page.wait.ele_displayed('css:.modal-content', timeout=10)
            
            if modal:
                # 1. 先处理弹窗里的盾
                pass_modal_captcha(modal)
                
                # 2. 【精准定位】根据您提供的: type="submit" class="btn btn-primary"
                confirm_btn = modal.ele('css:button[type="submit"].btn-primary')
                
                if confirm_btn:
                    log(">>> [动作] 点击最终确认 (Confirm)...")
                    confirm_btn.click(by_js=True)
                    
                    time.sleep(5)
                    # 检查结果
                    status = check_result_status(page)
                    if status == "SUCCESS":
                        log("🎉🎉🎉 续期成功！(Success)")
                    else:
                        log("⚠️ 点击了但未检测到成功字样，请检查截图确认。")
                else:
                    log("❌ 弹窗里找不到 Submit 按钮")
                    exit(1)
            else:
                log("❌ 弹窗未出现")
                exit(1)
        else:
            # 如果没找到按钮，检查是不是还没到期
            log("⚠️ 未找到 Renew 按钮，检查状态...")
            status = check_result_status(page)
            if status == "TOO_EARLY":
                log("✅ [结果] 还没到时间 (Too Early)，无需操作。")
            else:
                log("❌ 既没按钮，也没提示红条，页面可能加载失败。")
                exit(1)

    except Exception as e:
        log(f"❌ 运行异常: {e}")
        exit(1)
    finally:
        page.quit()

if __name__ == "__main__":
    job()
