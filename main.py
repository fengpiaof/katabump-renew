#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KataBump 服务器续期脚本 - GitHub Actions 版本 (v1.3)

核心特性：
- 集成 Silk (Privacy Pass) 和 buyi06/cf 插件自动过 Cloudflare Turnstile
- 适配 GitHub Actions 环境
- 多次重试机制
- 支持 Telegram 通知

环境变量：
- KB_EMAIL: KataBump 账号邮箱
- KB_PASSWORD: KataBump 账号密码
- KB_RENEW_URL: 续期页面 URL (如 https://dashboard.katabump.com/servers/edit?id=xxxxx)
- TELEGRAM_TOKEN: (可选) Telegram Bot Token
- TELEGRAM_USERID: (可选) Telegram 用户 ID

插件说明：
- Silk (Privacy Pass Client): 提供 Privacy Pass 令牌，帮助通过 CF 验证
- buyi06/cf (Cfpass CDP Extension): 自动处理 Turnstile 验证
"""

import os
import io
import json
import time
import zipfile
import shutil
import socket
import datetime
import requests
from loguru import logger

# ==================== 常量配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.join(BASE_DIR, "extensions")
os.makedirs(EXT_DIR, exist_ok=True)

BASE_URL = "https://dashboard.katabump.com"
LOGIN_URL = f"{BASE_URL}/auth/login"


# ==================== 工具函数 ====================
def get_env_var(name: str, default: str = "") -> str:
    """获取环境变量"""
    return os.environ.get(name, default).strip()


def send_telegram(message: str, success: bool = True):
    """发送 Telegram 通知"""
    token = get_env_var("TELEGRAM_TOKEN")
    userid = get_env_var("TELEGRAM_USERID")
    
    if not token or not userid:
        logger.info("未配置 Telegram，跳过通知")
        return
    
    emoji = "✅" if success else "❌"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": userid,
            "parse_mode": "HTML",
            "text": f"{emoji} <b>KataBump</b> {message}"
        }
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            logger.success("Telegram 通知发送成功")
        else:
            logger.warning(f"Telegram 通知发送失败: {resp.status_code}")
    except Exception as e:
        logger.error(f"Telegram 通知异常: {e}")


# ==================== 插件管理 ====================
def _find_manifest_dir(root_dir: str):
    """查找包含 manifest.json 的目录"""
    if not root_dir or not os.path.exists(root_dir):
        return None
    for root, _, files in os.walk(root_dir):
        if "manifest.json" in files:
            return os.path.abspath(root)
    return None


def _read_manifest_info(ext_dir: str):
    """读取插件信息"""
    try:
        mf = os.path.join(ext_dir, "manifest.json")
        with open(mf, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("name", ""), data.get("version", "")
    except Exception:
        return "", ""


def _crx_to_zip_bytes(crx_bytes: bytes) -> bytes:
    """将 CRX 文件转换为 ZIP 格式"""
    sig = b"PK\x03\x04"
    idx = crx_bytes.find(sig)
    return crx_bytes[idx:] if idx != -1 else b""


def download_silk():
    """下载 Silk (Privacy Pass Client) 插件"""
    extract_root = os.path.join(EXT_DIR, "silk_ext")
    existed = _find_manifest_dir(extract_root)
    if existed:
        name, ver = _read_manifest_info(existed)
        logger.info(f"✅ [插件1] Silk 已存在: {existed} | {name} {ver}")
        return existed

    logger.info("⬇️ [插件1] 正在下载 Silk (Privacy Pass Client)...")
    url = ("https://clients2.google.com/service/update2/crx?"
           "response=redirect&prodversion=122.0&acceptformat=crx2,crx3&"
           "x=id%3Dajhmfdgkijocedmfjonnpjfojldioehi%26uc")
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if resp.status_code != 200:
            logger.error(f"下载 Silk 失败: HTTP {resp.status_code}")
            return None
        payload = _crx_to_zip_bytes(resp.content)
        if not payload:
            logger.error("Silk CRX 解析失败")
            return None
        os.makedirs(extract_root, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            zf.extractall(extract_root)
        result = _find_manifest_dir(extract_root)
        if result:
            name, ver = _read_manifest_info(result)
            logger.success(f"✅ [插件1] Silk 下载完成: {name} {ver}")
        return result
    except Exception as e:
        logger.error(f"下载 Silk 异常: {e}")
        return None


def download_buyi06_cf():
    """下载 buyi06/cf (Cfpass CDP Extension) 插件"""
    extract_root = os.path.join(EXT_DIR, "buyi06_cf_root")
    existed = _find_manifest_dir(extract_root)
    if existed:
        name, ver = _read_manifest_info(existed)
        logger.info(f"✅ [插件2] buyi06/cf 已存在: {existed} | {name} {ver}")
        return existed

    logger.info("⬇️ [插件2] 正在下载 buyi06/cf (Cfpass CDP Extension)...")
    url = "https://codeload.github.com/buyi06/cf/zip/refs/heads/master"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if resp.status_code != 200:
            logger.error(f"下载 buyi06/cf 失败: HTTP {resp.status_code}")
            return None
        os.makedirs(extract_root, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(extract_root)
        result = _find_manifest_dir(extract_root)
        if result:
            name, ver = _read_manifest_info(result)
            logger.success(f"✅ [插件2] buyi06/cf 下载完成: {name} {ver}")
        return result
    except Exception as e:
        logger.error(f"下载 buyi06/cf 异常: {e}")
        return None


# ==================== 浏览器配置 ====================
def _pick_browser_path():
    """选择浏览器路径"""
    # 环境变量指定
    env_path = os.environ.get("KB_CHROME_PATH", "").strip()
    if env_path and os.path.exists(env_path):
        return env_path
    
    # GitHub Actions 使用 browser-actions/setup-chrome 安装的 Chrome
    # 通常在 PATH 中可以直接找到
    candidates = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    
    for path in candidates:
        if path and os.path.exists(path):
            return path
    
    return None


def _free_port():
    """获取一个空闲端口"""
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get_browser():
    """初始化浏览器"""
    from DrissionPage import Chromium, ChromiumOptions
    
    browser_path = _pick_browser_path()
    if not browser_path:
        logger.error("❌ 未找到浏览器，请确保已安装 Chrome/Chromium")
        return None
    
    logger.info(f"🔧 浏览器路径: {browser_path}")
    
    # 下载插件
    silk = download_silk()
    cf_ext = download_buyi06_cf()
    
    # 配置浏览器选项
    co = ChromiumOptions()
    co.set_browser_path(browser_path)
    
    # 无头模式 - 使用新版无头模式
    co.set_argument('--headless=new')
    
    # 基本配置
    co.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    co.set_argument('--window-size=1920,1080')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-infobars')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--disable-blink-features=AutomationControlled')
    
    # 加载插件
    if silk:
        logger.info(f"📦 加载插件: Silk -> {silk}")
        co.add_extension(silk)
    else:
        logger.warning("⚠️ Silk 插件未加载")
    
    if cf_ext:
        logger.info(f"📦 加载插件: buyi06/cf -> {cf_ext}")
        co.add_extension(cf_ext)
    else:
        logger.warning("⚠️ buyi06/cf 插件未加载")
    
    # 设置端口
    co.set_local_port(_free_port())
    
    try:
        browser = Chromium(addr_or_opts=co)
        logger.success("✅ 浏览器启动成功")
        return browser
    except Exception as e:
        logger.error(f"❌ 浏览器启动失败: {e}")
        return None


# ==================== 主逻辑 ====================
class KataBumpRenewer:
    def __init__(self):
        self.kb_email = get_env_var("KB_EMAIL")
        self.kb_password = get_env_var("KB_PASSWORD")
        self.kb_renew_url = get_env_var("KB_RENEW_URL")
        self.browser = None
        self.page = None
    
    def _wait_turnstile(self, timeout: int = 90) -> bool:
        """等待 Turnstile 验证完成"""
        logger.info(f"⏳ 等待 Turnstile 验证 (最多 {timeout} 秒)...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 检查 Turnstile 响应
                resp_ele = self.page.ele('css:input[name="cf-turnstile-response"]', timeout=1)
                if resp_ele:
                    val = resp_ele.attr("value")
                    if val and len(val) > 20:
                        logger.success("✅ Turnstile 验证通过!")
                        return True
                
                # 检查是否有错误
                if self.page.ele('text:Error verifying Turnstile', timeout=0.5):
                    logger.error("❌ Turnstile 验证错误")
                    return False
                
            except Exception:
                pass
            
            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0 and elapsed > 0:
                logger.info(f"已等待 {elapsed} 秒...")
            
            time.sleep(2)
            print(".", end="", flush=True)
        
        print("")
        logger.error("❌ Turnstile 验证超时")
        return False
    
    def _do_login(self) -> bool:
        """执行登录"""
        logger.info("🔐 检测到需要登录...")
        
        try:
            ele_email = self.page.ele('css:input[name="email"], input#email, input[type="email"]', timeout=5)
            ele_pass = self.page.ele('css:input[name="password"], input#password, input[type="password"]', timeout=5)
            btn_submit = self.page.ele('css:button[type="submit"], button#submit', timeout=5)
            
            if not ele_email or not ele_pass or not btn_submit:
                logger.error("❌ 找不到登录表单元素")
                return False
            
            # 输入凭据
            ele_email.clear()
            ele_email.input(self.kb_email)
            time.sleep(0.5)
            
            ele_pass.clear()
            ele_pass.input(self.kb_password)
            time.sleep(0.5)
            
            logger.info(f"📝 已输入账号: {self.kb_email[:3]}***")
            
            # 等待登录页面的 Turnstile (如果有)
            logger.info("检查登录页 Turnstile...")
            turnstile_iframe = self.page.ele('css:iframe[src*="challenges.cloudflare.com"]', timeout=3)
            if turnstile_iframe:
                logger.info("登录页有 Turnstile，等待验证...")
                if not self._wait_turnstile(timeout=60):
                    logger.warning("登录页 Turnstile 可能未通过，继续尝试...")
            
            # 点击登录
            btn_submit.click()
            logger.info("✅ 已点击登录按钮，等待跳转...")
            time.sleep(5)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 登录异常: {e}")
            return False
    
    def _do_renew(self) -> bool:
        """执行续期"""
        logger.info("🔎 查找 Renew 按钮...")
        
        renew_btn = self.page.ele('css:button[data-bs-toggle="modal"][data-bs-target="#renew-modal"]', timeout=10)
        if not renew_btn:
            logger.info("尝试文本查找...")
            renew_btn = self.page.ele('text:Renew', timeout=5)
        
        if not renew_btn:
            logger.error("❌ 未找到 Renew 按钮")
            return False
        
        # 滚动并点击
        try:
            renew_btn.scroll.to_see()
            time.sleep(1)
        except:
            pass
        
        renew_btn.click()
        logger.info("✅ 已点击 Renew 按钮，等待弹窗...")
        time.sleep(3)
        
        # 等待 Turnstile 验证
        if not self._wait_turnstile(timeout=90):
            return False
        
        # 点击确认
        logger.info("🔎 查找确认按钮...")
        confirm_btn = self.page.ele('css:#renew-modal button[type="submit"]', timeout=5)
        if not confirm_btn:
            confirm_btn = self.page.ele('css:.modal button[type="submit"]', timeout=5)
        
        if not confirm_btn:
            logger.error("❌ 找不到确认按钮")
            return False
        
        confirm_btn.click()
        logger.info("✅ 已点击确认按钮")
        time.sleep(5)
        
        # 检查结果
        html_lower = self.page.html.lower()
        if "success" in html_lower or "renewed" in html_lower:
            logger.success("🎉 续期成功!")
            return True
        else:
            logger.warning("❓ 未检测到明确的成功标识，但流程已完成")
            return True
    
    def run(self) -> bool:
        """主运行流程"""
        logger.info("=" * 50)
        logger.info("KataBump 续期脚本启动 (v1.3 - 插件版)")
        logger.info("=" * 50)
        
        # 检查环境变量
        logger.info("检查环境变量...")
        logger.info(f"KB_EMAIL: {'已设置' if self.kb_email else '未设置'}")
        logger.info(f"KB_PASSWORD: {'已设置' if self.kb_password else '未设置'}")
        logger.info(f"KB_RENEW_URL: {'已设置' if self.kb_renew_url else '未设置'}")
        
        missing = []
        if not self.kb_email:
            missing.append("KB_EMAIL")
        if not self.kb_password:
            missing.append("KB_PASSWORD")
        if not self.kb_renew_url:
            missing.append("KB_RENEW_URL")
        
        if missing:
            logger.error(f"❌ 缺少环境变量: {', '.join(missing)}")
            send_telegram(f"续期失败: 缺少环境变量 {', '.join(missing)}", success=False)
            return False
        
        logger.info(f"📧 账号: {self.kb_email}")
        logger.info(f"🔗 续期 URL: {self.kb_renew_url}")
        
        # 初始化浏览器
        self.browser = get_browser()
        if not self.browser:
            send_telegram("续期失败: 浏览器启动失败", success=False)
            return False
        
        self.page = self.browser.latest_tab
        
        success = False
        max_retries = 5
        
        try:
            for attempt in range(1, max_retries + 1):
                logger.info(f"{'=' * 30}")
                logger.info(f"🚀 第 {attempt}/{max_retries} 次尝试")
                logger.info(f"{'=' * 30}")
                
                try:
                    # 直接访问续期 URL
                    logger.info(f"➡️ 访问: {self.kb_renew_url}")
                    self.page.get(self.kb_renew_url)
                    time.sleep(5)
                    
                    # 检查是否被重定向到登录页
                    if "login" in self.page.url or self.page.ele('css:input[name="email"]', timeout=2):
                        logger.info("🚧 被重定向到登录页")
                        if not self._do_login():
                            logger.error("登录失败")
                            continue
                    
                    # 登录后再次访问续期页面
                    if "edit" not in self.page.url:
                        logger.info(f"🔄 跳转到续期页面: {self.kb_renew_url}")
                        self.page.get(self.kb_renew_url)
                        time.sleep(5)
                    
                    # 检查是否仍在登录页
                    if "login" in self.page.url:
                        logger.warning("⚠️ 仍在登录页，重试...")
                        continue
                    
                    # 执行续期
                    if self._do_renew():
                        success = True
                        break
                    else:
                        logger.warning("续期未成功，刷新重试...")
                        self.page.refresh()
                        time.sleep(3)
                        
                except Exception as e:
                    logger.error(f"❌ 尝试 {attempt} 异常: {e}")
                    time.sleep(3)
            
            if success:
                send_telegram(f"服务器续期成功! 账号: {self.kb_email}", success=True)
            else:
                send_telegram(f"续期失败! 账号: {self.kb_email}，已重试 {max_retries} 次", success=False)
                
        except Exception as e:
            logger.error(f"❌ 运行异常: {e}")
            send_telegram(f"续期异常: {str(e)}", success=False)
        finally:
            if self.browser:
                try:
                    self.browser.quit()
                except:
                    pass
        
        logger.info("=" * 50)
        logger.info(f"🏁 脚本执行完成，结果: {'成功' if success else '失败'}")
        logger.info("=" * 50)
        
        return success


if __name__ == "__main__":
    import sys
    renewer = KataBumpRenewer()
    result = renewer.run()
    sys.exit(0 if result else 1)
