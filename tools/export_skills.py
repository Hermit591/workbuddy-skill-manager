# -*- coding: utf-8 -*-
"""从本机 WorkBuddy 数据库导出全部技能元数据 + SKILL.md 正文。

产物 data/skills_raw.json 是给你自己的 AI 阅读的原料：
把这份 JSON 连同 tools/build_meta.template.py 一起交给它，
让它按你的实际用途做分类和中文注解。
"""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# 优先读 config.json，其次环境变量，最后 WorkBuddy 默认 profile
try:
    with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
        CFG = json.load(f)
except (OSError, ValueError):
    CFG = {}

PROFILE = (CFG.get("profile") or os.environ.get("WORKBUDDY_PROFILE")
           or os.path.join(os.path.expanduser("~"), ".workbuddy"))
DB = (CFG.get("db") or os.environ.get("WORKBUDDY_DB")
      or os.path.join(PROFILE, "workbuddy.db"))

PREFERRED_COLUMNS = (
    "name", "file_path", "description", "description_zh", "description_en",
    "when_to_use", "disabled", "disable_model_invocation", "user_invocable",
    "tags_zh_json", "tags_en_json", "source", "license", "version",
)


def read_body(path):
    """读取 SKILL.md 正文，去掉 YAML frontmatter。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2]
        return text.strip()
    except OSError:
        return ""


def main():
    if not os.path.isfile(DB):
        raise SystemExit("找不到 WorkBuddy 数据库: %s（检查 config.json）" % DB)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    available = {r[1] for r in conn.execute("pragma table_info(local_skills)")}
    cols = [c for c in PREFERRED_COLUMNS if c in available]
    rows = conn.execute(
        "select %s from local_skills order by name" % ", ".join(cols)
    ).fetchall()
    conn.close()

    skills = []
    for row in rows:
        d = dict(row)
        d["body"] = read_body(d.get("file_path", ""))
        skills.append(d)

    os.makedirs(DATA, exist_ok=True)
    out = os.path.join(DATA, "skills_raw.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)
    print("已导出 %d 条技能 -> %s" % (len(skills), out))
    print("下一步：把这份 JSON 和 tools/build_meta.template.py 交给你的 AI。")


if __name__ == "__main__":
    main()
