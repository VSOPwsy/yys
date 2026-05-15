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
- `global.humanize.click_jitter_radius`：**主开关 + raw (x, y) 抖动半径**。`0` / `null` 关闭全部拟人化（Button 落点 = match 中心）。正值：raw `click_xy` 走 disk-uniform 抖动；**Button 点击不再被这个值封顶**——Button 落点由下面的 `bbox_margin` 决定。默认 `12`。
- `global.humanize.bbox_margin`：**Button bbox 采样收紧比例**，必须 `[0, 0.5)`。`0.0` = 整个 bbox 都可能（含边缘像素）。`0.1`（默认）= 内 80%（边缘 5% 不采）。`0.3` = 内 40%（大 banner / panel 想收紧时用）。2 px 像素硬下限永远生效，保护小模板。
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

2.4. **模板目录组织规则**（抠的时候 `template_extractor.py` 会问你保存路径，按这套规则填）：

   核心原则：**模板归属看「这个图像识别的是什么」，不看「从哪里点进去」**。`templates/` 的子目录都是**顶层平级**（每个游戏场景一个），不嵌套。

   | 模板类型 | 归属规则 | 例子 |
   | --- | --- | --- |
   | **场景锚点** (`*_anchor`) | 模板放进**它识别的那个场景**的文件夹 | `templates/shishenlu/shishenlu_anchor.png`（"在式神录"的标志） |
   | **进入按钮** (`*_entry_btn`) | 模板放进**按钮视觉上所在的场景**文件夹 | `templates/tingyuan/shishenlu_entry_btn.png`（庭院折叠面板里那枚式神录入口按钮，虽然指向式神录但视觉上是庭院的） |
   | **场景内部的功能按钮** | 与该场景的锚点同一文件夹 | `templates/shishenlu/some_filter_btn.png` |
   | **跨场景通用按钮**（暂时挂在某场景下做归属） | 放在最常出现的场景里 | `templates/tingyuan/close_popup_btn.png`、`templates/tingyuan/home_return_btn.png` |

   推荐布局：
   ```
   templates/
   ├── tingyuan/                          # 庭院（家）的元素
   │   ├── tingyuan_anchor.png            #   ← "在庭院"的脸
   │   ├── tingyuanshiwu_entry_btn.png    #   ← 庭院里指向庭院事务的按钮
   │   ├── shishenlu_entry_btn.png        #   ← 庭院折叠面板里指向式神录的按钮
   │   ├── close_popup_btn.png            #   ← 通用关闭按钮（挂在 tingyuan 下）
   │   └── home_return_btn.png            #   ← 通用回主界面（挂在 tingyuan 下）
   ├── shishenlu/                         # 式神录的元素
   │   └── shishenlu_anchor.png           #   ← "在式神录"的脸
   ├── tingyuanshiwu/                     # 庭院事务的元素（独立场景，**平级**不嵌套）
   │   └── tingyuanshiwu_anchor.png
   ├── daily_reward/                      # 每日签到 plugin 的元素
   │   └── ...
   └── battle/                            # 假如战斗界面将来也有式神录入口
       └── shishenlu_entry_btn.png        #   ← 同名按钮、不同视觉，不冲突
   ```

   **多入口场景**：如果式神录将来从战斗界面也能进，战斗界面里的入口按钮就放 `templates/battle/shishenlu_entry_btn.png`，**和 `tingyuan/` 下那枚同名但路径不同、互不冲突**。把多个入口按钮都塞进 `templates/shishenlu/` 反而要起 `entry_from_tingyuan.png` / `entry_from_battle.png` 这种命名负担。

   **文件名是否带场景前缀**：框架不关心。倾向于"读 PNG 文件名能脱离上下文一眼看懂用途"：通用词如 `anchor` / `entry_btn` 容易冲撞，建议带前缀（`shishenlu_anchor.png`）；已经具体的词如 `already_claimed_anchor` / `claim_today_btn` 不重复也行。和 `Button.simple(...)` 里的逻辑名一一对应即可。

   **`Button.simple(template, ...)` 里的字符串**：相对 `templates/` 的逻辑路径，**不带 `.png`**。例：
   ```python
   SHISHENLU_ANCHOR = Button.simple("shishenlu/shishenlu_anchor", ...)
   SHISHENLU_ENTRY_BTN = Button.simple("tingyuan/shishenlu_entry_btn", ...)
   ```

   **何时新建一个 `templates/<scene>/` 文件夹**：当某个场景有了自己的锚点（成为 graph 里的一个 vertex），就给它开文件夹。在那之前如果只是别处的一枚"指向它的入口按钮"，按钮先寄存在按钮所在的场景文件夹里。

