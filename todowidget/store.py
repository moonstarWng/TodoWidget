# -*- coding: utf-8 -*-
"""清单数据: 多清单结构 + SQLite 存储

内存里仍然是一棵 dict 树(界面用起来方便), 每次保存整体写回数据库。
数据量是几百条级别, 整体重写完全无压力, 也省掉了各种增量同步的麻烦。
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime

from .paths import DATA_FILE, DB_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id           TEXT PRIMARY KEY,
    list_id      TEXT NOT NULL,
    parent_id    TEXT,
    text         TEXT NOT NULL DEFAULT '',
    done         INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    position     INTEGER NOT NULL DEFAULT 0,
    open         INTEGER NOT NULL DEFAULT 1,
    pinned       INTEGER NOT NULL DEFAULT 0,
    note_pinned  INTEGER NOT NULL DEFAULT 0,
    note_pos     TEXT,
    note_size    TEXT,
    created_at   TEXT,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_list ON items(list_id, parent_id, position);
"""


def now_str():
    """当前时间, 能用字符串直接排序的格式"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def day_of(value):
    """'2026-11-05 14:30:00' -> '2026-11-05'"""
    if not value:
        return ""
    return str(value)[:10]


def new_item(text):
    """新建一个任务节点"""
    return {"id": uuid.uuid4().hex[:8], "text": text, "done": False,
            "children": [], "open": True, "pinned": False,
            "created_at": now_str(), "completed_at": None}


class Store:
    """多份清单; 每份清单是 {id, name, items}"""

    def __init__(self, path=DB_FILE, import_json=True):
        self.path = path
        self.import_json = import_json
        self.lists = []
        self.current = ""
        self.conn = None
        self.load()

    # ---------------- 常用访问 ----------------
    @property
    def items(self):
        lst = self.current_list()
        if lst is None:
            return []
        return lst["items"]

    def current_list(self):
        for lst in self.lists:
            if lst["id"] == self.current:
                return lst
        if self.lists:
            return self.lists[0]
        return None

    def current_name(self):
        lst = self.current_list()
        if lst is None:
            return "待办"
        return lst["name"]

    def select(self, list_id):
        for lst in self.lists:
            if lst["id"] == list_id:
                self.current = list_id
                return True
        return False

    def add_list(self, name):
        clean = (name or "").strip() or "新清单"
        lst = {"id": uuid.uuid4().hex[:8], "name": clean, "items": []}
        self.lists.append(lst)
        self.current = lst["id"]
        return lst

    def rename_list(self, list_id, name):
        clean = (name or "").strip()
        if not clean:
            return False
        for lst in self.lists:
            if lst["id"] == list_id:
                lst["name"] = clean
                return True
        return False

    def delete_list(self, list_id):
        if len(self.lists) <= 1:
            return False
        left = []
        for lst in self.lists:
            if lst["id"] != list_id:
                left.append(lst)
        if len(left) == len(self.lists):
            return False
        self.lists = left
        if self.current == list_id:
            self.current = self.lists[0]["id"]
        return True

    def find_item(self, item_id):
        """按 id 在所有清单里找任务节点"""
        for lst in self.lists:
            for it, _ in walk(lst["items"]):
                if it["id"] == item_id:
                    return it
        return None

    # ---------------- 数据库 ----------------
    def connect(self):
        """打开(必要时建表)数据库"""
        if self.conn is not None:
            return self.conn
        folder = os.path.dirname(os.path.abspath(self.path))
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self._ensure_columns()
        self.conn.commit()
        return self.conn

    def _ensure_columns(self):
        """老库补字段(比如后来加的 pinned)"""
        try:
            exists = self.conn.execute(
                "PRAGMA table_info(items)").fetchall()
        except Exception:
            return
        names = [row[1] for row in exists]
        if "pinned" not in names:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "note_pinned" not in names:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN note_pinned INTEGER NOT NULL DEFAULT 0")
        if "note_pos" not in names:
            self.conn.execute("ALTER TABLE items ADD COLUMN note_pos TEXT")
        if "note_size" not in names:
            self.conn.execute("ALTER TABLE items ADD COLUMN note_size TEXT")

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def load(self):
        """优先读库; 没有库就看有没有老 JSON, 再没有就给一份示例"""
        had_db = os.path.exists(self.path)
        self.connect()

        rows = self.conn.execute(
            "SELECT id, name FROM lists ORDER BY position").fetchall()
        if rows:
            self._load_rows(rows)
            return

        if not had_db and self.import_json and os.path.exists(DATA_FILE):
            if self._import_json(DATA_FILE):
                self.save()
                return

        self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                       "items": seed_data()}]
        self.current = self.lists[0]["id"]
        self.save()

    def _load_rows(self, list_rows):
        self.lists = []
        items = self.conn.execute(
            "SELECT id, list_id, parent_id, text, done, note, position, open,"
            " created_at, completed_at, pinned, note_pinned, note_pos,"
            " note_size"
            " FROM items ORDER BY position, rowid").fetchall()

        by_id = {}
        roots = {}
        for list_id, name in list_rows:
            node = {"id": list_id, "name": name, "items": []}
            self.lists.append(node)
            roots[list_id] = node["items"]

        for row in items:
            (iid, list_id, parent_id, text, done, note, position, is_open,
             created_at, completed_at, pinned, note_pinned, note_pos,
             note_size) = row
            node = {"id": iid, "text": text or "", "done": bool(done),
                    "children": [], "open": bool(is_open),
                    "pinned": bool(pinned),
                    "note_pinned": bool(note_pinned),
                    "created_at": created_at or now_str(),
                    "completed_at": completed_at}
            if note_pos:
                node["note_pos"] = note_pos
            if note_size:
                node["note_size"] = note_size
            if note:
                node["note"] = note
            by_id[iid] = node
            bucket = roots.get(list_id)
            if bucket is None:
                continue
            bucket.append(node)

        # 第二遍挂父子关系
        for row in items:
            iid, list_id, parent_id = row[0], row[1], row[2]
            if not parent_id:
                continue
            node = by_id.get(iid)
            parent = by_id.get(parent_id)
            if node is None or parent is None:
                continue
            bucket = roots.get(list_id)
            if bucket is None:
                continue
            if node in bucket:
                bucket.remove(node)
            parent["children"].append(node)

        current = self.conn.execute(
            "SELECT value FROM meta WHERE key='current'").fetchone()
        self.current = current[0] if current else self.lists[0]["id"]
        if self.current_list() is None:
            self.current = self.lists[0]["id"]

    def save(self):
        if not self.lists:
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": []}]
            self.current = self.lists[0]["id"]
        if self.current_list() is None:
            self.current = self.lists[0]["id"]

        conn = self.connect()
        with conn:
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM lists")
            for pos, lst in enumerate(self.lists):
                conn.execute("INSERT INTO lists(id, name, position)"
                             " VALUES(?, ?, ?)", (lst["id"], lst["name"], pos))
                self._save_items(conn, lst["id"], None, lst["items"])
            conn.execute("INSERT OR REPLACE INTO meta(key, value)"
                         " VALUES('current', ?)", (self.current,))

    def _save_items(self, conn, list_id, parent_id, items):
        for pos, it in enumerate(items):
            conn.execute(
                "INSERT INTO items(id, list_id, parent_id, text, done, note,"
                " position, open, created_at, completed_at, pinned,"
                " note_pinned, note_pos, note_size)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (it["id"], list_id, parent_id, it.get("text") or "",
                 1 if it.get("done") else 0, it.get("note") or "",
                 pos, 1 if it.get("open", True) else 0,
                 it.get("created_at") or now_str(),
                 it.get("completed_at"),
                 1 if it.get("pinned") else 0,
                 1 if it.get("note_pinned") else 0,
                 it.get("note_pos") or "",
                 it.get("note_size") or ""))
            self._save_items(conn, list_id, it["id"],
                             it.get("children") or [])

    def _import_json(self, path):
        """把老版本 todo_data.json 导进来"""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        lists = data.get("lists")
        if not (isinstance(lists, list) and lists):
            old_items = data.get("items")
            if not isinstance(old_items, list):
                return False
            lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                      "items": old_items}]

        self.lists = []
        for lst in lists:
            items = lst.get("items") or []
            self.lists.append({"id": lst.get("id") or uuid.uuid4().hex[:8],
                               "name": lst.get("name") or "待办",
                               "items": self._upgrade_items(items)})
        self.current = data.get("current") or self.lists[0]["id"]
        if self.current_list() is None:
            self.current = self.lists[0]["id"]
        return True

    def _upgrade_items(self, items):
        """补上时间字段: 老数据创建时间记成现在, 已完成的完成时间也记成现在"""
        stamp = now_str()
        out = []
        for it in items:
            it.setdefault("created_at", stamp)
            if it.get("done") and not it.get("completed_at"):
                it["completed_at"] = stamp
            it["children"] = self._upgrade_items(it.get("children") or [])
            it.setdefault("open", True)
            it.setdefault("pinned", False)
            it.setdefault("note_pinned", False)
            out.append(it)
        return out


def seed_data():
    """首次启动时的示例清单"""
    src = [
        ("开始使用", ["点左边的框勾选", "双击任务写便签", "拖动行可以排序"]),
        ("这些也可以试试", ["左上角清单名: 切换 / 新建清单",
                          "右上角 ▾: 折叠成一条横杠", "右下角 ⚙: 换配色"]),
    ]
    out = []
    for title, kids in src:
        it = new_item(title)
        it["children"] = [new_item(k) for k in kids]
        out.append(it)
    return out


def walk(items, parent=None):
    """深度遍历, 产出 (item, 所在列表)"""
    for it in items:
        yield it, items
        yield from walk(it.get("children") or [])


def leaf_stats(item):
    done = total = 0
    for it, _ in walk([item]):
        if it is item:
            continue
        if not it.get("children"):
            total += 1
            done += 1 if it.get("done") else 0
    return done, total
