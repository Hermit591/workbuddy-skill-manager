# -*- coding: utf-8 -*-
"""WorkBuddy Skill Manager · 本地服务（开源框架）

这是一个只面向 WorkBuddy 的技能开关控制台后端，零第三方依赖。

WorkBuddy 的技能开关真源不是 workbuddy.db 的 disabled 字段，而是
settings.json 里的 skillOverrides 字典：
  - override_key 不在字典里        -> 完全启用
  - 值为 "user-invocable-only"     -> 关闭（禁 AI 自动调用，允许手动）
  - 值为 "off"                     -> 彻底禁用（连手动也禁）
override_key 来自 workbuddy.db 的 local_skills.override_key 列。

本服务以 skillOverrides 为唯一开关真源，同时镜像写回 local_skills 的三个
字段做兼容。路径全部通过 config.json / 环境变量配置，不绑定任何个人机器。
"""

import json
import os
import re
import sqlite3
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")


def _load_config():
    """配置文件可选；缺省时用 WorkBuddy 默认 profile（~/.workbuddy）自动推导。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


CFG = _load_config()
PROFILE = (CFG.get("profile") or os.environ.get("WORKBUDDY_PROFILE")
           or os.path.join(os.path.expanduser("~"), ".workbuddy"))
DB = CFG.get("db") or os.environ.get("WORKBUDDY_DB") or os.path.join(PROFILE, "workbuddy.db")
SETTINGS = (CFG.get("settings") or os.environ.get("WORKBUDDY_SETTINGS")
            or os.path.join(PROFILE, "settings.json"))
META = os.path.join(BASE, "data", CFG.get("metaFile", "skills_meta.json"))
SCENES = os.path.join(BASE, "data", CFG.get("scenesFile", "scenes.json"))
BACKUP_DIR = os.path.join(BASE, "data", "backups")
ORIGINAL_OVERRIDES = os.path.join(BASE, "data", CFG.get("baselineFile", "settings_baseline.json"))
SCENE_STATE = os.path.join(BASE, "data", "scene_state.json")
PORT = int(os.environ.get("SKILLMGR_PORT", CFG.get("port", 17823)))

OV_OFF = "off"                    # 彻底禁用
OV_USER_ONLY = "user-invocable-only"  # 普通“关闭”：禁 AI 自动，保留手动

WRITE_LOCK = threading.Lock()
_LAST_BACKUP = 0.0

FIELDS = {"disabled", "disable_model_invocation", "user_invocable"}


def log(*a):
    print("[SkillMgr]", *a, flush=True)


def read_settings():
    with open(SETTINGS, "r", encoding="utf-8") as f:
        return json.load(f)


def write_settings(data):
    """原子写：先写临时文件再替换，避免中途崩溃写出半个 JSON 把 WorkBuddy 配置搞坏。"""
    tmp = SETTINGS + ".skillmgr.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SETTINGS)


def backup_settings():
    """写 settings.json 前留快照，保留最近 12 份。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    dst = os.path.join(BACKUP_DIR, "settings_%s.json" % ts)
    shutil.copy2(SETTINGS, dst)
    files = sorted((f for f in os.listdir(BACKUP_DIR)
                    if f.startswith("settings_") and f.endswith(".json")), reverse=True)
    for old in files[12:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    return dst


def get_overrides():
    """返回 {override_key: 覆盖值}，WorkBuddy 真正的开关状态。"""
    data = read_settings()
    ov = data.get("skillOverrides")
    return dict(ov) if isinstance(ov, dict) else {}


def load_scenes():
    with open(SCENES, "r", encoding="utf-8") as f:
        return json.load(f)


def baseline_overrides():
    """「恢复原状」的基准覆盖状态；基准文件不存在时返回空字典。"""
    try:
        with open(ORIGINAL_OVERRIDES, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_scene_state():
    """记录当前激活的场景 id（仅用于 UI 显示）。"""
    try:
        with open(SCENE_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"scene": None}


def save_scene_state(scene_id):
    with open(SCENE_STATE, "w", encoding="utf-8") as f:
        json.dump({"scene": scene_id, "at": datetime.now().isoformat()}, f,
                  ensure_ascii=False, indent=2)


def scene_category_map():
    """override_key -> category，从 meta 的 path + db 的 override_key 关联。"""
    meta = load_meta()
    cat_by_path = {s["path"]: s.get("category") for s in meta["skills"]}
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return {r["override_key"]: cat_by_path.get(r["file_path"])
                for r in conn.execute("select file_path, override_key from local_skills")
                if r["override_key"]}
    finally:
        conn.close()


def override_state(key, overrides=None):
    """把一个 override_key 转成前端三态：0=启用 1=用户手动可用(关) 2=彻底禁用。"""
    ov = (overrides if overrides is not None else get_overrides()).get(key)
    if ov == OV_OFF:
        return 2
    if ov == OV_USER_ONLY:
        return 1
    return 0


def backup_db(force=False):
    """用 SQLite 在线备份 API 做一致性快照，写操作前自动执行。"""
    global _LAST_BACKUP
    now = time.time()
    if not force and now - _LAST_BACKUP < 180 and os.listdir(BACKUP_DIR):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, "workbuddy_%s.db" % ts)
    src_conn = sqlite3.connect(DB)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    _LAST_BACKUP = now
    # 只保留最近 12 份
    files = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.startswith("workbuddy_") and f.endswith(".db")),
        reverse=True,
    )
    for old in files[12:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    log("已备份数据库 ->", dst)
    return dst


def load_meta():
    """分类元数据由使用者自己的 AI 生成（见 README / tools/build_meta.template.py）。"""
    if not os.path.isfile(META):
        return {"categories": [], "skills": []}
    with open(META, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_skills_from_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select file_path, name, override_key, disabled, disable_model_invocation, "
            "user_invocable, description, when_to_use from local_skills"
        ).fetchall()
        return {r["file_path"]: dict(r) for r in rows}
    finally:
        conn.close()


def build_payload():
    """合并静态元数据 + WorkBuddy 真实开关（settings.json skillOverrides）。"""
    meta = load_meta()
    dbrows = fetch_skills_from_db()
    overrides = get_overrides()
    skills = []
    for s in meta["skills"]:
        row = dbrows.get(s["path"])
        item = dict(s)
        if row:
            key = row.get("override_key")
            item["override_key"] = key
            # 开关真源：settings.json。disabled 只是兼容镜像，不再作为界面依据。
            st = override_state(key, overrides) if key else 0
            item["switch_state"] = st          # 0=启用 1=仅手动(页面显示为关) 2=彻底禁用
            item["disabled"] = 0 if st == 0 else 1
            item["disable_model_invocation"] = 1 if st != 0 else 0
            item["user_invocable"] = 0 if st == 2 else 1
            # 数据库里若有更新过的描述，以数据库为准（WorkBuddy 侧修改也能反映）
            if row.get("description"):
                item["description"] = row["description"]
            if row.get("when_to_use"):
                item["when_to_use"] = row["when_to_use"]
        else:
            item["switch_state"] = 0
            item["override_key"] = s.get("name", "")
        item["exists"] = bool(row)
        skills.append(item)
    return {"categories": meta["categories"], "skills": skills,
            "dbPath": DB, "settingsPath": SETTINGS, "total": len(skills),
            "activeScene": load_scene_state().get("scene")}


def _check_field_value(field, value):
    if field not in FIELDS:
        raise ValueError("非法字段: %s" % field)
    if value not in (0, 1):
        raise ValueError("value 只能是 0 或 1")


def path_to_key_map():
    """file_path -> override_key，从 db 读出。"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return {r["file_path"]: r["override_key"] for r in
                conn.execute("select file_path, override_key from local_skills")
                if r["override_key"]}
    finally:
        conn.close()


def apply_overrides(key_values):
    """真正生效的写操作：改 settings.json 的 skillOverrides + 镜像改 db。

    key_values: [(override_key, 新的覆盖值 or None)]
    覆盖值为 None 表示删除该键 = 完全启用。
    """
    key_values = [(k, v) for k, v in key_values if k]
    if not key_values:
        return 0
    with WRITE_LOCK:
        backup_settings()
        data = read_settings()
        ov = data.get("skillOverrides")
        if not isinstance(ov, dict):
            ov = {}
        for k, v in key_values:
            if v is None:
                ov.pop(k, None)
            else:
                ov[k] = v
        data["skillOverrides"] = ov
        write_settings(data)

        # 镜像同步数据库字段，保持与其他工具兼容（不再作为开关真源）
        conn = sqlite3.connect(DB, timeout=15)
        try:
            for k, v in key_values:
                if v is None:
                    disabled, dmi, ui = 0, 0, 1
                elif v == OV_OFF:
                    disabled, dmi, ui = 1, 1, 0
                else:  # user-invocable-only
                    disabled, dmi, ui = 1, 1, 1
                conn.execute(
                    "update local_skills set disabled=?, disable_model_invocation=?, "
                    "user_invocable=? where override_key=?", (disabled, dmi, ui, k))
            conn.commit()
        finally:
            conn.close()
    log("已写 skillOverrides %d 项" % len(key_values))
    return len(key_values)


def update_field(path, field, value):
    """单技能开关切换。前端传的是 disabled 语义（0=开,1=关）。"""
    _check_field_value(field, value)
    pm = path_to_key_map()
    key = pm.get(path)
    if not key:
        raise ValueError("技能缺少 override_key: %s" % path)

    if field == "disabled":
        # 关闭时保留用户原来的覆盖值（如 off），开启时删除覆盖键
        if value == 0:
            apply_overrides([(key, None)])
        else:
            # 若当前已是 off（彻底禁用），维持 off；否则写 user-invocable-only
            cur = override_state(key)
            apply_overrides([(key, OV_OFF if cur == 2 else OV_USER_ONLY)])
    elif field == "disable_model_invocation":
        # 1 = 禁止 AI 调用 -> user-invocable-only / off；0 = 允许 -> 删除
        if value == 0:
            cur = override_state(key)
            # 彻底禁用态保持 off（手动也禁），否则解为完全启用
            if cur == 2:
                apply_overrides([(key, OV_OFF)])  # 保持
            else:
                apply_overrides([(key, None)])
        else:
            cur = override_state(key)
            apply_overrides([(key, OV_OFF if cur == 2 else OV_USER_ONLY)])
    elif field == "user_invocable":
        # 0 = 禁止手动 -> off；1 = 允许手动 -> 若当前彻底禁用则升为 user-invocable-only
        if value == 0:
            apply_overrides([(key, OV_OFF)])
        else:
            cur = override_state(key)
            if cur == 2:
                apply_overrides([(key, OV_USER_ONLY)])
            else:
                apply_overrides([])  # 无需改动
    return {"ok": True, "path": path, "field": field, "value": value,
            "switch_state": override_state(key)}


def apply_scene(scene_id):
    """应用场景：keep 内的分类全部启用，keep 外的分类全部关闭。

    scene_id == "all" = 全开（清空所有覆盖）。
    场景是临时工作状态；「恢复原状」用于回到 baseline 覆盖状态。
    """
    scenes = load_scenes()
    scene = next((sc for sc in scenes.get("scenes", []) if sc["id"] == scene_id), None)
    if not scene and scene_id != "all":
        raise ValueError("未知场景: %s" % scene_id)

    if scene_id == "all":
        # 全开 = 清空所有覆盖，AI 可用全部技能
        pairs = [(k, None) for k in get_overrides()]
        apply_overrides(pairs)
        save_scene_state("all")
        return {"ok": True, "scene": "all", "name": "全部启用",
                "closed": 0, "kept": 0}

    keep = set(scene.get("keep") or [])
    base = baseline_overrides()
    k2cat = scene_category_map()

    # 构造目标覆盖：keep 内全部启用（删除覆盖），keep 外强制关闭。
    # 场景是临时工作状态，不在场景里保留用户的手动关闭——那是「恢复原状」按钮的职责。
    target = {}
    for key, cat in k2cat.items():
        if cat not in keep:
            target[key] = OV_USER_ONLY

    # 一次性写入：先清掉所有当前覆盖，再写目标
    pairs = [(k, None) for k in get_overrides()]
    pairs += [(k, v) for k, v in target.items()]
    apply_overrides(pairs)
    save_scene_state(scene_id)

    closed = sum(1 for k, cat in k2cat.items() if cat not in keep)
    kept = sum(1 for k, cat in k2cat.items() if cat in keep)
    log("应用场景 %s: 保留 %d, 关闭 %d" % (scene["name"], kept, closed))
    return {"ok": True, "scene": scene_id, "name": scene["name"],
            "closed": closed, "kept": kept,
            "keepCategories": scene.get("keep", [])}


def update_scope(scope, field, value, category=None, paths=None, mode=None):
    """范围批量开关：all 全库 / category 某分类 / paths 指定列表。

    mode: 'normal' 普通关闭(user-invocable-only) / 'full' 彻底禁用(off)
    """
    _check_field_value(field, value)
    paths = list(paths or [])
    if scope == "category":
        if not category:
            raise ValueError("缺少分类 id")
        paths = [s["path"] for s in load_meta()["skills"] if s.get("category") == category]
    elif scope == "paths":
        if not paths:
            raise ValueError("未选择任何技能")
    elif scope != "all":
        raise ValueError("非法范围: %s" % scope)

    pm = path_to_key_map()
    if scope == "all":
        keys = list(pm.values())
    else:
        keys = [pm[p] for p in paths if p in pm]

    close_value = OV_OFF if mode == "full" else OV_USER_ONLY
    if value == 0:  # 启用 = 删除覆盖键
        pairs = [(k, None) for k in keys]
    else:           # 关闭 = 写入覆盖值
        pairs = [(k, close_value) for k in keys]
    count = apply_overrides(pairs)
    log("批量开关: scope=%s field=%s value=%s mode=%s 影响=%d" %
        (scope, field, value, mode, count))
    return {"ok": True, "scope": scope, "category": category,
            "field": field, "value": value, "mode": mode, "count": count}


class Handler(BaseHTTPRequestHandler):
    server_version = "SkillManager/1.0"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name):
        # 只允许读取本目录下白名单文件，防目录穿越
        allowed = {"index.html": "text/html; charset=utf-8",
                   "app.js": "application/javascript; charset=utf-8",
                   "style.css": "text/css; charset=utf-8"}
        if name not in allowed:
            self._send(404, {"error": "not found"})
            return
        path = os.path.join(BASE, name)
        if not os.path.isfile(path):
            self._send(404, {"error": "missing " + name})
            return
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, allowed[name])

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        try:
            if path == "/" or path == "/index.html":
                return self._static("index.html")
            if path in ("/app.js", "/style.css"):
                return self._static(path.lstrip("/"))
            if path == "/api/skills":
                payload = build_payload()
                # 列表不返回正文（正文可能达数 KB/条），详情页按需单独取
                for s in payload["skills"]:
                    s.pop("body", None)
                return self._send(200, payload)
            if path == "/api/skill":
                # 用 path 定位（name 可能重名）
                qs = parse_qs(u.query)
                target = qs.get("path", [""])[0]
                payload = build_payload()
                for s in payload["skills"]:
                    if s["path"] == target:
                        return self._send(200, s)
                return self._send(404, {"error": "技能不存在"})
            if path == "/api/scenes":
                return self._send(200, {"scenes": load_scenes()["scenes"],
                                        "active": load_scene_state().get("scene")})
            if path == "/api/health":
                return self._send(200, {"ok": True, "db": DB, "settings": SETTINGS,
                                        "overrideCount": len(get_overrides()),
                                        "metaMtime": os.path.getmtime(META),
                                        "time": datetime.now().isoformat()})
            if path == "/api/backup":
                dst = backup_db(force=True)
                return self._send(200, {"ok": True, "file": os.path.basename(dst) if dst else None})
            if path == "/api/backups":
                files = sorted(
                    (f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")), reverse=True
                )[:12]
                return self._send(200, {"files": files})
            self._send(404, {"error": "not found"})
        except Exception as e:
            log("GET error:", repr(e))
            self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if path == "/api/toggle":
                r = update_field(
                    payload.get("path", ""), payload.get("field", "disabled"),
                    int(payload.get("value", 0)))
                if load_scene_state().get("scene"):
                    save_scene_state(None)
                return self._send(200, r)
            if path == "/api/toggle-batch":
                r = update_scope(
                    payload.get("scope", "paths"),
                    payload.get("field", "disabled"),
                    int(payload.get("value", 0)),
                    category=payload.get("category"),
                    paths=payload.get("paths", []),
                    mode=payload.get("mode", "normal"),
                )
                # 手动改开关后不再是纯场景状态
                if load_scene_state().get("scene"):
                    save_scene_state(None)
                return self._send(200, r)
            if path == "/api/scene-apply":
                return self._send(200, apply_scene(payload.get("scene", "")))
            if path == "/api/scene-baseline":
                # 恢复到基准覆盖状态
                base = baseline_overrides()
                pairs = [(k, None) for k in get_overrides()]
                pairs += [(k, v) for k, v in base.items()]
                apply_overrides(pairs)
                save_scene_state(None)
                return self._send(200, {"ok": True, "count": len(base)})
            if path == "/api/reset-db-mirror":
                # 按 settings.json 真源重新镜像数据库的 disabled 等字段
                data = read_settings()
                ov = data.get("skillOverrides", {})
                conn = sqlite3.connect(DB, timeout=15)
                try:
                    rows = conn.execute(
                        "select override_key, disabled, disable_model_invocation, "
                        "user_invocable from local_skills").fetchall()
                    fixed = 0
                    for key, dis, dmi, ui in rows:
                        st = override_state(key, ov)
                        want = (0, 0, 1) if st == 0 else (
                            (1, 1, 0) if st == 2 else (1, 1, 1))
                        if (dis, dmi, ui) != want:
                            conn.execute(
                                "update local_skills set disabled=?, "
                                "disable_model_invocation=?, user_invocable=? "
                                "where override_key=?", want + (key,))
                            fixed += 1
                    conn.commit()
                finally:
                    conn.close()
                return self._send(200, {"ok": True, "fixed": fixed})
            if path == "/api/refresh-meta":
                # 重新从 SKILL.md 与数据库导出并重建分类元数据
                import subprocess
                py = sys.executable
                r1 = subprocess.run([py, os.path.join(BASE, "tools", "export_skills.py")],
                                    capture_output=True, text=True, timeout=120)
                r2 = subprocess.run([py, os.path.join(BASE, "tools", "build_meta.py")],
                                    capture_output=True, text=True, timeout=120)
                return self._send(200, {"ok": True,
                                        "export": r1.stdout[-500:], "build": r2.stdout[-500:],
                                        "errors": (r1.stderr + r2.stderr)[-500:]})
            self._send(404, {"error": "not found"})
        except Exception as e:
            log("POST error:", repr(e))
            self._send(400, {"error": str(e)})

    def log_message(self, fmt, *args):
        pass  # 静默访问日志，避免刷屏


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not os.path.isfile(META):
        log("提示: 尚未生成 skills_meta.json，请把 README 里的数据结构交给你的 AI 生成。")
    if not os.path.isfile(SETTINGS) or not os.path.isfile(DB):
        log("错误: 找不到 WorkBuddy 的 settings.json / workbuddy.db，请检查 config.json。")
        sys.exit(1)
    fetch_skills_from_db()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://127.0.0.1:%d/" % PORT
    log("服务已启动:", url)
    log("数据库:", DB)
    log("开关真源:", SETTINGS, "skillOverrides 当前", len(get_overrides()), "项")
    log("按 Ctrl+C 退出")
    try:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        srv.serve_forever()
    except KeyboardInterrupt:
        log("已退出")
        srv.shutdown()


if __name__ == "__main__":
    main()
