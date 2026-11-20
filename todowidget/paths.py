# -*- coding: utf-8 -*-
"""项目路径: 数据和配置都放在程序旁边

打包成 exe 后 sys.frozen 为真, 目录取 exe 所在位置,
这样数据不会跟着解包临时目录一起被清掉。
"""

import os
import shutil
import sys

# 程序本体所在目录(只放 exe 之类, 不放数据)
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 老版本把数据放在程序目录里, 迁走的时候按这些名字找
LEGACY_FILES = ("todo_data.db", "todo_config.json", "todo_data.json")
LEGACY_DIRS = ("theme_bg", "note_images")


def _base_dir():
    """默认数据目录: 用户漫游目录下固定的 TodoWidget"""
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if appdata:
        return os.path.join(appdata, "TodoWidget")
    return os.path.join(APP_DIR, "data")


BASE_DIR = _base_dir()
# 指针: 记着"数据现在在哪", 放在固定的 BASE_DIR 里
POINTER = os.path.join(BASE_DIR, "location.txt")


def _read_pointer():
    """读指针, 读出无效路径就当没有"""
    try:
        with open(POINTER, encoding="utf-8") as f:
            path = f.read().strip()
    except OSError:
        return ""
    if path and os.path.isdir(path):
        return path
    return ""


def _write_pointer(path):
    """写指针

    :param path: 数据目录
    """
    try:
        os.makedirs(os.path.dirname(POINTER), exist_ok=True)
        with open(POINTER, "w", encoding="utf-8") as f:
            f.write(path)
        return True
    except OSError:
        return False


def copy_data(source, target):
    """把数据从一处复制到另一处(已有的文件不覆盖)

    :param source: 源目录
    :param target: 目标目录
    """
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return False
    for name in LEGACY_FILES:
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass
    for name in LEGACY_DIRS:
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        if os.path.isdir(src) and not os.path.isdir(dst):
            try:
                shutil.copytree(src, dst)
            except OSError:
                pass
    return True


def _resolve():
    """定下数据目录: 有指针听指针, 没有就搬到默认目录(顺带迁一次老数据)"""
    picked = _read_pointer()
    if picked:
        return picked
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
    except OSError:
        return APP_DIR
    copy_data(APP_DIR, BASE_DIR)
    _write_pointer(BASE_DIR)
    return BASE_DIR


DATA_DIR = _resolve()

DATA_FILE = os.path.join(DATA_DIR, "todo_data.json")
DB_FILE = os.path.join(DATA_DIR, "todo_data.db")
CONF_FILE = os.path.join(DATA_DIR, "todo_config.json")


def switch_data_dir(target):
    """把数据换到另一个目录: 复制过去 + 改指针(重启后生效)

    :param target: 新的数据目录
    """
    if not target:
        return False
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return False
    copy_data(DATA_DIR, target)
    return _write_pointer(target)


def open_data_dir():
    """在资源管理器里打开数据目录"""
    try:
        os.startfile(DATA_DIR)
        return True
    except Exception:
        return False


def reset_data_dir():
    """恢复默认数据目录"""
    return _write_pointer(BASE_DIR)
