# WorkBuddy Skill Manager

> 一个本地运行的 WorkBuddy 技能开关控制台。**WorkBuddy 专用**，其他 Agent 无法直接使用。
> 本仓库只提供框架，不预置任何技能清单、分类或中文注解——那些由你自己的 AI 搭建。

## 这是什么

一个零第三方依赖的本地小工具：Python 标准库写后端，原生 HTML/CSS/JS 做界面，双击 `.bat` 就能跑。它直接读写 WorkBuddy 的技能开关配置，所以在页面上切开关，WorkBuddy 那边就是真的切了。

## 能实现什么

- **真实开关同步**：单个技能开/关，与 WorkBuddy 界面状态完全一致（不是做样子的影子字段）
- **两种关闭强度**：普通关闭（禁 AI 自动调用、保留手动）和彻底禁用（手动也禁用），对齐 WorkBuddy 自己的语义
- **一键全开 / 全关**、**按分类批量启停**
- **场景模式**：点一下只保留指定分类、其他全关。WorkBuddy 会把所有启用技能的名字+描述塞进每轮对话的 `<available_skills>`，关掉用不到的整类技能能显著省 token
- **搜索、详情抽屉**：看技能说明、使用时机、`SKILL.md` 原文、源文件路径、覆盖键
- **自动备份**：每次改开关前备份 `settings.json`，数据库备份也支持，保留最近 12 份
- **本地监听**：只绑定 `127.0.0.1`，不对外暴露

## 为什么别的 Agent 用不了

这套代码读写的是 **WorkBuddy 独有的内部数据结构**，不是通用技能协议：

| 依赖 | WorkBuddy 里的位置 / 含义 |
|---|---|
| `workbuddy.db` → `local_skills` 表 | 技能记录，其中 `override_key` 列是开关的索引键 |
| `settings.json` → `skillOverrides` 字典 | **开关真源**：键不存在=启用；`user-invocable-only`=普通关闭；`off`=彻底禁用 |
| `SKILL.md` frontmatter | WorkBuddy 的 `description` / `when_to_use` 等字段 |

WorkBuddy 的开关**不读**数据库的 `disabled` 字段——这一点是从它的 `toggleSkill` 实现里溯源确认的。

Claude Code、Cursor、Cline、OpenClaw 等其他 Agent 各自用 `.claude/skills/`、`AGENTS.md`、MCP 或完全不同的配置体系，既没有 `local_skills.override_key`，也没有 `skillOverrides` 字典。把本仓库直接搬过去不会生效；要支持别的 Agent，需要自己重写 `server.py` 里的 `apply_overrides()` 写入层。

## 本仓库刻意不包含什么

**只打包框架。** 以下内容都没有预置，请让你自己的 AI 生成：

- ❌ 任何真实技能清单
- ❌ 任何分类体系（比如"PPT 类""逆向类"这种划分）
- ❌ 任何中文注解、翻译规则
- ❌ 任何个人路径、机器名、账号、场景配置

原因很实际：分类和注解取决于你机器上装了什么技能、你干什么活。别人替你猜的结论往往不准，而你的 AI 看过你自己的 `skills_raw.json` 之后能写得贴切得多。

## 快速开始

### 1. 环境

- Python 3.8+
- WorkBuddy（当然）

### 2. 配置（通常不用改）

```bash
cp config.example.json config.json
```

不填任何路径时，程序自动读取用户主目录下的 `~/.workbuddy/workbuddy.db` 和 `settings.json`。
如果你的 profile 在别处，填 `profile` 为绝对路径；也可以分别指定 `db`、`settings`。
端口改 `port`，或设环境变量 `SKILLMGR_PORT`。

### 3. 启动

双击 `启动技能管家.bat`，或：

```bash
python server.py
```

浏览器自动打开 `http://127.0.0.1:17823/`。

首次启动时 `data/skills_meta.json` 还不存在，页面会是空的——先做下一步。

## 让你自己的 AI 搭建分类（核心步骤）

1. **导出原料**

   ```bash
   python tools/export_skills.py
   ```

   生成 `data/skills_raw.json`：你机器上全部技能的名字、描述、使用时机、`SKILL.md` 正文。

2. **把这两个文件交给你的 AI**

   - `data/skills_raw.json`
   - `tools/build_meta.template.py`

   让它按你的实际用途：
   - 设计 `CATEGORIES`（分类 id / 名称 / 图标 / 颜色 / 说明）
   - 填满 `CATEGORY_OVERRIDE` 和 `CN_TABLE`，给每条技能写中文一句话说明
   - 补全 `classify()` 和 `cn_summary()`
   - 另存为 `tools/build_meta.py`

   模板里每个 TODO 都标了位置。

3. **生成元数据**

   ```bash
   python tools/build_meta.py
   ```

   得到 `data/skills_meta.json`，页面立刻有内容。

4. **场景（可选）**

   复制 `data/scenes.example.json` 为 `data/scenes.json`，让你的 AI 按分类 id 填 `keep` 列表：
   `keep` 里的分类全部启用，其余全部关闭。

5. **恢复原状基准（可选）**

   把当前 `settings.json` 里的 `skillOverrides` 字典原样存成 `data/settings_baseline.json`，
   页面上的「恢复原状」按钮就会回到这份状态。没有该文件时按钮会清空所有覆盖。

6. 回到页面点「刷新状态」。

以后装了新技能，重跑 `python tools/export_skills.py` → 让你的 AI 更新 `build_meta.py` → 再跑一次构建即可。

## 配置兜底与环境变量

| 配置项 | 环境变量 | 缺省 |
|---|---|---|
| `profile` | `WORKBUDDY_PROFILE` | `~/.workbuddy` |
| `db` | `WORKBUDDY_DB` | `<profile>/workbuddy.db` |
| `settings` | `WORKBUDDY_SETTINGS` | `<profile>/settings.json` |
| `port` | `SKILLMGR_PORT` | `17823` |

## 开关机制（给想改代码的人）

`server.py` 的 `apply_overrides(key_values)` 是唯一的写入口：

```
[(override_key, None)]                  -> 删除覆盖键 = 完全启用
[(override_key, "user-invocable-only")] -> 普通关闭
[(override_key, "off")]                 -> 彻底禁用
```

写 `settings.json` 用临时文件 + `os.replace` 原子替换，避免崩溃时写出半个 JSON。
数据库三个字段跟着镜像写，仅为兼容，界面不读它们。

批量修改还会顺带清掉 WorkBuddy 的技能清单缓存标记；如果界面没立刻刷新，重启一次 WorkBuddy 即可。

## 主要 API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/skills` | 技能列表（含实时开关状态，不含正文） |
| GET | `/api/skill?path=...` | 单条详情（含 `SKILL.md` 正文） |
| GET | `/api/scenes` | 场景列表 |
| GET | `/api/health` | 健康检查、当前配置路径、覆盖数量 |
| POST | `/api/toggle` | 单条开关 |
| POST | `/api/toggle-batch` | 批量开关（`scope`: all / category / paths） |
| POST | `/api/scene-apply` | 应用场景，`scene: "all"` 为全开 |
| POST | `/api/scene-baseline` | 恢复基准状态 |
| POST | `/api/backup` | 备份（GET `/api/backups` 查看列表） |

## 许可

MIT
