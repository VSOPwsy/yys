# yys_script — 阴阳师自动化框架

基于 MuMu 12 国服模拟器 + nemu IPC（DLL 截图 + 注入触摸）的游戏自动化框架。通过避开 ADB 通道降低被检测风险，支持多账号、多玩法热插拔、玩法之间共享图导航。

> **目标用户**：自己折腾、自己负责。本项目仅供学习研究，使用造成的封号 / 财产损失自负。

---

## 1. 环境要求

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 (64-bit) | nemu IPC 只在 Windows 上工作 |
| Python | 3.10 (Anaconda 推荐) | 项目代号 `yys` 的 conda 环境 |
| 模拟器 | MuMu 12 **国服版**（非 MuMuPlayerGlobal） | 国际版不支持 IPC |
| 游戏 | 阴阳师国服 | 已登录可玩状态 |
| 权限 | **管理员**（如果想启用 F9/F10/F12 全局热键） | 否则会自动降级 `noop` 后端 |

> **环境陷阱**（CLAUDE.md §7）：VSCode 默认 Python 解释器 ≠ `yys` 环境。本项目所有 `python` / `pytest` / `pip` 命令必须显式调 `D:\anaconda3\envs\yys\python.exe`。

---

## 2. 安装

```powershell
# 1. 克隆 + 创建 conda 环境
git clone <repo-url> yys_script
cd yys_script
conda create -n yys python=3.10 -y
conda activate yys

# 2. 装依赖
D:\anaconda3\envs\yys\python.exe -m pip install -r requirements.txt

# 3.（可选）装 OCR（每日奖励数量识别需要）
D:\anaconda3\envs\yys\python.exe -m pip install paddleocr==2.7.3

# 4.（可选）跑一次单测确认环境
D:\anaconda3\envs\yys\python.exe -m pytest tests/ -q
# 应该看到全部 245 项通过
```

如果遇到 `ModuleNotFoundError: No module named 'pkg_resources'`，把 `setuptools` 降到 `<81`：

```powershell
D:\anaconda3\envs\yys\python.exe -m pip install "setuptools<81"
```

---

## 3. 配置

入口配置文件：[`config/config.yaml`](config/config.yaml)。结构如下：

```yaml
global:               # 跨账号共享
  scheduler:          # 长跑策略：每日上限 / 休息周期 / 插件间隔
  humanize:           # 拟人化参数：jitter 半径 / 节流 / 延迟变化
  hotkeys:            # F9 暂停 / F10 停止 / F12 紧急退出

accounts:             # 即使只一个账号也用列表
  - id: main
    emulator:
      backend: nemu
      mumu_folder: D:/Program Files/Netease/MuMu  # MuMu 安装根
      instance_id: 0
    plugins:
      daily_reward:
        enabled: true
```

**关键字段**：

- `accounts[*].emulator.mumu_folder`：**MuMu 12 的安装根目录**（含 `shell/`、`nx_device/`、`vms/`），不是 `shell/` 子目录。详见 CLAUDE.md §7。
- `accounts[*].emulator.instance_id`：多开时每个实例不同（0 是第一个）。
- `global.humanize.click_jitter_radius`：点击坐标的随机扰动半径，单位像素。值越大越像真人但精度越低；默认 12 是"保守"档。
- `global.humanize.max_actions_per_minute`：每分钟最多操作数，超频自动等待。默认 60 ≈ 每秒最多一次操作。
- `global.scheduler.concurrent_plugins`：**默认 `false`**，每个账号同时只跑一个插件（Navigator 不是线程安全的）。需要先 audit 才能改 true。

**多账号扩展**只在 yaml 里加一个 `- id: alt1` 块即可。代码不动。

---

## 4. 跑起来

```powershell
# 默认配置
D:\anaconda3\envs\yys\python.exe main.py

# 指定配置文件
D:\anaconda3\envs\yys\python.exe main.py --config config/my_run.yaml

# 加日志级别
D:\anaconda3\envs\yys\python.exe main.py --log-level DEBUG
```

启动后控制台会列出已注册的热键。**正常状态下**：

- `F9`：暂停 / 恢复全部插件
- `F10`：停止全部插件（优雅，等当前操作结束）
- `F12`：紧急退出（best-effort 停止，然后 `os._exit(2)`）
- `Ctrl+C`：等同于 F10

**全局热键需要管理员权限**才能稳定 hook（Windows 限制）。普通用户跑也不会崩，但热键不会响应——会自动降级到 `noop` 后端。这时只能用 Ctrl+C 退出。

---

