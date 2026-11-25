# -*- coding: utf-8 -*-
"""检查更新: 从 GitHub 取最新打包好的 exe, 换掉自己再重启"""

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .version import APP_VERSION

GITHUB_REPO = "moonstarWng/TodoWidget"
EXE_NAME = "待办清单.exe"
RELEASES_API = "https://api.github.com/repos/{}/releases/latest".format(
    GITHUB_REPO)
HEADERS = {"User-Agent": "TodoWidget-updater"}


def exe_path():
    """当前运行的 exe 路径; 用源码方式跑时返回 None"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return None


def build_time():
    """程序自身的构建时间(秒), 源码模式按本文件的时间算"""
    path = exe_path() or os.path.abspath(__file__)
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def version_text():
    """界面上显示的当前版本号"""
    return APP_VERSION


def build_text():
    """构建时间, 精确到分钟"""
    stamp = build_time()
    if not stamp:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def parse_version(text):
    """把 2026.11.19.1 这种版本号拆成可比较的数字元组"""
    parts = []
    for piece in re.split(r"[^0-9]+", text or ""):
        if piece:
            parts.append(int(piece))
    return tuple(parts)


def describe_error(exc):
    """把网络异常换成一句人话"""
    if isinstance(exc, socket.timeout):
        return "连接超时"
    if isinstance(exc, urllib.error.HTTPError):
        return "服务器返回 {}".format(exc.code)
    if isinstance(exc, urllib.error.URLError):
        return "连不上 GitHub，检查下网络"
    return "网络错误"


def _latest_release(timeout):
    """取最新的 GitHub Release 信息(dict)"""
    request = urllib.request.Request(RELEASES_API, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError("还没有发布过新版本")
        raise RuntimeError(describe_error(exc))
    except Exception as exc:
        raise RuntimeError(describe_error(exc))


def fetch_latest(timeout=12):
    """取最新 release 的版本号(用 tag 表示)"""
    data = _latest_release(timeout)
    tag = str(data.get("tag_name") or "").strip().lstrip("vV")
    if not tag:
        raise RuntimeError("发布里没有版本号")
    return tag


def is_newer(latest_version):
    """远端比自己新才算有更新"""
    return parse_version(latest_version) > parse_version(APP_VERSION)


def file_digest(path):
    """算文件 sha256"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(progress=None, timeout=90):
    """下载最新 exe 到程序目录, 返回临时文件路径

    内容跟当前程序一样就返回 None。

    :param progress: 下载进度回调, 参数是 0~1
    :param timeout: 单次读取超时(秒)
    """
    target = exe_path()
    if target is None:
        raise RuntimeError("现在是源码运行，请手动更新")
    data = _latest_release(timeout)
    url = None
    for asset in data.get("assets") or []:
        if (asset.get("name") or "").lower() == EXE_NAME.lower():
            url = asset.get("browser_download_url")
            break
    if not url:
        raise RuntimeError("发布里没有找到程序文件")
    headers = dict(HEADERS)
    headers["Accept"] = "application/octet-stream"
    request = urllib.request.Request(url, headers=headers)
    dest = target + ".new"
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            seen = 0
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    seen += len(chunk)
                    if progress is not None:
                        ratio = seen / float(total) if total else 0.0
                        progress(min(1.0, ratio))
    except Exception as exc:
        remove_quietly(dest)
        raise RuntimeError(describe_error(exc))
    if os.path.getsize(dest) < 1024 * 1024:
        remove_quietly(dest)
        raise RuntimeError("下载的文件不完整")
    with open(dest, "rb") as fh:
        if fh.read(2) != b"MZ":
            remove_quietly(dest)
            raise RuntimeError("下载到的不是程序文件")
    if file_digest(dest) == file_digest(target):
        remove_quietly(dest)
        return None
    return dest


def apply_and_restart(new_exe):
    """把新 exe 换上去, 然后等旧进程退出后自动重启

    :param new_exe: 已经下载好的新 exe 路径
    """
    target = exe_path()
    if target is None:
        raise RuntimeError("现在是源码运行，没法自动替换")
    old = target + ".old"
    remove_quietly(old)
    try:
        os.replace(target, old)
    except OSError as exc:
        raise RuntimeError("没法替换正在运行的程序: {}".format(exc))
    try:
        os.replace(new_exe, target)
    except OSError as exc:
        # 没换成功就把原来的名字改回来, 别把程序弄丢了
        try:
            os.replace(old, target)
        except OSError:
            pass
        raise RuntimeError("替换新版本失败: {}".format(exc))
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    command = 'ping -n 5 127.0.0.1 >nul & start "" "{}"'.format(target)
    subprocess.Popen(command, shell=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def remove_quietly(path):
    """删文件, 删不掉就算了"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def cleanup_old():
    """启动时清理上次更新留下的旧 exe / 半截下载"""
    target = exe_path()
    if target is None:
        return
    remove_quietly(target + ".old")
    remove_quietly(target + ".new")
