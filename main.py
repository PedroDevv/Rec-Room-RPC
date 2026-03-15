import asyncio
import time
import sys
import json
import os
import threading
import winreg

import requests

def _missing_dep():
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, "Missing dependencies.\nPlease run RUNME.bat first.", "Rec Room RPC", 0x10)
    sys.exit(1)

try:
    from curl_cffi.requests import get as cffi_get
except ImportError:
    _missing_dep()

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    _missing_dep()

try:
    from pypresence import AioPresence as Presence
    import pypresence.exceptions as pye
except ImportError:
    _missing_dep()

try:
    import psutil
except ImportError:
    _missing_dep()

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    _missing_dep()

import tkinter as tk
from tkinter import messagebox


def show_error(title: str, message: str):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, message)
    root.destroy()


def show_info(title: str, message: str):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(title, message)
    root.destroy()


def ask_yes_no(title: str, message: str) -> bool:
    root = tk.Tk()
    root.withdraw()
    result = messagebox.askyesno(title, message)
    root.destroy()
    return result


def ask_input(title: str, prompt: str) -> str:
    import tkinter.simpledialog as sd
    root = tk.Tk()
    root.withdraw()
    result = sd.askstring(title, prompt) or ""
    root.destroy()
    return result.strip()


DISCORD_CLIENT_ID = "1482466537817374760"
CONFIG_FILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
POLL_INTERVAL     = 30
RECNET_BASE       = "https://rec.net"
STARTUP_KEY       = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME      = "RecRoomRPC"
RR_PROCESS        = "RecRoom.exe"

DEVICE_CLASS_MAP = {
    0: ("rec_room_logo", "Rec Room"),
    1: ("quest",         "Meta Quest"),
    2: ("screenmode",    "Screen Mode (PC)"),
    3: ("pcvr",          "Windows VR"),
    4: ("ios",           "iOS"),
    5: ("android",       "Android"),
    6: ("psvr",          "PlayStation VR"),
    7: ("xbox",          "Xbox"),
    8: ("ps5",           "PlayStation 5"),
}

_access_token = ""
_cookies      = {}
_tray_icon    = None
_stop_event   = threading.Event()


def _build_cookie_header(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def get_match_headers() -> dict:
    h = {
        "Authorization": f"Bearer {_access_token}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Origin":  "https://rec.net",
        "Referer": "https://rec.net/",
    }
    if _cookies:
        h["Cookie"] = _build_cookie_header(_cookies)
    return h


def _browser_login() -> tuple[str, dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=520,720"])
        context = browser.new_context(viewport={"width": 520, "height": 720})
        page    = context.new_page()
        page.goto(RECNET_BASE, wait_until="domcontentloaded")

        token       = None
        cookie_dict = {}

        while True:
            time.sleep(1)
            try:
                raw = page.evaluate("() => localStorage.getItem('na_current_user_session')")
            except Exception:
                continue
            if not raw:
                continue
            try:
                data  = json.loads(raw)
                token = data.get("accessToken", "")
            except Exception:
                continue
            if not token:
                continue

            for c in context.cookies():
                cookie_dict[c["name"]] = c["value"]

            try:
                page.evaluate(
                    "() => { document.body.innerHTML = "
                    "'<div style=\"font-family:sans-serif;display:flex;"
                    "align-items:center;justify-content:center;height:100vh;"
                    "font-size:20px;color:#333;text-align:center;padding:24px\">"
                    "Logged in!<br><br>You can close this window.</div>'; }"
                )
            except Exception:
                pass

            time.sleep(1.5)
            browser.close()
            return token, cookie_dict

        browser.close()
        raise ValueError("Login window closed before login completed.")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_startup_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, STARTUP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def set_startup(enabled: bool):
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE)
    if enabled:
        exe = sys.executable
        script = os.path.abspath(__file__)
        winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, f'"{exe}" "{script}"')
        print(f"  Startup enabled.")
    else:
        try:
            winreg.DeleteValue(key, STARTUP_NAME)
            print(f"  Startup disabled.")
        except FileNotFoundError:
            pass
    winreg.CloseKey(key)


def is_rec_room_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == RR_PROCESS:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def get_account(username: str) -> dict | None:
    try:
        r = cffi_get(
            f"https://accounts.rec.net/account?username={username}",
            headers=get_match_headers(),
            impersonate="chrome120",
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if isinstance(data, dict) and data.get("accountId"):
                return data
    except Exception as e:
        print(f"  Account fetch error: {e}")
    return None


def get_room(instance_name: str, room_id: int) -> dict | None:
    if not instance_name or not instance_name.startswith("^"):
        return None
    try:
        r = cffi_get(
            f"https://rooms.rec.net/rooms/{room_id}",
            headers=get_match_headers(),
            impersonate="chrome120",
            timeout=8,
        )
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"  Room fetch error: {e}")
    return None


