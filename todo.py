# -*- coding: utf-8 -*-
"""桌面待办清单 —— 启动入口

用法:
    pyw -3 todo.py            # 启动(无黑框)
    py -3 todo.py --console   # 带控制台启动, 便于看报错
    py -3 todo.py --selftest  # 自检(用临时数据, 不动你的清单)
"""

import ctypes
import sys

from todowidget.app import TodoApp
from todowidget.selftest import run_selftest
from todowidget.utils import TkApp, single_instance


def main():
    """启动程序, 或跑自检"""
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())

    ok, _handle = single_instance()
    if not ok:
        ctypes.windll.user32.MessageBoxW(
            None, "待办清单已经在运行了。\n图标在右下角托盘里，双击即可显示。",
            "待办清单", 0x40)
        return

    root = TkApp()
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID("todowidget.app")
    except Exception:
        pass
    TodoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
