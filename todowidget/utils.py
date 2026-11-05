# -*- coding: utf-8 -*-
"""系统相关的小工具: 单实例、日志、窗口摆放、图标、测试事件"""

import ctypes
import ctypes.wintypes
import os
import traceback
import webbrowser
from datetime import datetime

import tkinter as tk

try:
    import pystray
    from PIL import Image, ImageChops, ImageDraw, ImageTk

    HAS_TRAY = True
except Exception:  # 没装 pystray/pillow 也能跑, 只是没有托盘
    HAS_TRAY = False

from .paths import APP_DIR
from .theme import P, hex_to_rgb

class MonitorInfo(ctypes.Structure):
    """win32 的 MONITORINFO, 用来算便签该摆在哪个屏幕中间"""

    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.c_ulong),
    ]

def open_url(url):
    """用系统默认浏览器打开链接"""
    if not url:
        return False
    if url.lower().startswith("www."):
        url = "http://" + url
    try:
        os.startfile(url)
        return True
    except Exception:
        pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False

def place_window(window, x, y, width, height):
    """把无边框窗口摆到指定位置(只动窗口本身, 不涉及鼠标键盘)"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        flags = 0x0004 | 0x0010 | 0x0040  # NOZORDER | NOACTIVATE | SHOWWINDOW
        user32.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height),
                            flags)
        return True
    except Exception:
        return False

class FakeEvent:
    """测试用的事件对象, 字段和 Tk 事件保持一致"""

    def __init__(self, widget, x, y):
        self.widget = widget
        self.x = x
        self.y = y
        try:
            self.x_root = widget.winfo_rootx() + x
            self.y_root = widget.winfo_rooty() + y
        except Exception:
            self.x_root = x
            self.y_root = y


# --------------------------------------------------------------------------
# 数据
# --------------------------------------------------------------------------

def make_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    red, green, blue = hex_to_rgb(P.accent)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14,
                        fill=(red, green, blue, 255))
    w = max(4, size // 9)
    d.line([(size * 0.24, size * 0.52), (size * 0.43, size * 0.72),
            (size * 0.76, size * 0.30)], fill=(255, 255, 255, 255), width=w,
           joint="curve")
    return img

def single_instance():
    """返回 False 表示已有实例在跑"""
    try:
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateMutexW(None, False, "DesktopTodoWidgetMutex")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False, h
        return True, h
    except Exception:
        return True, None

def log_error(exc, val, tb):
    """把 Tk 回调里的异常写到文件, pythonw 下没有控制台也能查"""
    import traceback
    path = os.path.join(APP_DIR, "todo_error.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write("\n==== {} ====\n".format(stamp))
            traceback.print_exception(exc, val, tb, file=f)
    except Exception:
        pass

class TkApp(tk.Tk):
    def report_callback_exception(self, exc, val, tb):
        log_error(exc, val, tb)
