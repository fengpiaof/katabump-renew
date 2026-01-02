#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 服务器自动续期脚本
环境：GitHub Actions (Ubuntu/Linux)
依赖：DrissionPage >= 4.1.x
"""

import os
import time
import json
import requests
import zipfile
import io
import shutil
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions


# ==================== 配置区域 ====================
class Config:
    """集中配置管理"""
    
    # 浏览器配置
    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    WINDOW_SIZE = "1920,1080"
    
    # 超时配置（秒）
    PAGE_LOAD_TIMEOUT = 20
    ELEMENT_WAIT_TIMEOUT = 15
    CF_SOLVE_TIMEOUT = 30
    CLICK_RETRY_DELAY = 1.0
    
    # 重试次数
    DOWNLOAD_RETRIES = 3
    CLICK_RETRIES = 3
    
    # 目标配置
    SERVER_ID = "197288"
    EXTENSION_ID = "ajhmfdgkijocedmfjonnpjfojldioehi"
    
    # 调试输出目录
    DEBUG_DIR = "debug_output"


# ==================== 工具函数 ====================
def log(message, level="INFO"):
    """统一日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def capture_debug_info(page, tag=""):
    """捕获调试信息（截图 + HTML + 元数据）"""
    os.makedirs(Config.DEBUG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{timestamp}_{tag}" if tag else timestamp
    
    # 截图
    try:
        screenshot_path = os.path.join(Config.DEBUG_DIR, f"{base_name}.png")
        page.get_screenshot(path=screenshot_path, full_page=True)
        log(f"截图已保存: {screenshot_path}")
    except Exception as e:
        log(f"截图失败: {e}", "WARNING")
    
    # 保存 HTML
    try:
        html_path = os.path.join(Config.DEBUG_DIR, f"{base_name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.html)
        log(f"HTML已保存: {html_path}")
    except Exception as e:
        log(f"HTML保存失败: {e}", "WARNING")
    
    # 保存元数据
    try:
        meta_path = os.path.join(Config.DEBUG_DIR, f"{base_name}.json")
        meta = {
            "timestamp": timestamp,
            "tag": tag,
            "url": getattr(page, "url", ""),
            "title": getattr(page, "title", ""),
            "user_agent": Config.USER_AGENT
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        log(f"元数据已保存: {meta_path}")
    except Exception as e:
        log(f"元数据保存失败: {e}", "WARNING")


def wait_until(condition, timeout=30, interval=0.5, error_msg="条件等待超时"):
    """通用条件等待函数"""
    start_time = time.time()
    last_exception = None
    
    while time.time() - start_time < timeout:
        try:
            if condition():
                return True
        except Exception as e:
            last_exception = e
        time.sleep(interval)
    
    if last_exception:
        raise TimeoutError(f"{error_msg} (最后异常: {last_exception})")
    raise TimeoutError(error_msg)


def click_safe(element, page=None, tag=""):
    """安全点击元素，支持重试和兜底"""
    if not element:
        log("元素不存在，无法点击", "ERROR")
        return False
    
    for attempt in range(Config.CLICK_RETRIES):
        try:
            # 滚动到可视区域
            try:
                element.scroll.to_view()
            except Exception:
                pass
            
            # 尝试普通点击
            element.click()
            log(f"点击成功 (尝试 {attempt + 1}/{Config.CLICK_RETRIES})")
            return True
            
        except Exception as e:
            log(f"点击失败 (尝试 {attempt + 1}/{Config.CLICK_RETRIES}): {e}", "WARNING")
            
            # 尝试 JavaScript 点击
            try:
                element.click(by_js=True)
                log(f"JavaScript点击成功 (尝试 {attempt + 1}/{Config.CLICK_RETRIES})")
                return True
            except Exception as js_error:
                log(f"JavaScript点击也失败: {js_error}", "WARNING")
            
            if attempt < Config.CLICK_RETRIES - 1:
                time.sleep(Config.CLICK_RETRY_DELAY)
    
    # 全部失败后截图
    if page:
        capture_debug_info(page, f"click_failed_{tag}")
    
    return False


def find_element_robust(page, selectors, timeout=15):
    """多重保障查找元素"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        for method, value in selectors:
            try:
                if method == 'text':
                    ele = page.ele(f'text:{value}')
                elif method == 'css':
                    ele = page.ele(f'css:{value}')
                elif method == 'xpath':
                    ele = page.ele(f'xpath:{value}')
                elif method == 'tag':
                    ele = page.ele(f'tag:{value}')
                elif method == 'raw':
                    ele = page.ele(value)
                else:
                    continue
                
                if ele and ele.is_displayed():
                    log(f"找到元素: {method}={value}")
                    return ele
            except Exception as e:
                log(f"查找元素失败 {method}={value}: {e}", "DEBUG")
        
        time.sleep(0.5)
    
    return None


def wait_for_cloudflare(page, timeout=30, tag=""):
    """等待 Silk 插件自动过 Cloudflare 盾"""
    log(f"等待 Silk 插件自动过盾 (超时 {timeout}s)...")
    
    def cf_passed():
        try:
            title = page.title.lower()
            html = page.html.lower()
            # 成功标志：标题不是 Just a moment，且没有 CF 验证相关内容
            return ("just a moment" not in title and 
                   "cloudflare" not in title and
                   "checking your browser" not in html)
        except Exception:
            return False
    
    try:
        if wait_until(cf_passed, timeout=timeout, error_msg="Cloudflare 过盾超时"):
            log("✅ Cloudflare 验证已通过")
            return True
    except TimeoutError:
        log("⚠️ 插件自动过盾超时，尝试手动辅助", "WARNING")
        
        # 尝试手动辅助
        try:
            iframe = page.get_frame('@src^https://challenges.cloudflare.com')
            if iframe:
                body = iframe.ele('tag:body')
                if body:
                    click_safe(body, page, f"{tag}_cf_body")
                    time.sleep(2)
        except Exception as e:
            log(f"手动辅助过盾失败: {e}", "WARNING")
        
        # 再次检查
        if wait_until(cf_passed, timeout=10, error_msg="手动辅助后仍超时"):
            log("✅ 手动辅助后 Cloudflare 验证通过")
            return True
    
    capture_debug_info(page, f"cf_failed_{tag}")
    return False


# ==================== 插件下载与解压 ====================
def download_crx_file(url, dst_path, headers=None):
    """流式下载 CRX 文件"""
    log(f"开始下载: {url}")
    
    for attempt in range(Config.DOWNLOAD_RETRIES):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(10, 60)) as response:
                response.raise_for_status()
                
                with open(dst_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                log(f"下载成功: {dst_path}")
                return True
                
        except Exception as e:
            log(f"下载失败 (尝试 {attempt + 1}/{Config.DOWNLOAD_RETRIES}): {e}", "WARNING")
            if os.path.exists(dst_path):
                os.remove(dst_path)
            time.sleep(2)
    
    return False


def extract_crx_to_folder(crx_path, extract_dir):
    """将 CRX 文件解压到文件夹"""
    log(f"开始解压 CRX 文件: {crx_path}")
    
    try:
        with open(crx_path, 'rb') as f:
            content = f.read()
        
        # 查找 ZIP 文件头
        zip_start = content.find(b'PK\x03\x04')
        if zip_start == -1:
            raise ValueError("CRX 文件格式错误：未找到 ZIP 头")
        
        log(f"找到 ZIP 头，位置: {zip_start}")
        
        # 创建解压目录
        os.makedirs(extract_dir, exist_ok=True)
        
        # 解压 ZIP 数据
        with zipfile.ZipFile(io.BytesIO(content[zip_start:])) as zf:
            zf.extractall(extract_dir)
        
        # 验证 manifest.json 是否存在
        manifest_path = os.path.join(extract_dir, 'manifest.json')
        if not os.path.exists(manifest_path):
            raise FileNotFoundError("解压后未找到 manifest.json")
        
        log(f"✅ CRX 解压成功: {extract_dir}")
        return True
        
    except Exception as e:
        log(f"CRX 解压失败: {e}", "ERROR")
        # 清理失败的解压目录
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        return False


def download_and_extract_silk_extension():
    """下载并解压 Silk 插件"""
    extension_id = Config.EXTENSION_ID
    crx_path = "silk.crx"
    extract_dir = "silk_ext"
    
    # 检查是否已存在有效的插件目录
    if os.path.exists(extract_dir) and os.listdir(extract_dir):
        manifest_path = os.path.join(extract_dir, 'manifest.json')
        if os.path.exists(manifest_path):
            log(f"✅ 插件已存在: {extract_dir}")
            return os.path.abspath(extract_dir)
        else:
            log("插件目录存在但缺少 manifest.json，重新下载", "WARNING")
            shutil.rmtree(extract_dir, ignore_errors=True)
    
    # 清理旧文件
    if os.path.exists(crx_path):
        os.remove(crx_path)
    
    # 构建下载 URL
    download_url = (
        f"https://clients2.google.com/service/update2/crx"
        f"?response=redirect&prodversion=122.0"
        f"&acceptformat=crx2,crx3"
        f"&x=id%3D{extension_id}%26uc"
    )
    
    headers = {
        "User-Agent": Config.USER_AGENT
    }
    
    # 下载 CRX
    if not download_crx_file(download_url, crx_path, headers):
        log("❌ CRX 下载失败", "ERROR")
        return None
    
    # 解压 CRX
    if not extract_crx_to_folder(crx_path, extract_dir):
        log("❌ CRX 解压失败", "ERROR")
        return None
    
    # 清理 CRX 文件
    if os.path.exists(crx_path):
        os.remove(crx_path)
    
    log(f"✅ 插件准备完成: {os.path.abspath(extract_dir)}")
    return os.path.abspath(extract_dir)


# ==================== 核心业务逻辑 ====================
def inject_discord_token(page):
    """注入 Discord Token 实现免密登录"""
    log("开始 Discord Token 注入流程")
    
    # 获取 Token
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise EnvironmentError("❌ 致命错误：环境变量中未找到 DISCORD_TOKEN")
    
    log(f"Token 已获取 (长度: {len(token)})")
    
    # 访问 Discord 登录页
    log("访问 Discord 登录页...")
    page.get('https://discord.com/login', retry=3, timeout=Config.PAGE_LOAD_TIMEOUT)
    
    # 等待 Cloudflare 过盾
    wait_for_cloudflare(page, timeout=Config.CF_SOLVE_TIMEOUT, tag="discord_login")
    
    # 清空 Cookie（DrissionPage 4.x 写法）
    try:
        page.set.cookies.clear()
        log("Cookie 已清空")
    except Exception as e:
        log(f"Cookie 清空失败（可忽略）: {e}", "WARNING")
    
    # 注入 Token
    token_value = f'"{token}"'
    js_code = f"window.localStorage.setItem('token', '{token_value}');"
    
    log("执行 Token 注入 JavaScript...")
    page.run_js(js_code)
    time.sleep(1)
    
    # 刷新页面验证 Token
    log("刷新页面验证 Token...")
    page.refresh()
    page.wait.load_start()
    time.sleep(3)
    
    # 检查是否仍要求登录
    email_input = page.ele('css:input[name="email"]', timeout=5)
    if email_input:
        capture_debug_info(page, "token_invalid")
        raise RuntimeError("❌ Token 无效，Discord 仍要求登录")
    
    log("✅ Discord Token 注入成功")


def login_to_katabump(page):
    """登录到 Katabump 面板"""
    log("开始 Katabump 登录流程")
    
    # 访问 Katabump 面板
    log("访问 Katabump 面板...")
    page.get('https://dashboard.katabump.com/', retry=3, timeout=Config.PAGE_LOAD_TIMEOUT)
    
    # 等待 Cloudflare 过盾
    wait_for_cloudflare(page, timeout=Config.CF_SOLVE_TIMEOUT, tag="katabump_home")
    
    # 检查是否已登录
    if "login" not in page.url.lower():
        log("✅ 已直接进入 Dashboard（无需登录）")
        return True
    
    log("需要登录，寻找登录按钮...")
    
    # 查找登录按钮（多种选择器容错）
    login_selectors = [
        ('text', 'Login with Discord'),
        ('text', 'Discord 登录'),
        ('css', 'a[href*="discord"]'),
        ('css', '.btn-discord'),
        ('css', 'button:contains("Discord")'),
        ('xpath', '//a[contains(text(), "Discord")]'),
        ('xpath', '//button[contains(text(), "Login")]')
    ]
    
    login_btn = find_element_robust(page, login_selectors, timeout=Config.ELEMENT_WAIT_TIMEOUT)
    
    if not login_btn:
        capture_debug_info(page, "no_login_button")
        raise RuntimeError("❌ 未找到登录按钮")
    
    log("点击登录按钮...")
    if not click_safe(login_btn, page, "login_button"):
        raise RuntimeError("❌ 登录按钮点击失败")
    
    # 等待跳转到 Discord 授权页
    log("等待跳转到 Discord 授权页...")
    
    def discord_auth_page_loaded():
        return "discord.com" in page.url.lower() and "oauth2" in page.url.lower()
    
    if not wait_until(discord_auth_page_loaded, timeout=15, error_msg="未跳转到 Discord 授权页"):
        capture_debug_info(page, "auth_redirect_failed")
        raise RuntimeError("❌ 未跳转到 Discord 授权页")
    
    # 处理 Cloudflare
    wait_for_cloudflare(page, timeout=Config.CF_SOLVE_TIMEOUT, tag="discord_auth")
    
    # 查找并点击授权按钮
    log("查找授权按钮...")
    auth_selectors = [
        ('text', 'Authorize'),
        ('text', '授权'),
        ('css', 'button[type="submit"]'),
        ('xpath', '//button[contains(text(), "Authorize")]'),
        ('xpath', '//div[contains(text(), "Authorize")]')
    ]
    
    auth_btn = find_element_robust(page, auth_selectors, timeout=10)
    
    if auth_btn:
        log("点击授权按钮...")
        if not click_safe(auth_btn, page, "authorize_button"):
            log("⚠️ 授权按钮点击失败，可能已自动授权", "WARNING")
    else:
        log("⚠️ 未找到授权按钮，可能已跳过授权步骤", "WARNING")
    
    # 等待返回 Katabump
    log("等待返回 Katabump 面板...")
    
    def back_to_katabump():
        return "katabump.com" in page.url.lower() and "login" not in page.url.lower()
    
    if not wait_until(back_to_katabump, timeout=20, error_msg="未返回 Katabump 面板"):
        capture_debug_info(page, "login_return_failed")
        raise RuntimeError("❌ 登录后未返回 Katabump 面板")
    
    log("✅ Katabump 登录成功")


def renew_server(page):
    """续期服务器"""
    log("开始服务器续期流程")
    
    # 构建目标 URL
    target_url = f"https://dashboard.katabump.com/servers/edit?id={Config.SERVER_ID}"
    log(f"进入服务器页面: {target_url}")
    
    # 访问目标服务器页面
    page.get(target_url, retry=3, timeout=Config.PAGE_LOAD_TIMEOUT)
    
    # 等待 Cloudflare 过盾
    wait_for_cloudflare(page, timeout=Config.CF_SOLVE_TIMEOUT, tag="server_page")
    
    # 等待页面加载完成
    time.sleep(2)
    
    # 查找续期按钮（支持中英文）
    log("查找续期按钮...")
    renew_selectors = [
        ('text', 'Renew'),
        ('text', '续期'),
        ('css', 'button:contains("Renew")'),
        ('css', 'button:contains("续期")'),
        ('xpath', '//button[contains(text(), "Renew")]'),
        ('xpath', '//button[contains(text(), "续期")]'),
        ('xpath', '//a[contains(text(), "Renew")]')
    ]
    
    renew_btn = find_element_robust(page, renew_selectors, timeout=Config.ELEMENT_WAIT_TIMEOUT)
    
    if not renew_btn:
        capture_debug_info(page, "no_renew_button")
        log(f"DEBUG HTML: {page.html[:500]}", "DEBUG")
        raise RuntimeError("❌ 未找到续期按钮")
    
    log("点击续期按钮...")
    if not click_safe(renew_btn, page, "renew_button"):
        raise RuntimeError("❌ 续期按钮点击失败")
    
    # 等待弹窗出现
    log("等待续期弹窗...")
    time.sleep(2)
    
    # 等待 Cloudflare（弹窗也可能触发）
    wait_for_cloudflare(page, timeout=Config.CF_SOLVE_TIMEOUT, tag="renew_modal")
    
    # 查找确认弹窗
    log("查找确认弹窗...")
    try:
        modal = page.ele('css:.modal-content', timeout=5)
    except Exception:
        modal = None
    
    if modal:
        log("找到续期弹窗，查找确认按钮...")
        
        confirm_selectors = [
            ('text', 'Renew'),
            ('text', '确认'),
            ('text', 'Confirm'),
            ('css', 'button.btn-primary'),
            ('css', 'button.btn-success'),
            ('xpath', './/button[contains(text(), "Renew")]'),
            ('xpath', './/button[contains(text(), "确认")]')
        ]
        
        confirm_btn = find_element_robust(modal, confirm_selectors, timeout=5)
        
        if confirm_btn:
            log("点击确认按钮...")
            if not click_safe(confirm_btn, page, "confirm_renew"):
                raise RuntimeError("❌ 确认按钮点击失败")
        else:
            capture_debug_info(page, "no_confirm_button")
            raise RuntimeError("❌ 弹窗中未找到确认按钮")
    else:
        log("⚠️ 未找到弹窗，可能续期已完成或无需确认", "WARNING")
    
    # 等待续期完成
    log("等待续期完成...")
    time.sleep(3)
    
    log("🎉🎉🎉 服务器续期成功！")


def main():
    """主函数"""
    log("=" * 60)
    log("Katabump 服务器自动续期脚本启动")
    log("=" * 60)
    
    page = None
    
    try:
        # ==================== 阶段 1: 准备插件 ====================
        log("\n【阶段 1/5】准备 Silk 插件")
        log("-" * 40)
        
        extension_path = download_and_extract_silk_extension()
        if not extension_path:
            raise RuntimeError("❌ 插件准备失败")
        
        # ==================== 阶段 2: 配置浏览器 ====================
        log("\n【阶段 2/5】配置并启动浏览器")
        log("-" * 40)
        
        co = ChromiumOptions()
        
        # 基础配置
        co.set_argument('--headless=new' if Config.HEADLESS else '--headless=false')
        co.set_argument('--disable-dev-shm-usage')  # 防止内存崩溃
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        co.set_argument(f'--window-size={Config.WINDOW_SIZE}')
        co.set_argument(f'--user-agent={Config.USER_AGENT}')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        
        # 自动分配端口
        co.auto_port()
        
        # 加载插件
        if extension_path:
            co.add_extension(extension_path)
            log(f"插件已加载: {extension_path}")
        else:
            log("⚠️ 插件加载失败，将以无插件模式运行", "WARNING")
        
        # 启动浏览器
        log("启动浏览器...")
        page = ChromiumPage(co)
        
        # 设置超时（DrissionPage 4.x 写法）
        try:
            page.set.timeouts(Config.PAGE_LOAD_TIMEOUT)
            log(f"页面超时设置为: {Config.PAGE_LOAD_TIMEOUT}s")
        except Exception as e:
            log(f"超时设置失败（可忽略）: {e}", "WARNING")
        
        # ==================== 阶段 3: Discord Token 注入 ====================
        log("\n【阶段 3/5】Discord Token 注入")
        log("-" * 40)
        
        inject_discord_token(page)
        
        # ==================== 阶段 4: 登录 Katabump ====================
        log("\n【阶段 4/5】登录 Katabump 面板")
        log("-" * 40)
        
        login_to_katabump(page)
        
        # ==================== 阶段 5: 服务器续期 ====================
        log("\n【阶段 5/5】服务器续期")
        log("-" * 40)
        
        renew_server(page)
        
        # ==================== 成功完成 ====================
        log("\n" + "=" * 60)
        log("✅ 所有步骤执行成功！")
        log("=" * 60)
        
        return 0
        
    except Exception as e:
        log(f"\n❌ 脚本执行失败: {e}", "ERROR")
        
        # 捕获错误现场
        if page:
            capture_debug_info(page, "crash")
        
        # 打印详细错误信息
        import traceback
        log("\n详细错误堆栈:", "ERROR")
        log(traceback.format_exc(), "ERROR")
        
        return 1
        
    finally:
        # 清理资源
        if page:
            try:
                page.quit()
                log("浏览器已关闭")
            except Exception as e:
                log(f"浏览器关闭失败（可忽略）: {e}", "WARNING")


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)