2.5. **验证每个 Button 的模板质量**（每抠一张就跑一次，能省后面 80% 的 debug 时间）：

   `dev_tools/button_inspector.py` 直接从生产代码加载 [Button](core/vision/button.py) 对象——用的就是你写在 `buttons.py` / `main_buttons.py` 里的 `threshold`、`region`、`click_offset`，所见即所跑。

   ```powershell
   # 从生产代码加载（推荐，沿用真实参数）
   D:\anaconda3\envs\yys\python.exe dev_tools/button_inspector.py --mumu "D:/Program Files/Netease/MuMu" --button graphs.main_buttons:SIGN_IN_ENTRY_BTN

   # 临时验证还没写进代码的模板
   D:\anaconda3\envs\yys\python.exe dev_tools/button_inspector.py --mumu "D:/Program Files/Netease/MuMu" --template main/sign_in_entry_btn
   ```

   **键位**：`R` 刷新截图、`A` 切换 best-only / 全部匹配、`+/-` 实时调阈值 ±0.02、`I` 刷新模板缓存（重抠后用）、`S` 保存带标注的画面到 `dev_tools/button_inspector_out/`、`Q`/`Esc` 退出。

   **底部一句话判定**：

   | 横幅 | 含义 | 处置 |
   | --- | --- | --- |
   | **PASS** 绿 | 1 个匹配，分数比阈值高出 ≥ 0.05 | 这个模板可以用 |
   | **MARGINAL** 黄 | 1 个匹配但 headroom < 0.05 | 边缘——光照 / 动画变一帧就会失败。重抠更稳的特征 |
   | **AMBIGUOUS** 橙 | ≥ 2 个匹配（按 `A` 查看每一个） | 模板太通用。加 `region=` 限定，或重抠包含独特元素的更大区域 |
   | **FAIL** 红 | 0 个匹配 | 阈值太严 / 当前帧没这按钮 / 模板抠错。按 `-` 看真实最高分能到多少 |

   **可视化元素**：绿色框 + 红十字 = 匹配位置和**实际点击落点**（已应用 `click_offset`），红十字应该正好落在按钮可点击区域中心。蓝色框 = `Button.region` 限定的搜索范围。每个匹配旁的数字 = 原始 `cv2.matchTemplate` 评分。

   **典型工作流**：
   1. 在 [template_extractor.py](dev_tools/template_extractor.py) 里抠 + 存 → 不退出
   2. 切到 button_inspector 窗口，按 `I` 让它重新读盘上的 PNG → 按 `R` 刷新当前截图 → 看判定
   3. 如果是 MARGINAL / AMBIGUOUS / FAIL → 回 extractor 重新框 → 重复 2
   4. PASS 之后**切到其他界面再按 `R`**，确认这个按钮在不该出现的地方**不会**误匹配（看到红色 FAIL 反而是好结果）

