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
    # 下面这些都是照着比较有名的配色方案抄的
    "nord": dict(
        bg="#2e3440", bg_alt="#3b4252", head="#272c36", border="#434c5e",
        group_bg="#3b4252", hover="#434c5e", fg="#eceff4", fg_dim="#a9b3c4",
        fg_faint="#616e88", accent="#88c0d0", done="#7b869c",
        group="#ffffff", sel="#4c566a"),
    "dracula": dict(
        bg="#282a36", bg_alt="#343746", head="#21222c", border="#44475a",
        group_bg="#343746", hover="#44475a", fg="#f8f8f2", fg_dim="#b8b9c8",
        fg_faint="#6272a4", accent="#bd93f9", done="#7f839c",
        group="#ffffff", sel="#6272a4"),
    "solarized_dark": dict(
        bg="#002b36", bg_alt="#073642", head="#00212b", border="#0f4b57",
        group_bg="#073642", hover="#0f4b57", fg="#eee8d5", fg_dim="#93a1a1",
        fg_faint="#586e75", accent="#b58900", done="#71908f",
        group="#fdf6e3", sel="#1c5a66"),
    "solarized_light": dict(
        bg="#fdf6e3", bg_alt="#eee8d5", head="#f7f0dd", border="#d9d2bf",
        group_bg="#eee8d5", hover="#e6dfcb", fg="#073642", fg_dim="#586e75",
        fg_faint="#93a1a1", accent="#268bd2", done="#a3a294",
        group="#002b36", sel="#cfe3ee"),
    "tokyo_night": dict(
        bg="#1a1b26", bg_alt="#24283b", head="#16161e", border="#2f3549",
        group_bg="#24283b", hover="#2f3549", fg="#c0caf5", fg_dim="#a9b1d6",
        fg_faint="#565f89", accent="#7aa2f7", done="#6b7398",
        group="#ffffff", sel="#3b4261"),
    "gruvbox": dict(
        bg="#282828", bg_alt="#32302f", head="#1d2021", border="#3c3836",
        group_bg="#32302f", hover="#3c3836", fg="#ebdbb2", fg_dim="#bdae93",
        fg_faint="#7c6f64", accent="#fabd2f", done="#8c8375",
        group="#fbf1c7", sel="#504945"),
    "catppuccin": dict(
        bg="#1e1e2e", bg_alt="#27273a", head="#181825", border="#313244",
        group_bg="#27273a", hover="#313244", fg="#cdd6f4", fg_dim="#a6adc8",
        fg_faint="#6c7086", accent="#cba6f7", done="#72758c",
        group="#ffffff", sel="#45475a"),
    "github": dict(
        bg="#ffffff", bg_alt="#f6f8fa", head="#f6f8fa", border="#d0d7de",
        group_bg="#f6f8fa", hover="#eaeef2", fg="#1f2328", fg_dim="#59636e",
        fg_faint="#8c959f", accent="#0969da", done="#8c959f",
        group="#1f2328", sel="#ddf4ff"),
    "monokai": dict(
        bg="#272822", bg_alt="#32332c", head="#1f201b", border="#3e3f36",
        group_bg="#32332c", hover="#3e3f36", fg="#f8f8f2", fg_dim="#c5c6bb",
        fg_faint="#75715e", accent="#f92672", done="#8b8c80",
        group="#ffffff", sel="#49483e"),
}

THEME_NAMES = (("dark", "深色"), ("light", "浅色"),
               ("forest", "墨绿"), ("sand", "暖沙"),
               ("nord", "Nord"), ("dracula", "Dracula"),
               ("solarized_dark", "Solar 深"), ("solarized_light", "Solar 浅"),
               ("tokyo_night", "东京夜"), ("gruvbox", "Gruvbox"),
               ("catppuccin", "Catppuccin"), ("github", "GitHub 亮"),
               ("monokai", "Monokai"))

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


def mix_color(color_a, color_b, ratio):
    """两个颜色按比例混一混, ratio=0 是 a, 1 是 b"""
    a = hex_to_rgb(color_a)
    b = hex_to_rgb(color_b)
    parts = []
    for index in range(3):
        parts.append(int(round(a[index] + (b[index] - a[index]) * ratio)))
    return "#{:02x}{:02x}{:02x}".format(*parts)


def brightness(color):
    """颜色亮不亮(0~255), 判断深色还是浅色用"""
    red, green, blue = hex_to_rgb(color)
    return (red * 299 + green * 587 + blue * 114) / 1000.0


def custom_scheme(bg, accent):
    """从一个底色 + 一个强调色推出一整套配色

    只让用户挑两个颜色, 其余的(文字、边框、悬停、选中)按深浅自动配,
    省得自定义配色里出现看不清的组合。

    :param bg: 底色, 如 '#1b1d24'
    :param accent: 强调色, 如 '#ff4d6d'
    """
    dark = brightness(bg) < 140
    ink = "#ffffff" if dark else "#000000"
    fg = mix_color(bg, ink, 0.88 if dark else 0.82)
    head = mix_color(bg, "#000000", 0.10 if dark else 0.04)
    return dict(
        bg=bg,
        bg_alt=mix_color(bg, ink, 0.07),
        head=head,
        border=mix_color(bg, fg, 0.16),
        group_bg=mix_color(bg, ink, 0.06),
        hover=mix_color(bg, fg, 0.12),
        fg=fg,
        fg_dim=mix_color(fg, bg, 0.40),
        fg_faint=mix_color(fg, bg, 0.64),
        accent=accent,
        done=mix_color(fg, bg, 0.55),
        group=fg,
        sel=mix_color(accent, bg, 0.55),
    )


def best_text_color(hex_color):
    """深色底配白字, 浅色底配黑字"""
    red, green, blue = hex_to_rgb(hex_color)
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    if brightness > 150:
        return "#1c1d22"
    return "#ffffff"


set_theme("dark")