def get_location(account_id: int) -> dict | None:
    try:
        r = cffi_get(
            f"https://match.rec.net/player?id={account_id}",
            headers=get_match_headers(),
            impersonate="chrome120",
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if isinstance(data, list):
                data = data[0] if data else None
            return data or None
    except Exception as e:
        print(f"  Location error: {e}")
    return None


def room_image_url(image_name: str | None) -> str | None:
    if not image_name:
        return None
    return f"https://img.rec.net/{image_name}?width=360"


def profile_image_url(image_name: str | None) -> str | None:
    if not image_name:
        return None
    return f"https://img.rec.net/{image_name}?width=192&cropSquare=true"


def get_device_asset(device_class: int) -> tuple[str, str]:
    return DEVICE_CLASS_MAP.get(device_class, ("rec_room_logo", "Rec Room"))


def do_login() -> tuple[str, str, dict]:
    show_info(
        "Rec Room RPC: Login",
        "A browser window will open for you to log in to Rec Room.\n\n"
        "Your login goes directly from your PC to rec.net.\n"
        "Your password is never stored or sent anywhere.\n"
        "Only a session token is saved locally to config.json.\n"
        "Delete config.json at any time to log out."
    )

    token, cookies = _browser_login()

    username = ask_input("Rec Room RPC", "Enter your Rec Room username (without @):")
    if not username:
        show_error("Rec Room RPC", "No username entered. Exiting.")
        sys.exit(1)

    save_config({"username": username, "cookies": cookies})
    return username, token, cookies


def make_tray_icon_image() -> Image.Image:
    img  = Image.new("RGB", (64, 64), color=(255, 94, 20))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=(255, 255, 255))
    draw.ellipse([20, 20, 44, 44], fill=(255, 94, 20))
    return img


