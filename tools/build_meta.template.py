# -*- coding: utf-8 -*-
"""分类与中文注解生成器 · 模板（框架不预置任何分类）

用法：
  1. 先运行 tools/export_skills.py 生成 data/skills_raw.json
  2. 把 skills_raw.json 和本文件一起交给**你自己的 AI**，让它：
       - 按你的实际用途设计 CATEGORIES
       - 给每条技能写中文一句话说明（CN_TABLE）
       - 补全 classify() / cn_summary() 的规则
  3. 把 AI 填好的结果另存为 tools/build_meta.py
  4. 运行 python tools/build_meta.py -> 生成 data/skills_meta.json

本框架刻意不含任何分类体系、中文注解或技能清单：
这些结论取决于你机器上装了什么技能、你平时怎么干活，
只有你自己的 AI 看过 skills_raw.json 之后才写得准。
"""
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "skills_raw.json")
OUT = os.path.join(BASE, "data", "skills_meta.json")

# TODO(你的 AI): 按实际技能重新设计分类。id 用英文短横线，icon 用一个字符。
CATEGORIES = [
    {"id": "example-a", "name": "示例分类 A", "icon": "◆", "color": "#3b5bdb",
     "desc": "由你的 AI 按实际用途编写"},
]

# TODO(你的 AI): 精确命中的特例，name(小写) -> category id
CATEGORY_OVERRIDE = {
    # "some-skill-name": "example-a",
}

# TODO(你的 AI): name(小写) -> 中文一句话说明。优先级高于自动摘要。
CN_TABLE = {
    # "some-skill-name": "用一句话讲清楚这个技能是干什么、什么时候用",
}


def classify(name, desc):
    """把一条技能映射到某个分类 id。让 AI 按实际技能名/描述补规则。"""
    n = (name or "").lower()
    d = desc or ""
    if n in CATEGORY_OVERRIDE:
        return CATEGORY_OVERRIDE[n]
    # TODO(你的 AI): 关键词/正则规则；兜底统一返回 'other'（若你定义了该分类）
    return "example-a"


def cn_summary(name, desc, when):
    """生成列表页显示的中文一句话说明。"""
    n = (name or "").lower()
    if n in CN_TABLE:
        return CN_TABLE[n]
    text = (desc or "").strip() or (when or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:96] + ("…" if len(text) > 96 else "") if text else "（暂无说明，点开详情看原文）"


def main():
    if not os.path.isfile(RAW):
        raise SystemExit("缺少 data/skills_raw.json，请先运行 tools/export_skills.py")
    with open(RAW, "r", encoding="utf-8") as f:
        raw = json.load(f)

    skills = []
    for x in raw:
        name = x.get("name", "")
        desc = x.get("description") or ""
        skills.append({
            "name": name,
            "path": x.get("file_path", ""),
            "category": classify(name, desc),
            "summary": cn_summary(name, desc, x.get("when_to_use") or ""),
            "description": desc,
            "when_to_use": x.get("when_to_use") or "",
            "body": x.get("body", ""),
            "source": x.get("source", ""),
            "license": x.get("license") or "",
        })

    meta = {"categories": CATEGORIES, "skills": skills}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    from collections import Counter
    cnt = Counter(s["category"] for s in skills)
    print("已生成 %s（%d 条技能）" % (OUT, len(skills)))
    for c in CATEGORIES:
        print("  %-16s %3d" % (c["name"], cnt.get(c["id"], 0)))
    unknown = [s["name"] for s in skills if s["category"] not in {c["id"] for c in CATEGORIES}]
    if unknown:
        print("未归类(%d): %s" % (len(unknown), ", ".join(unknown[:30])))


if __name__ == "__main__":
    main()