2.6. **注册 Button + vertex 进 graph，然后用 screen_inspector 验证识别**：

   `button_inspector` 只验证"单张 PNG 在当前帧匹配质量"，**不验证**"这个 anchor 作为某个 vertex 的 recognizer 能否被识别器正确推断出来"。后者必须先把 anchor 接入 graph。

   假设你刚抠了 `templates/main/tingyuanshiwu/tingyuanshiwu_anchor.png`：

   **(a)** 在 [graphs/main_buttons.py](graphs/main_buttons.py)（根命名空间）或 `plugins/<name>/buttons.py`（插件命名空间）里加一条：
   ```python
   TINGYUAN_AFFAIRS_ANCHOR = Button.simple(
       "main/tingyuanshiwu/tingyuanshiwu_anchor",   # 不带 .png 后缀
       name="庭院事务锚点",
       threshold=0.85,
   )
   ```
   别忘了 export 到 `__all__`。

   **(b)** 在对应的 graph builder 里注册 vertex。根命名空间的界面写进 [graphs/main.py](graphs/main.py) 的 `build_main_graph()`：
   ```python
   vertex(
       "tingyuan_affairs",
       name="庭院事务",
       recognizer=TINGYUAN_AFFAIRS_ANCHOR,
       dwell_time=500,
   )
   ```
   插件相关的界面写进 `plugins/<name>/graph.py` 的 `build_subgraph()`，bare name 会自动加 `<name>.` 前缀。

   **(c)** 验证 —— `--graph` 参数**不用改**，它指向的就是你刚编辑的那个 builder 函数：
   ```powershell
   D:\anaconda3\envs\yys\python.exe dev_tools/screen_inspector.py --mumu "D:/Program Files/Netease/MuMu" --graph graphs.main:build_main_graph
   ```
   在新界面按 `R` → 期望底部叠加 `vertex: tingyuan_affairs`（绿）。切到其他界面按 `R` → 期望显示 `<unknown>`（红）或正确的其他 vertex 名。

   **`--graph` 何时该改**：
   - 默认 `graphs.main:build_main_graph` —— 只测根命名空间的 vertex（main_menu / popup / tingyuan_affairs 等）。
   - **测插件子图 / 跨命名空间 edge** —— **用现成的 `dev_tools.dev_graph:build_full_graph`**，它会 `discover()` 所有 plugin + 用 `GraphAssembler` 合并子图。详见 §6.1。
   - **`--graph` 接受任何 `<module>:<callable>` 形式**，callable 必须返回一个 `GameGraph` 实例（无参调用）。

   **判定规则（识别器的硬性约束）**：
   - **每个 vertex 在它对应的真实界面上必须被识别出来**（排他性命中）。
   - **vertex 之间不能有重叠的 recognizer 命中**（同一帧不能两个 vertex 都说"我是"）。重叠会让 `ScreenRecognizer` log warning 并返回第一个匹配，路径规划不可预测。两个相似的界面要么 anchor 抠得更独特，要么用 `region=` 限定搜索区。
   - **不该被识别为任何 vertex 的过渡界面 / 加载界面应该返回 `<unknown>`**——这是 Navigator 重新规划路径的触发条件。把不该识别的界面错误识别为某个 vertex 会让 Navigator 卡在错误的路径上。

