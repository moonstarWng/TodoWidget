# -*- coding: utf-8 -*-
"""字体: 中文字体(本地化名字)和西文字体分开选

Windows 注册表里是英文名(SimSun), Tk 报出来的是本地化名(宋体),
这里加一张对照表把两边对齐; 自绘列表要的是字体文件, 也在这里解析。
"""

import io
import json
import os

try:
    from PIL import ImageFont
except Exception:
    ImageFont = None

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
CACHE_FILE = os.path.join(
    os.environ.get("APPDATA") or FONT_DIR, "TodoWidget", "font_cache.json")

# Tk 的本地化字体名 -> 注册表里的英文名
TK_ALIASES = {
    "宋体": "SimSun",
    "新宋体": "NSimSun",
    "黑体": "SimHei",
    "楷体": "KaiTi",
    "仿宋": "FangSong",
    "等线": "DengXian",
    "等线 Light": "DengXian Light",
    "微软雅黑": "Microsoft YaHei",
    "微软雅黑 Light": "Microsoft YaHei Light",
    "微軟正黑體": "Microsoft JhengHei",
    "微软正黑体": "Microsoft JhengHei",
    "標楷體": "DFKai-SB",
    "ＭＳ ゴシック": "MS Gothic",
    "ＭＳ 明朝": "MS Mincho",
    "游ゴシック": "Yu Gothic",
    "맑은 고딕": "Malgun Gothic",
}

# 名字里带这些的, 直接当中文字体(省得每个都去探一遍)
CJK_HINTS = ("yahei", "simsun", "simhei", "nsimsun", "dengxian", "kaiti",
             "fangsong", "jhenghei", "msjh", "msyh", "songti", "heiti",
             "noto sans cjk", "noto serif cjk", "source han", "wenkai",
             "宋", "黑", "楷", "仿", "等线", "雅黑", "正黑", "明體", "明朝",
             "ゴシック", "고딕", "方正", "汉仪", "思源")

_paths = None
_names = None


def _scan():
    """扫注册表, 建 字族名 -> 字体文件 的映射"""
    global _paths, _names
    if _paths is not None:
        return
    paths = {}
    names = {}
    try:
        import winreg
    except Exception:
        _paths, _names = paths, names
        return
    roots = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    for hive, key_path in roots:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
        try:
            count = winreg.QueryInfoKey(key)[1]
            for index in range(count):
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    continue
                clean = name
                for suffix in ("(TrueType)", "(OpenType)", "(All res)"):
                    clean = clean.replace(suffix, "")
                for part in clean.split("&"):
                    family = part.strip()
                    if not family:
                        continue
                    full = value
                    if not os.path.isabs(full):
                        full = os.path.join(FONT_DIR, full)
                    if not os.path.exists(full):
                        continue
                    key_name = family.lower()
                    paths.setdefault(key_name, full)
                    names.setdefault(key_name, family)
        finally:
            try:
                winreg.CloseKey(key)
            except Exception:
                pass
    _paths, _names = paths, names


def registry_families():
    """注册表里的字族名(英文名, 排好序)"""
    _scan()
    return sorted(_names.values(), key=lambda text: text.lower())


def font_file(family):
    """按字族名(英文名或 Tk 的本地化名)找字体文件

    :param family: 字族名
    """
    if not family:
        return ""
    _scan()
    name = str(family).strip()
    found = _paths.get(name.lower(), "")
    if found:
        return found
    alias = TK_ALIASES.get(name)
    if alias:
        return _paths.get(alias.lower(), "")
    return ""


def resolve(family):
    """把一个字体名换成注册表里的英文名(能对上的话)

    :param family: 字族名, 可以是 Tk 的本地化名
    """
    name = str(family or "").strip()
    if not name:
        return ""
    _scan()
    if name.lower() in _paths:
        return _names.get(name.lower(), name)
    alias = TK_ALIASES.get(name)
    if alias:
        return alias
    return name


def load(family, size, bold=False):
    """按字族名加载 PIL 字体

    :param family: 字族名(本地化名也行)
    :param size: 像素大小
    :param bold: 要不要粗体
    """
    if ImageFont is None or not family:
        return None
    base = resolve(family)
    if bold:
        path = font_file(base + " Bold")
        if path:
            font = _open_face(path, base, size)
            if font is not None:
                return font
    path = font_file(base)
    if not path:
        return None
    return _open_face(path, base, size)


def _open_face(path, family, size):
    """在 ttc/ttf 里找到对应的 face

    :param path: 字体文件
    :param family: 期望的英文字族名
    :param size: 像素大小
    """
    want = str(family).strip().lower()
    for index in range(8):
        try:
            font = ImageFont.truetype(path, size, index=index)
        except Exception:
            break
        try:
            got = font.getname()[0].strip().lower()
        except Exception:
            got = ""
        if got == want:
            return font
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return None


def cjk_families(tk_families=()):
    """能显示中文的字体(优先用 Tk 报的名字, 这样两边都能用)

    :param tk_families: Tk 的可用字族; 不传就只用注册表里的名字
    """
    wanted = [name for name in tk_families if not name.startswith("@")]
    if not wanted:
        wanted = registry_families()
    cached = _read_cache()
    known = set(cached)
    result = []
    for name in wanted:
        if name in known or _can_draw_chinese(name):
            result.append(name)
    if not result:
        return ["Microsoft YaHei UI"]
    return result


def _can_draw_chinese(family):
    """这个字体能不能画出中文(中/文两个字都要画得出来且不一样)

    :param family: 字体名
    """
    base = resolve(family)
    if any(hint in str(base).lower() for hint in CJK_HINTS):
        return True
    path = font_file(base)
    if not path:
        return False
    font = _open_face(path, base, 14)
    if font is None:
        return False
    try:
        ref = font.getmask("\ue000")
        first = font.getmask("\u4e2d")
        second = font.getmask("\u6587")
        ref_sig = (ref.size, bytes(ref))
        first_sig = (first.size, bytes(first))
        second_sig = (second.size, bytes(second))
    except Exception:
        return False
    if first_sig == ref_sig or second_sig == ref_sig:
        return False
    return first_sig != second_sig


def _read_cache():
    """读中文字体缓存"""
    try:
        with io.open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [name for name in data if isinstance(name, str)]


def _write_cache(names):
    """写中文字体缓存

    :param names: 字体名列表
    """
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with io.open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False)
    except Exception:
        pass
