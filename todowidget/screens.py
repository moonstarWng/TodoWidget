# -*- coding: utf-8 -*-
"""显示器布局

双屏 / 单屏来回切的时候, 窗口要能落到当前这一套屏里;
每种屏幕配置各自记住一个位置。
"""

import ctypes
from ctypes import wintypes


class RECT(ctypes.Structure):
    """Win32 的矩形"""

    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    """GetMonitorInfo 要的结构体"""

    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong)]


def monitors():
    """所有显示器的可用区域(不含任务栏), 每项是 (x, y, w, h)"""
    items = []
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return items
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR,
                                   wintypes.HDC, ctypes.POINTER(RECT),
                                   ctypes.c_void_p)

    def callback(hmonitor, hdc, rect, data):
        try:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                work = info.rcWork
                width = work.right - work.left
                height = work.bottom - work.top
                if width > 0 and height > 0:
                    items.append((work.left, work.top, width, height))
        except Exception:
            pass
        return 1

    try:
        user32.EnumDisplayMonitors(0, None, proc_type(callback), 0)
    except Exception:
        return items
    if not items:
        try:
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            if width > 0 and height > 0:
                items.append((0, 0, width, height))
        except Exception:
            pass
    return items


def layout_key():
    """当前屏幕配置的标识(接口/分辨率一变就不一样)"""
    items = monitors()
    if not items:
        return ""
    parts = ["{},{}x{}x{}".format(x, y, w, h) for x, y, w, h in sorted(items)]
    return "|".join(parts)


def fit_on_screen(x, y, width, height, margin=24):
    """把窗口挪到某块屏里, 别让它整个跑到屏幕外

    :param x: 希望的左上角横坐标
    :param y: 希望的左上角纵坐标
    :param width: 窗口宽
    :param height: 窗口高
    :param margin: 至少留多少像素在屏内
    """
    items = monitors()
    if not items:
        return x, y
    for mx, my, mw, mh in items:
        if (mx - width + margin <= x <= mx + mw - margin
                and my - height + margin <= y <= my + mh - margin):
            new_x = max(mx - width + margin, min(x, mx + mw - margin))
            new_y = max(my, min(y, my + mh - margin))
            return new_x, new_y
    # 哪个屏都放不下: 摆到主屏右上角, 跟首次启动的位置一致
    mx, my, mw, mh = items[0]
    new_x = mx + mw - width - 40
    new_y = my + max(60, mh // 10)
    return max(mx, new_x), max(my, new_y)


def parse_geom(geom):
    """'280x440+300+200' -> (280, 440, 300, 200), 解析不了就返回 None

    :param geom: 几何字符串
    """
    text = str(geom or "").strip()
    if "x" not in text or "+" not in text and "-" not in text[1:]:
        return None
    try:
        size, rest = text.split("+", 1)
        width, height = size.split("x")
        parts = rest.split("+")
        x = int(parts[0])
        y = int(parts[1])
        return int(width), int(height), x, y
    except Exception:
        return None


def fit_geom(geom, margin=24):
    """把几何字符串夹到当前屏幕里

    :param geom: 几何字符串
    :param margin: 至少留多少像素在屏内
    """
    parsed = parse_geom(geom)
    if parsed is None:
        return ""
    width, height, x, y = parsed
    new_x, new_y = fit_on_screen(x, y, width, height, margin)
    return "{}x{}+{}+{}".format(width, height, new_x, new_y)
