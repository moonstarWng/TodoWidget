# -*- coding: utf-8 -*-
"""项目路径: 数据和配置都放在程序旁边

打包成 exe 后 sys.frozen 为真, 目录取 exe 所在位置,
这样数据不会跟着解包临时目录一起被清掉。
"""

import os
import sys

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_FILE = os.path.join(APP_DIR, "todo_data.json")
CONF_FILE = os.path.join(APP_DIR, "todo_config.json")