2.7. **用 `nav_smoke.py` 做端到端导航烟雾测试**：

   vertex 接入 graph 之后，下一个该过的工具是 `dev_tools/nav_smoke.py`。它把"加载 graph → 截图 → 识别当前 vertex → `PathFinder` 找路径 → `Navigator.goto()` 真点击 → 验证到达"一条龙跑通，比写完 plugin 再发现 dangling edge 容易 debug 得多。

   ```powershell
   # 先 dry-run 看路径规划是否对（不会真点击）
   D:\anaconda3\envs\yys\python.exe dev_tools/nav_smoke.py --mumu "D:/Program Files/Netease/MuMu" --target tingyuanshiwu --dry-run

   # 输出大致是：
   #   loaded graphs.main:build_main_graph — 3 vertices, 2 edges
   #   current vertex: tingyuan
   #   path (1 edges):
   #     1. tingyuan -> tingyuanshiwu  via click_button-action  cost=1.20

   # 路径对的话去掉 --dry-run 真跑
   D:\anaconda3\envs\yys\python.exe dev_tools/nav_smoke.py --mumu "D:/Program Files/Netease/MuMu" --target tingyuanshiwu
   ```

   **`--graph` 默认 `graphs.main:build_main_graph`**，和 `screen_inspector.py` 共用同一套接口（任何 `module:callable` 返回 `GameGraph`）。**target 是 plugin 命名空间的 vertex 时（如 `shishenlu.home`、`daily_reward.sign_in_panel`），把 `--graph` 改成 `dev_tools.dev_graph:build_full_graph` ——否则插件子图没合并进图，target 找不到、跨命名空间 edge 全被当 dangling 删掉**（详见 §6.1）。

   **退出码 cheat sheet**：

   | 码 | 含义 | 处置 |
   | --- | --- | --- |
   | 0 | 到达目标 | 路径走通了 |
   | 2 | target vertex 不在 graph 里 | typo / 忘了 vertex() 注册 / **target 是 plugin 命名空间但 `--graph` 没用 `build_full_graph`**（看日志有没有 `dangling edge dropped`） |
   | 3 | 当前画面识别不出来 | 屏幕不对 / anchor 太严 → screen_inspector 调 |
   | 4 | `PathFinder` 找不到路径 | **典型 dangling edge bug**（edge 写了 `"foo.bar"` 但 vertex 只注册了 `"bar"`）→ 看启动时的 `validate() dropped` warning |
   | 5/6 | `Navigator.goto` 抛异常 | edge action 失败 / 到达后识别不到目标 vertex |
   | 7 | replans 用光仍未到 | 看日志哪条 edge 失败：通常是模板抠太松导致 click 落空 |

   **点击落点检查**：`click(Button)` 已经在 base 层用按钮 bbox 约束 jitter（保守档 `click_jitter_radius=12` 也不会跑出小按钮的 30×20 框），所以如果还是点击落空，**100% 是模板抠太松了**（模板内含按钮外的空白）。回 §5 步骤 2.5 用 `button_inspector` 看绿框是否紧贴可点击热区。

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
| `dev_tools/button_inspector.py` | **实时**验证一个 Button：加载生产代码里的对象，画匹配框 + 点击落点 + PASS/FAIL 判定 |
| `dev_tools/nav_smoke.py` | **端到端**导航烟雾测试：加载 graph + 真点击执行一次 `Navigator.goto(target)` 验证到达。`--dry-run` 只规划不点。新加 vertex/edge 后必跑 |
| `dev_tools/graph_visualizer.py` | 用 matplotlib 画图，节点按 owner 着色 |
| `dev_tools/screen_inspector.py` | 实时识别：截图后叠加"当前是 XXX 顶点" |
| `dev_tools/graph_composer.py` | 交互式建图（录 vertex + edge），输出 Python 草稿 |

CLAUDE.md §6 末尾的 `dev_tools/` 一节有每个工具的键位详解。

### 6.1 dev_tools 的 `--graph` 参数：何时用 `build_full_graph` ⭐

`nav_smoke.py` / `screen_inspector.py` / `graph_visualizer.py` 都接受 `--graph mod:fn`，但**默认值** `graphs.main:build_main_graph` **只构造 root 命名空间的图**，不会去 discover 任何 plugin 或合并子图——因为它是给 root 自身用的简单 builder。

| 你想做的事 | 用哪个 `--graph` |
| --- | --- |
| 验证 root 命名空间内部的 vertex / edge（`tingyuan` / `popup` / `tingyuanshiwu`）| `graphs.main:build_main_graph`（默认值，啥也不用加） |
| 跨命名空间导航：目标是 plugin 命名空间的 vertex（如 `shishenlu.home` / `daily_reward.sign_in_panel`） | **`dev_tools.dev_graph:build_full_graph`** |
| 看整个项目当前所有 plugin 提供的拓扑（开会 / 文档可视化） | **`dev_tools.dev_graph:build_full_graph`** |

`dev_tools.dev_graph:build_full_graph` 会：
1. `PluginRegistry.discover()` 扫盘找所有 plugin（不看 config 的 `enabled` 标志——dev 想看哪个 plugin 就看哪个）。
2. 用 `GraphAssembler` 合并所有 plugin 子图进 root。
3. 返回组装好的 `GameGraph`。

**典型症状**：如果 `nav_smoke.py` 报错 `dangling edge(s) dropped: <root_vertex> -> <plugin>.something`，且 `target vertex 'X' not in graph`——99% 是忘了用 `build_full_graph`，跨命名空间 edge 在 root-only 图里被当作 dangling 删掉了。

**示例**：

```powershell
# 走完整图，目标是 shishenlu 这个 plugin 命名空间的 vertex
D:\anaconda3\envs\yys\python.exe dev_tools/nav_smoke.py --mumu "D:/Program Files/Netease/MuMu" `
  --graph dev_tools.dev_graph:build_full_graph `
  --target shishenlu.home `
  --dry-run

