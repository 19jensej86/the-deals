"""
Browser Context Manager
=======================
Manages Chrome browser context with:
- Profile cloning (to avoid conflicts with running Chrome)
- Cookie persistence (login state)
- Stealth mode (avoid detection)
"""

import os
import shutil
import subprocess
import tempfile
import time
from playwright.sync_api import Playwright, BrowserContext, Error as PWError

# Chrome profile path (Windows default)
CHROME_USER_DATA = r"C:\Users\JensFrejd\AppData\Local\Google\Chrome\User Data"
PROFILE_NAME = "Default"


def ensure_chrome_closed():
    """
    Ensures Chrome is not running before we clone the profile.
    Required because profile is locked when Chrome is running.
    """
    try:
        tasks = subprocess.check_output(["tasklist"], text=True)
        if "chrome.exe" in tasks.lower():
            print("⚠️  Chrome is running – closing it...")
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            print("✅ Chrome closed.")
    except Exception as e:
        print(f"⚠️ Could not check/close Chrome: {e}")


def clone_profile() -> str:
    """
    Creates a temporary copy of the Chrome profile.
    This allows us to use cookies/login without locking the original.
    
    Returns:
        Path to the temporary profile directory
    """
    temp_dir = tempfile.mkdtemp(prefix="ricardo_profile_")
    src = os.path.join(CHROME_USER_DATA, PROFILE_NAME)
    dest = os.path.join(temp_dir, PROFILE_NAME)

    try:
        print(f"📁 Cloning profile: {src} -> {dest}")
        shutil.copytree(
            src,
            dest,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "Cache", "GPUCache", "Code Cache", "Service Worker",
                "IndexedDB", "Local Storage", "Session Storage",
                "*.log", "*.tmp"
            ),
        )
        print("✅ Profile cloned.")
    except Exception as e:
        print(f"⚠️ Could not fully clone profile: {e}")

    return temp_dir


def cleanup_profile(path: str):
    """
    Removes the temporary profile directory.
    """
    try:
        shutil.rmtree(path, ignore_errors=True)
        print(f"🧹 Temp profile deleted: {path}")
    except Exception as e:
        print(f"⚠️ Could not delete temp profile: {e}")


def launch_persistent_context(
    p: Playwright,
    profile_dir: str,
    *,
    headless: bool = False,
    user_agent: str | None = None,
) -> BrowserContext:
    """
    Launches Chrome with persistent context (profile).
    
    Args:
        p: Playwright instance
        profile_dir: Path to the profile directory (from clone_profile)
        headless: Whether to run headless
        user_agent: Custom user agent string
    
    Returns:
        BrowserContext instance
    """
    try:
        args = [
            f"--profile-directory={PROFILE_NAME}",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-infobars",
            "--disable-extensions",
        ]
        
        if user_agent:
            args.append(f"--user-agent={user_agent}")

        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel="chrome",
            headless=headless,
            args=args,
            viewport={"width": 1920, "height": 1080},
            locale="de-CH",
            timezone_id="Europe/Zurich",
        )

        return ctx

    except PWError as e:
        print(f"❌ Chrome launch failed: {e}")
        cleanup_profile(profile_dir)
        raise