## 5. 添加一个新玩法（5 步）

参考实现：[`plugins/daily_reward/`](plugins/daily_reward/)（每日签到，完整带 README）。

1. **开分支**：
   ```powershell
   git checkout -b feature/my_plugin
   ```

2. **用 dev_tools 抠模板 + 录图**：
   ```powershell
   # 抠模板（识别锚点 + 按钮）
   D:\anaconda3\envs\yys\python.exe dev_tools/template_extractor.py --mumu "D:/Program Files/Netease/MuMu"
   # 录图（在真模拟器上点屏录 vertex/edge）
   D:\anaconda3\envs\yys\python.exe dev_tools/graph_composer.py --mumu "D:/Program Files/Netease/MuMu"
   # 校准识别（实时查看每个屏幕被识别成哪个 vertex）
   D:\anaconda3\envs\yys\python.exe dev_tools/screen_inspector.py --mumu "D:/Program Files/Netease/MuMu" --graph graphs.main:build_main_graph
   ```

3. **建插件目录结构**：
   ```
   plugins/my_plugin/
   ├── __init__.py        # re-export 类
   ├── buttons.py         # 所有 Button 定义
   ├── graph.py           # build_subgraph() 用 DSL 写子图
   ├── steps.py           # 业务步骤函数（接受 ctx 参数，便于测试）
   ├── plugin.py          # GameplayPlugin 子类
   └── README.md          # 写清依赖 / 模板清单 / 联调步骤
   ```

4. **在 graphs/main.py 加入口边**（如果需要从主界面进入插件）：
   ```python
   edge(
       "main_menu", external("my_plugin.entry_vertex"),
       action=click_button(MY_PLUGIN_ENTRY_BTN),
       cost=1.2,
   )
   ```

5. **在 config.yaml 启用插件 + 跑测试**：
   ```yaml
   accounts:
     - id: main
       plugins:
         my_plugin:
           enabled: true
   ```
   ```powershell
   # 写单测先验证 setup/run/teardown 流程不依赖真模拟器
   D:\anaconda3\envs\yys\python.exe -m pytest tests/test_my_plugin.py -v
   # 然后真机联调
   D:\anaconda3\envs\yys\python.exe main.py
   ```

详细的图组合规则（命名空间 / `external()` / `merge()` 行为）见 [`CLAUDE.md`](CLAUDE.md) §5 + §6。

---

## 6. 测试与调试

```powershell
# 全部单测
D:\anaconda3\envs\yys\python.exe -m pytest tests/ -q

# 单文件
D:\anaconda3\envs\yys\python.exe -m pytest tests/test_humanize.py -v

# 不带真模拟器的烟雾测试（验证 main.py 整体能起来 / 退出）
D:\anaconda3\envs\yys\python.exe main.py --config config/config.fake.yaml
```

**dev_tools** 都是 CLI，按需调用：

| 工具 | 用途 |
| --- | --- |
| `dev_tools/template_extractor.py` | 抠模板 PNG（按 S 截屏，框选，C 裁剪） |
| `dev_tools/vision_debug.py` | 在静态截图上调 Button.threshold / region |
| `dev_tools/graph_visualizer.py` | 用 matplotlib 画图，节点按 owner 着色 |
| `dev_tools/screen_inspector.py` | 实时识别：截图后叠加"当前是 XXX 顶点" |
| `dev_tools/graph_composer.py` | 交互式建图（录 vertex + edge），输出 Python 草稿 |

CLAUDE.md §6 末尾的 `dev_tools/` 一节有每个工具的键位详解。

---

## 7. 已知限制

- **MuMu 国际版（MuMuPlayerGlobal）不支持**：必须是国内版 MuMu 12。`NemuIpcBackend` 会拒绝路径含 "MuMuPlayerGlobal" 的配置。
- **`press_back()` 在 nemu IPC 上不可用**：DLL 只有触摸通道，没系统键。Plugin 里用 `click_button(BACK_BTN)` 代替。
- **OCR 是进程级单例 + 串行**：多账号同时跑 OCR 会排队。Phase 4 默认每账号同时只跑一个插件，所以暂不是瓶颈。
- **Plugin 必须自觉查 `should_stop()`**：纯 CPU 循环里至少每秒一次，blocking 操作前必查。否则 `stop()` 超时后线程会泄露（Python 不允许强杀线程）；F12 emergency exit 是这种情况下的最后兜底。
- **多账号 Navigator 并发**：同一账号 + `concurrent_plugins=true` 时，多个插件共享同一个 Navigator，**没有锁**。默认配置 `false` 避免这个问题；改 true 前请 audit 你的插件代码。