# 同一个 --graph 给 screen_inspector 用（这样它也能识别 plugin 命名空间的 vertex）
D:\anaconda3\envs\yys\python.exe dev_tools/screen_inspector.py --mumu "D:/Program Files/Netease/MuMu" `
  --graph dev_tools.dev_graph:build_full_graph
```

**为什么 `dev_tools.dev_graph:build_full_graph` 而不是把 plugin 合并塞进默认值？**——保持职责分离。`graphs/main.py` 是 root 命名空间的**单一职责**单元，`dev_tools/dev_graph.py` 是 dev-only 的"全景视图"，由 `dev_tools` 持有 plugin 合并这一额外耦合，符合 CLAUDE.md §3 的 dev_tools 隔离原则（dev 可以引用 production，production 不引用 dev）。

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
A: 大概率是模板没抠对 / 阈值太高匹配不到。用 `dev_tools/button_inspector.py --button <mod>:<VAR>` 实时看匹配框、分数和点击落点；底部彩色横幅会直接告诉你是 PASS / MARGINAL / AMBIGUOUS / FAIL。详见 §5 步骤 2.5。

**Q: 怎么判断我刚抠的按钮模板够不够好？**
A: 跑 `dev_tools/button_inspector.py`。三个验证维度——(1) 当前界面有按钮时显示 PASS（headroom ≥ 0.05）；(2) 按 `A` 切到 all-matches 模式确认整张图里没有第二个匹配（不是 AMBIGUOUS）；(3) 切到其他界面按 `R`，期望看到红色 FAIL（在不该出现的地方没误匹配）。三个都过才能用进生产。

**Q: 点击好像点在了按钮周围而不是按钮上？**
A: `click(Button)` 在 base 层用 `_jitter_in_button` 在**整个匹配 bbox 内**采样（2026-05 重设计：早期版本被 `click_jitter_radius` 当上限封顶 → 中心 25% 块，操作员看到每帧点同一像素，已废弃）。落点保证落在 bbox 内（减去 `bbox_margin` 比例 + 2px 像素硬下限）。如果点偏，**100% 是模板抠太松了**——模板包了一圈按钮外的空白 → bbox 也包含空白 → 采样落到空白处。回 button_inspector 看绿色匹配框是不是紧贴可点击热区，松了就回 extractor 重抠紧一点。要在大 banner 上收紧落点：把 `global.humanize.bbox_margin` 从 0.1 调到 0.3 左右。

**Q: 每次点击都落在完全相同的像素上，不像随机？**
A: 大概率你跑的是 `dev_tools/nav_smoke.py` 这类 dev 工具的**旧版本**——之前没把拟人化参数接到 backend 上，导致 `_jitter_radius is None` → 直接落 match 中心。已修：dev_tools 现在默认镜像生产配置（`HumanizeConfig` 默认值），用 `--no-humanize` 才回到确定性点击。如果用的是 `main.py` 那条线还看到这个现象，检查 `config/config.yaml` 的 `global.humanize.click_jitter_radius` 是不是被改成 `0` 或 `null` 了。

**Q: 怎么验证我刚加的 vertex / edge 在真模拟器上能跑通？**
A: 用 `dev_tools/nav_smoke.py --target <vertex_id> --dry-run`。它把"识别 → 找路径 → 执行 → 验证到达"端到端跑一遍，不通的话退出码会指向具体原因（4 = 路径不通、3 = 识别失败、5/6 = action 抛异常、7 = 到达验证失败）。dry-run 不会真点击，路径打印对了再去掉 dry-run。详见 §5 步骤 2.7。

**Q: `nav_smoke.py` 报 `dangling edge(s) dropped: tingyuan -> plugin.something` 然后 `target vertex 'X' not in graph`？**
A: 99% 是忘了把 `--graph` 改成 `dev_tools.dev_graph:build_full_graph`。默认的 `graphs.main:build_main_graph` 只构造 root 命名空间的图，**不**走 `PluginRegistry.discover()` + `GraphAssembler` 合并 plugin 子图，所以 `plugin.something` 这种全限定 vertex 不存在，指向它的 edge 全被当 dangling 删了。详见 §6.1。`screen_inspector.py` / `graph_visualizer.py` 同理。

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
