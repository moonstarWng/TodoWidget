# -*- coding: utf-8 -*-
"""配色与主题

所有颜色挂在全局唯一的 Palette 实例 P 上, 换主题时原地改属性,
各模块共享同一个对象, 不会出现"改完主题某些地方还是旧色"的问题。
"""

import tkinter.font as tkfont


class Palette:
    """当前生效的一套颜色"""

    # 主界面
    bg = "#17181d"
    bg_alt = "#1e2027"
    head = "#131418"
    border = "#2b2e38"
    group_bg = "#202330"
    hover = "#2c3242"
    fg = "#e8e9ee"
    fg_dim = "#8b8d99"
    fg_faint = "#555863"
    accent = "#5b9cff"
    done = "#5c6070"
    group = "#ffffff"
    sel = "#2d4c7d"
    ghost_bg = "#2f5fa8"

    # 便签(米黄纸, 有意跟主窗体区分开)
    note_bg = "#f7ebc9"
    note_head = "#ecdcae"
    note_fg = "#33302a"
    note_dim = "#857a5f"
    note_edge = "#c9b481"
    note_code = "#ead9a9"
    note_mark = "#a8863f"
    note_link = "#1a56a8"


P = Palette()

THEMES = {
    "dark": dict(
        bg="#17181d", bg_alt="#1e2027", head="#131418", border="#2b2e38",
        group_bg="#202330", hover="#2c3242", fg="#e8e9ee", fg_dim="#8b8d99",
        fg_faint="#555863", accent="#5b9cff", done="#5c6070",
        group="#ffffff", sel="#2d4c7d"),
    "light": dict(
        bg="#f7f8fa", bg_alt="#eceef2", head="#ffffff", border="#dcdfe6",
        group_bg="#eaeef7", hover="#e2e8f5", fg="#23252b", fg_dim="#6c7181",
        fg_faint="#a2a8b4", accent="#3b7cf6", done="#a3a7b3",
        group="#15171c", sel="#cfddfb"),
    "forest": dict(
        bg="#131a17", bg_alt="#18211d", head="#0e1512", border="#26332c",
        group_bg="#1b2621", hover="#22322a", fg="#e6efe9", fg_dim="#89a294",
        fg_faint="#4f6157", accent="#43c08a", done="#5a6b62",
        group="#ffffff", sel="#1f4636"),
    "sand": dict(
        bg="#1d1a16", bg_alt="#26221c", head="#161310", border="#3a342b",
        group_bg="#262119", hover="#302a20", fg="#f0e9de", fg_dim="#a2978a",
        fg_faint="#6a6053", accent="#e0a458", done="#6b6257",
        group="#fff8ee", sel="#4a3a24"),
}

THEME_NAMES = (("dark", "深色"), ("light", "浅色"),
               ("forest", "墨绿"), ("sand", "暖沙"))

LIST_COLORS = ("#5b9cff", "#43c08a", "#e0a458", "#c86bd8",
               "#e06b6b", "#3fb8cc")
TAB_COLORS = {"pending": None, "done": "#43c08a"}

TEXTURE_NAMES = (("solid", "纯色"), ("paper", "纸质"), ("glass", "磨砂"))

# 纸质质感: 暖米色, 不管当前主题是什么都用这套
PAPER_SCHEME = dict(
    bg="#f4ecdc", bg_alt="#ece2cd", head="#f0e8d6", border="#d5c5a3",
    group_bg="#e9dfc7", hover="#e3d7bd", fg="#3a3226", fg_dim="#7e735c",
    fg_faint="#a99d84", accent="#b07b32", done="#a89b82",
    group="#221d15", sel="#dcc9a2")

FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "TkDefaultFont")


def apply_palette(scheme, accent=None):
    """按一套配色改 P; accent 只影响强调色"""
    P.bg = scheme["bg"]
    P.bg_alt = scheme["bg_alt"]
    P.head = scheme["head"]
    P.border = scheme["border"]
    P.group_bg = scheme["group_bg"]
    P.hover = scheme["hover"]
    P.fg = scheme["fg"]
    P.fg_dim = scheme["fg_dim"]
    P.fg_faint = scheme["fg_faint"]
    P.done = scheme["done"]
    P.group = scheme["group"]
    P.sel = scheme["sel"]
    if accent:
        P.accent = accent
    else:
        P.accent = scheme["accent"]
    P.ghost_bg = P.accent


def set_theme(name, accent=None):
    """切换配色, 直接改在共享的 P 上"""
    theme = THEMES.get(name)
    if theme is None:
        theme = THEMES["dark"]
    apply_palette(theme, accent)


def use_paper(accent=None):
    """切到纸质配色"""
    apply_palette(PAPER_SCHEME, accent)


def pick_font(root, size, weight="normal", overstrike=False):
    """挑一个系统里有的中文字体"""
    families = set(tkfont.families(root))
    family = next((f for f in FONTS if f in families), "TkDefaultFont")
    return tkfont.Font(root=root, family=family, size=size,
                       weight=weight, overstrike=overstrike)


def hex_to_rgb(value):
    """'#5b9cff' -> (91, 156, 255)"""
    text = value.lstrip("#")
    if len(text) != 6:
        return (91, 156, 255)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (91, 156, 255)


def best_text_color(hex_color):
    """深色底配白字, 浅色底配黑字"""
    red, green, blue = hex_to_rgb(hex_color)
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    if brightness > 150:
        return "#1c1d22"
    return "#ffffff"


set_theme("dark")