---

## 8. FAQ

**Q: 跑起来后游戏没反应，但脚本日志显示已经点击了？**
A: 大概率是模板没抠对 / 阈值太高匹配不到。用 `dev_tools/vision_debug.py` 调，把 threshold 降到 0.75 看看，或者用 `dev_tools/screen_inspector.py` 实时确认当前识别为哪个 vertex。

**Q: 跑了一会儿日志显示 `ERROR` 并附 traceback，然后插件 STOPPED 了？**
A: 这是 Phase 4 错误恢复机制：插件捕获到未预期异常时，先存截图到 `logs/<account>/error/<timestamp>_<plugin>.png` 留证，然后尝试最多 3 次 `goto("main_menu")`。如果都失败则插件进入 ERROR 状态，调度器移到下一个插件。打开那张 PNG 看看实际屏幕状态。

**Q: F9/F10/F12 不响应。**
A: Windows 上全局热键需要管理员权限。`HotkeyController` 会在没权限时自动降级到 `noop` 后端并 log 警告，主程序继续跑。要么以管理员身份起，要么用 Ctrl+C 退出。也可以在 config 把 `global.hotkeys.backend` 改成 `noop`，禁用热键以避免 warning。

**Q: 想跑 OCR 但 paddleocr 装不上 / 卡死？**
A: 项目默认惰性 import paddleocr，所以不装也能跑（只是 `read_reward_count` 会返回 None）。如果非要装，pip 直连 PyPI 比 conda 镜像更稳。`paddleocr==2.7.3` 是经过验证的版本。

**Q: 重新 vendor 了一份 alas，setuptools 装新版了，跑起来报错？**
A: Alas 的旧 adbutils 依赖 `pkg_resources`，setuptools 81+ 移除了这个模块。降到 80：`pip install "setuptools<81"`。

**Q: VSCode 一直提示 numpy / opencv-python 没装？**
A: VSCode 默认指向系统 Python310，不是 `yys` 环境。右下角点解释器，切到 `D:\anaconda3\envs\yys\python.exe`，或者忽略 IDE 提示，命令行用 `yys` python 即可。

---

## 9. 项目结构

```
yys_script/
├── core/                   # 生产代码核心层
│   ├── humanize.py         # Phase 4 拟人化工具（jitter, random_delay, weighted_path）
│   ├── config.py           # YAML 配置加载 + 校验
│   ├── exceptions.py       # 异常树根 BotError + 所有子类
│   ├── logging_config.py   # 彩色控制台 + 按天滚动文件
│   ├── input_backend/      # InputBackend 抽象 + NemuIpcBackend + Fake + 工厂
│   ├── vision/             # Button / 模板库 / 模板匹配 / OCR
│   ├── navigation/         # 图导航：DSL / 路径搜索 / 识别 / Navigator
│   ├── scheduler/          # 调度器 / Worker / Plugin 基类 / Throttle / LongRunPolicy
│   ├── hotkey/             # F9 / F10 / F12 控制器（含 keyboard / noop 后端)
│   └── cache/              # LRU + TTL；按字节预算的 CacheManager
├── graphs/                 # 主图（全局界面骨架）
│   ├── main.py             # 生产用 — main_menu / popup
│   ├── main_buttons.py     # 主图 Button 定义
│   ├── _demo.py            # Phase 2/3 演示用 fake-recognizer 主图
│   └── _demo_actions.py    # 演示用的 fake recognizer / action
├── plugins/                # 每个子目录 = 一个玩法
│   ├── _demo/              # Phase 3 演示插件
│   └── daily_reward/       # Phase 4 参考实现
├── templates/              # 模板 PNG（按玩法子目录隔离）
├── config/                 # 配置文件
│   ├── config.yaml         # 默认（生产）配置
│   └── config.fake.yaml    # 烟雾测试用（FakeBackend）
├── dev_tools/              # 开发工具（CLI，禁止被生产代码 import）
├── vendor/alas/            # Alas verbatim 子集，禁止手改（用 vendor_alas.py 重新生成）
├── tests/                  # 单元 / 集成测试（245 项）
├── logs/                   # 运行日志（按 account_id 子目录隔离）
├── main.py                 # 程序入口
├── CLAUDE.md               # 项目工作记忆（AI 助手用）
├── requirements.txt
└── README.md               # 本文件
```

`CLAUDE.md` 是给 AI 助手用的工作记忆 + 完整 API 参考。要扩功能 / debug 边界条件请优先翻它。
