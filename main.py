import os
import time
from DrissionPage import ChromiumPage, ChromiumOptions

def parse_cookie_string(cookie_str):
    """将 Cookie 字符串解析为字典列表"""
    cookies = []
    if not cookie_str:
        return cookies
    try:
        for item in cookie_str.split(';'):
            if '=' in item:
                name, value = item.strip().split('=', 1)
                cookies.append({
                    'name': name,
                    'value': value,
                    'domain': '.discord.com', # 关键：设置给 Discord 域名
                    'path': '/'
                })
    except Exception as e:
        print(f"Cookie 解析警告: {e}")
    return cookies

def job():
    # --- 1. 浏览器初始化 ---
    co = ChromiumOptions()
    co.headless(True) # GitHub Actions 必须开启无头模式
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--lang=zh-CN')
    # 模拟真实浏览器 User-Agent
    co.set_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    page = ChromiumPage(co)
    
    try:
        # ==================== 阶段一：注入凭证与登录 ====================
        print(">>> [1/7] 正在尝试注入 Discord Cookie...")
        raw_cookie = os.environ.get("DISCORD_COOKIE_STRING")
        
        if raw_cookie:
            # 必须先访问域名才能设置 Cookie
            page.get('https://discord.com', retry=1)
            page.set.cookies(parse_cookie_string(raw_cookie))
            time.sleep(1)
            print(">>> Cookie 注入完成。")
        else:
            print(">>> 警告: 未检测到 Cookie Secret，将直接尝试账号密码登录。")

        print(">>> [2/7] 前往 Katabump 点击登录...")
        page.get('https://dashboard.katabump.com/auth/login')
        time.sleep(3)
        
        # 处理 Cloudflare 5秒盾
        if "Just a moment" in page.title or "Cloudflare" in page.title:
            print("--- 正在通过 Cloudflare 检查... ---")
            time.sleep(8)

        # 寻找并点击 "Login with Discord"
        discord_btn = page.ele('text:Login with Discord')
        if discord_btn:
            discord_btn.click()
        else:
            raise Exception("未找到 Discord 登录按钮，可能页面加载失败。")
            
        print(">>> 正在跳转至 Discord 授权页...")
        time.sleep(5)
        
        # ==================== 阶段二：Discord 登录/授权处理 ====================
        if "discord.com" in page.url:
            print(">>> [3/7] 已到达 Discord，判断登录状态...")
            
            # 【情况 A：Cookie 失效，需要输入密码】
            if page.ele('css:input[name="email"]'):
                print(">>> Cookie 未能维持登录态，执行账号密码补救登录...")
                email = os.environ.get("DISCORD_EMAIL")
                password = os.environ.get("DISCORD_PASSWORD")
                
                if not email or not password:
                    raise Exception("Cookie 失效且未配置账号密码 Secret，无法继续！")

                page.ele('css:input[name="email"]').input(email)
                page.ele('css:input[name="password"]').input(password)
                
                print(">>> 点击登录...")
                page.ele('css:button[type="submit"]').click()
                time.sleep(5)
                
                # 检查是否出现强力验证码
                if "captcha" in page.html or "verify" in page.url:
                    print("⚠️ 严重警告：触发了 Discord 验证码/异地验证，脚本可能无法通过。")
            else:
                print(">>> Cookie 有效！跳过了密码输入步骤。")

            # 【情况 B：点击授权】
            # 无论是否刚登录，都可能需要点击 "授权/Authorize"
            print(">>> [4/7] 寻找授权按钮...")
            time.sleep(3)
            # 兼容中文和英文界面的按钮
            auth_btn = page.ele('text:Authorize') or page.ele('text:授权') or page.ele('css:button div:contains("Authorize")')
            
            if auth_btn:
                print(">>> 点击授权...")
                auth_btn.click()
            else:
                print(">>> 未找到授权按钮（可能已自动跳转或已授权），继续等待...")

        # ==================== 阶段三：验证登录结果 ====================
        print(">>> [5/7] 等待跳转回 Katabump 面板...")
        # 轮询 30 秒等待跳转
        for i in range(30):
            if "katabump.com" in page.url and "login" not in page.url:
                print(">>> 登录成功！已进入面板。")
                break
            time.sleep(1)
            
        if "login" in page.url:
             # 截图供调试
             page.get_screenshot(path='login_failed.jpg')
             raise Exception("登录失败：流程结束后仍然停留在登录页，请检查 Secrets。")

        # ==================== 阶段四：执行服务器续期 ====================
        target_url = "https://dashboard.katabump.com/servers/edit?id=197288"
        print(f">>> [6/7] 进入目标服务器: {target_url}")
        page.get(target_url)
        time.sleep(5)

        # 1. 点击主界面的 Renew 按钮
        main_renew = None
        # 查找所有包含 Renew 的元素，筛选出真正的按钮
        for btn in page.eles('text:Renew'):
            if btn.tag == 'button' or 'btn' in btn.attr('class'):
                main_renew = btn
                break
        
        if not main_renew:
            # 尝试找中文 "续期"
            main_renew = page.ele('text:续期')

        if main_renew:
            main_renew.click()
            print(">>> 已点击主 Renew 按钮，等待弹窗...")
            time.sleep(3)
            
            # 2. 处理弹窗内的 Cloudflare 验证 (Iframe)
            print(">>> [7/7] 处理弹窗验证与确认...")
            try:
                # 定位 src 开头为 challenges.cloudflare.com 的 iframe
                iframe = page.get_frame('@src^https://challenges.cloudflare.com')
                if iframe:
                    print(">>> 发现验证框，尝试点击...")
                    iframe.ele('tag:body').click() 
                    time.sleep(4) # 等待验证通过
                else:
                    print(">>> 未发现验证框 (可能无需验证)。")
            except:
                pass
            
            # 3. 点击弹窗内的最终确认按钮
            # 定位 class 为 modal-content 的弹窗容器
            modal = page.ele('css:.modal-content')
            if modal:
                # 在弹窗里找按钮，防止点错
                final_btn = modal.ele('text:Renew') or modal.ele('css:button.btn-primary')
                if final_btn:
                    final_btn.click()
                    print("✅✅✅ 续期成功！任务完成。")
                else:
                    print("❌ 错误：在弹窗里没找到 Renew 确认按钮")
            else:
                print("❌ 错误：弹窗未正常显示")
        else:
            print("❌ 错误：主界面未找到 Renew 按钮")

    except Exception as e:
        print(f"❌ 运行出错: {e}")
        # 保存全屏截图到 GitHub Artifacts
        page.get_screenshot(path='error_screenshot.jpg', full_page=True)
        exit(1) # 退出代码 1，通知 GitHub Action 任务失败
    finally:
        page.quit()

if __name__ == "__main__":
    job()