def start_tray(username: str):
    global _tray_icon

    def on_toggle_startup(icon, item):
        enabled = not is_startup_enabled()
        set_startup(enabled)
        icon.update_menu()

    def on_logout(icon, item):
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        set_startup(False)
        icon.stop()
        _stop_event.set()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def on_quit(icon, item):
        icon.stop()
        _stop_event.set()

    def startup_label(item):
        return "Disable run at startup" if is_startup_enabled() else "Enable run at startup"

    menu = pystray.Menu(
        pystray.MenuItem(f"Logged in as @{username}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(startup_label, on_toggle_startup),
        pystray.MenuItem("Log out", on_logout),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    _tray_icon = pystray.Icon(
        "RecRoomRPC",
        make_tray_icon_image(),
        "Rec Room RPC",
        menu,
    )
    _tray_icon.run()


async def connect_rpc() -> Presence | None:
    rpc = Presence(DISCORD_CLIENT_ID)
    try:
        await rpc.connect()
        return rpc
    except (pye.InvalidPipe, FileNotFoundError):
        return None
    except Exception:
        return None


async def set_idle(rpc, username, display_name, profile_img):
    try:
        await rpc.update(
            details="In the menus",
            large_image="rec_room_logo",
            large_text="Rec Room",
            small_image=profile_img or "rec_room_logo",
            small_text=display_name,
            buttons=[{"label": "View Profile", "url": f"https://rec.net/user/{username}"}],
        )
    except Exception:
        pass


async def set_in_room(rpc, *, room_display, room_tag, state_str,
                      start, large_img, profile_img, display_name, room_url, username):
    kwargs = dict(
        details=f"Playing {room_display}",
        state=state_str,
        start=start,
        large_image=large_img or "rec_room_logo",
        large_text=room_tag,
        small_image=profile_img or "rec_room_logo",
        small_text=display_name,
    )
    buttons = [{"label": "View Profile", "url": f"https://rec.net/user/{username}"}]
    if room_url:
        buttons.insert(0, {"label": "View Room", "url": room_url})
    kwargs["buttons"] = buttons[:2]
    await rpc.update(**kwargs)


async def presence_loop(username: str):
    global _access_token

    acct = get_account(username)
    if not acct:
        print("  Could not find account.")
        return

    account_id    = acct["accountId"]
    display_name  = acct.get("displayName") or username
    profile_image = profile_image_url(acct.get("profileImage") or acct.get("ProfileImage"))

    rpc = await connect_rpc()
    if not rpc:
        print("  Could not connect to Discord.")
        return

    print(f"  [{time.strftime('%H:%M:%S')}] Rec Room launched — RPC active")

    last_room_id = None
    room_start   = None
    cached_room  = None

    try:
        while not _stop_event.is_set() and is_rec_room_running():
            tick = time.monotonic()

            location     = get_location(account_id)
            is_online    = (location or {}).get("isOnline", False) if location else False
            device_class = (location or {}).get("deviceClass", 0)
            p_asset, p_label = get_device_asset(device_class)
            room_inst    = (location or {}).get("roomInstance") if location else None
            room_id      = (room_inst or {}).get("roomId") if room_inst else None

            if not location or not is_online or not room_inst or not room_id:
                await set_idle(rpc, username, display_name, profile_image)
                last_room_id = None
                room_start   = None
                cached_room  = None
            else:
                is_full        = room_inst.get("isFull", False)
                is_in_progress = room_inst.get("isInProgress", False)
                instance_name  = room_inst.get("name", "")

                if room_id != last_room_id:
                    room_start   = int(time.time())
                    last_room_id = room_id
                    cached_room  = None

                if cached_room is None:
                    cached_room = get_room(instance_name, room_id)

                is_dorm = instance_name.startswith("@")
                rname   = instance_name.lstrip("^@")

                if is_dorm:
                    dorm_owner      = instance_name.lstrip("@").split("'")[0]
                    room_display    = f"{dorm_owner}'s Dorm"
                    room_tag        = room_display
                    img_url         = None
                    rec_net_url     = None
                    is_private_room = True
                elif cached_room:
                    room_display    = cached_room.get("DisplayName") or cached_room.get("displayName") or rname
                    img_url         = room_image_url(cached_room.get("ImageName") or cached_room.get("imageName"))
                    rec_net_url     = f"https://rec.net/room/{rname}" if rname else None
                    room_tag        = f"^{rname}" if rname else f"Room #{room_id}"
                    is_private_room = False
                else:
                    room_display    = "[Private Room]"
                    room_tag        = "[Private Room]"
                    img_url         = None
                    rec_net_url     = None
                    is_private_room = True

                if is_dorm:
                    state_str = "In Their Dorm"
                elif is_private_room:
                    state_str = "Private Room"
                elif is_in_progress:
                    state_str = "In a match"
                elif is_full:
                    state_str = "Server Full"
                else:
                    state_str = "Public Room"

                await set_in_room(
                    rpc,
                    room_display=room_display,
                    room_tag=room_tag,
                    state_str=state_str,
                    start=room_start,
                    large_img=img_url,
                    profile_img=profile_image,
                    display_name=display_name,
                    room_url=rec_net_url if not is_private_room else None,
                    username=username,
                )
                print(f"  [{time.strftime('%H:%M:%S')}] {room_display}  |  {state_str}  |  {p_label}")

            await asyncio.sleep(max(0, POLL_INTERVAL - (time.monotonic() - tick)))

    finally:
        try:
            await rpc.clear()
            rpc.close()
        except Exception:
            pass
        print(f"  [{time.strftime('%H:%M:%S')}] Rec Room closed — RPC cleared")


def watch_loop(username: str):
    print(f"  Waiting for Rec Room to launch...")
    print(f"  (Right-click the tray icon to manage settings)")
    print()

    while not _stop_event.is_set():
        if is_rec_room_running():
            asyncio.run(presence_loop(username))
            if not _stop_event.is_set():
                print(f"  Waiting for Rec Room to launch...")
        time.sleep(5)


if __name__ == "__main__":
    print("-" * 50)
    print("  Rec Room Discord Rich Presence")
    print("-" * 50)

    config        = load_config()
    username      = config.get("username", "").strip()
    saved_cookies = config.get("cookies", {})

    if not username or not saved_cookies:
        username, _access_token, _cookies = do_login()

        if ask_yes_no("Rec Room RPC", "Run automatically at Windows startup?"):
            set_startup(True)
    else:
        _cookies = saved_cookies
        try:
            r = cffi_get(
                f"{RECNET_BASE}/api/auth/session",
                headers={
                    "Cookie": _build_cookie_header(_cookies),
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                },
                impersonate="chrome120",
                timeout=10,
            )
            token = r.json().get("accessToken", "") if r.ok else ""
            if token:
                _access_token = token
                print(f"  Session restored for @{username}\n")
            else:
                raise ValueError("no token")
        except Exception:
            show_info("Rec Room RPC", "Your session has expired. Please log in again.")
            os.remove(CONFIG_FILE)
            username, _access_token, _cookies = do_login()

    watcher = threading.Thread(target=watch_loop, args=(username,), daemon=True)
    watcher.start()

    show_info(
        "Rec Room RPC — Running",
        f"Rec Room RPC is now running in the background as @{username}.\n\n"
        "It will automatically activate when Rec Room launches.\n\n"
        "To close or restart, right-click the tray icon near your clock."
    )

    start_tray(username)
