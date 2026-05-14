# CLAUDE.md — AI 工作记忆

## 1. 产品目标

基于 MuMu 12 国服模拟器的游戏（阴阳师）自动化脚本：通过 nemu IPC（DLL 截图 + 注入触摸）避免 ADB 检测，支持多账号、多玩法热插拔，玩法之间共享图导航。

## 2. 当前进度

- ✅ Phase 0：项目骨架 + IPC 冒烟测试
- ✅ Phase 1：核心抽象层（异常体系 / 日志 / TTL 缓存 / Button / TemplateRepository / TemplateMatcher / OCR / InputBackend 抽象 + NemuIpcBackend / 工厂 / dev_tools 模板提取与匹配调试 / 52 项单元测试）
- ✅ Phase 2：图导航系统（GameGraph + DSL（subgraph/root_graph/vertex/edge/external + 9 个 action 工厂） / GraphAssembler 含未启用插件 dangling 处理 / PathFinder 含 avoid_risky / avoid_tags / 随机路径 / ScreenRecognizer / Navigator goto + 失败重规划 / dev_tools 三件套（visualizer/screen_inspector/composer） / 52 项新单元测试，全包 104 项通过）
- ✅ Phase 3：插件 + 线程 + 全局热键（CacheManager 字节预算 / GameplayPlugin + PluginContext（含可中断 sleep / wait_until_resumed） / PluginRegistry 扫盘发现 / PluginWorker 状态机 IDLE→RUNNING→{PAUSED,STOPPED,ERROR} / Scheduler 多账号多插件 + 命令队列 + 调度器线程 / HotkeyController 含 noop 后端 + F9/F10/F12 默认 / FakeBackend 提取到 core / DemoPlugin 5 次循环 + 跨命名空间返回 / 71 项新单元测试，全包 175 项通过）
- ⬜ Phase 4：首个玩法（一个完整的可跑业务循环）

## 3. 强制开发纪律（每次工作必读）

- **Python 环境**：本项目所有 `python` / `pytest` / `pip` 命令都必须在 conda 环境 **`yys`** 里跑。VSCode 默认解释器是系统 Python310，跑测试会找不到 numpy/opencv。命令行用 `D:\anaconda3\envs\yys\python.exe` 直接调或 `conda run -n yys ...`（注意 `conda run` 可能因 GBK 终端编码崩，必要时 `$env:PYTHONIOENCODING="utf-8"`）。
- **Git 工作流**：任何功能开发都必须先 `git checkout -b feature/xxx`，开发完成后合并回 `main` 并打 tag。**禁止在 `main` 分支直接提交**（Phase 0 的初始提交除外）。
- **文档纪律**：所有"公开方法"（不以下划线开头的方法）必须更新 [§6 公开 API 参考](#6-公开-api-参考)，写明：功能、参数、返回值、可能抛出的异常、边界条件。
- **异常纪律**：所有可预见的错误必须抛出 `core/exceptions.py` 中定义的异常子类，**禁止 `raise Exception(...)`**。所有异常必须被恰当捕获——不允许静默吞掉（`except: pass` 是红线）。
- **dev_tools 隔离**：`dev_tools/` 下的代码**绝不允许**被 `core/`、`plugins/`、`main.py` 引用。生产代码不依赖开发工具。`dev_tools/` 里的 import 写绝对路径（`from vendor.alas...`），可以反向引用生产代码做调试。
- **vendor 不可改**：`vendor/` 下的第三方代码**只能由 `dev_tools/vendor_alas.py` 写入**，禁止手动修改逻辑/格式/注释。如需扩展功能，在 `core/` 写包装层。重新 vendor 用 `python dev_tools/vendor_alas.py --clean`。
- **每个 Phase 结束时**：更新 [§2 当前进度](#2-当前进度)、[§6 公开 API 参考](#6-公开-api-参考)、[§7 已知问题与陷阱](#7-已知问题与陷阱)，然后 `git commit` + `git tag phase-N`。

## 4. 目录结构

```text
project/
├── core/                          # 生产代码核心层。所有抽象基类、运行时框架都在这。
│   ├── exceptions.py              # 异常树根 BotError 及全部子类（Phase 1/2/3 持续扩充）。
│   ├── logging_config.py          # setup_logging / get_logger，彩色 + 按天滚动（Phase 1）。
│   ├── input_backend/             # Strategy 模式：抽象输入接口 + nemu_backend.py + fake.py（demo/test）+ 工厂。
│   ├── vision/                    # 视觉栈：Button、TemplateRepository、TemplateMatcher、OcrEngine。
│   ├── navigation/                # 图导航：vertex/edge 模型、路径搜索、跨命名空间合并。
│   ├── scheduler/                 # Phase 3：plugin_base.py / registry.py / worker.py / scheduler.py。
│   ├── hotkey/                    # Phase 3：controller.py（keyboard / noop 后端）。
│   └── cache/                     # lru.py: TTLCache（计数）；manager.py: CacheManager（字节预算，per account_id）。
├── vendor/alas/                   # Alas (LmeSzinc/AzurLaneAutoScript) 的 verbatim 子集。
│                                  # 详见 vendor/alas/README.md。
├── plugins/                       # 每个子目录 = 一个玩法 = 一个 GameplayPlugin 实现。
│                                  # 自带 graph.py 子图与 main 主图合并。
├── graphs/                        # 主图（全局界面骨架，main_menu/profile 等）。
├── templates/                     # 模板图（PNG），按玩法分子目录。
├── dev_tools/                     # 开发脚本：vendor 生成、smoke 测试、模板裁剪等。
│                                  # 禁止被生产代码 import。
├── tests/                         # 单元/集成测试。
├── logs/                          # 运行日志（按 account_id 子目录隔离）。
├── main.py                        # 程序入口。
├── requirements.txt
├── .gitignore
└── CLAUDE.md                      # 本文件。
```

## 5. 架构决策（关键设计模式）

- **输入层**：Strategy 模式。`core/input_backend/base.py` 定义 `InputBackend` 抽象基类，`core/input_backend/nemu_backend.py` 是当前实现（封装 vendor/alas 的 `NemuIpcImpl`）。未来替换底层（scrcpy/MAA/真机 ADB），只改这一层。
- **UI 元素**：`Button` 一等公民对象（`core/vision/button.py`）。封装"模板路径 + 阈值 + 搜索区域 + 点击偏移 + 后置延迟"。所有可点击元素都用 `Button` 表达，**禁止散落的 `(x, y)` 硬编码或一次性 click_template**。
- **导航层**：基于 NetworkX 的有向图。Vertex = 游戏界面（一个稳定的 UI 状态），Edge = 操作（点击、滑动、等待）。Edge 带 `cost`（耗时，秒）和 `risky`（是否危险——例如花钻、消耗资源）属性。
- **图组合（模块化命名空间）**：主图（`graphs/main.py`）只定义全局骨架（如 `main_menu`、`profile`）。每个插件自带子图（`plugins/<name>/graph.py`）。子图内部的 vertex/edge 使用 **bare name**（相对路径），引用其他命名空间的 vertex 使用 **全限定名 `<plugin>.<vertex>`**（绝对路径）。启动时按插件名挂载所有子图到主图。**每个 vertex 有唯一的产权插件**，插件之间禁止重复定义同一界面。**插件可声明跨边界 edge**（如插件 A 的某个 vertex 按返回键回到 `main.main_menu`），但只能引用对方 vertex、不能定义。
- **玩法层**：Plugin 模式。`core/scheduler/plugin_base.py` 定义 `GameplayPlugin` 基类。`plugins/` 下每个子目录是一个玩法，运行时自动注册。
- **线程模型**：每个玩法跑在独立 Worker 线程内。主线程通过 `queue.Queue` 下命令，通过 `threading.Event` 控制停止。
- **缓存**：内存 LRU（`functools.lru_cache` 不够灵活时自己写），所有缓存带 TTL，"用完即释放"。
- **多账号就绪原则（关键）**：所有"状态承载者"（`InputBackend`、`Navigator`、`PluginContext`、`CacheManager`、Scheduler 的内部 Worker 池）必须按 `account_id` 构造，**全程禁止任何形式的单例或全局状态**。配置文件用列表结构（`accounts: [...]`），即使现在只有一个账号。OCR 引擎是**唯一例外**（stateless、初始化慢，单例可接受，但要保证线程安全）。日志和缓存按 `account_id` 物理隔离到不同子目录。

## 6. 公开 API 参考

按模块组织，每个公开类/函数都要写：签名 / 功能 / 参数 / 返回 / 异常 / 边界。

### vendor/alas/module/device/method/nemu_ipc.py

#### `NemuIpcImpl(nemu_folder: str, instance_id: int, display_id: int = 0)`

底层 nemu IPC 实现，单实例对应单 MuMu 实例。Phase 0 阶段我们只用这一个类（高层 `NemuIpc(Platform)` 封装类不用）。

**构造参数**
- `nemu_folder` *(str)*：MuMu 12 安装根目录。**注意**：是 MuMu 的安装根（含 `nx_main/`、`nx_device/`、`vms/` 等），不是 `shell/` 或 `nx_main/`。例如 `D:\Program Files\Netease\MuMu`。
- `instance_id` *(int)*：MuMu 实例 ID，从 0 开始（多开时实例 1 是第二个）。
- `display_id` *(int, default=0)*：显示器 ID。除非开启了"后台挂机时保活运行"否则保持 0。

**构造时副作用**
- 尝试加载 `<nemu_folder>/shell/sdk/external_renderer_ipc.dll`，找不到则尝试 `<nemu_folder>/nx_device/12.0/shell/sdk/external_renderer_ipc.dll`（MuMu 12 v5.0+ 的新路径）。两者都没有则抛 `NemuIpcIncompatible`。
- 仅加载 DLL，不连接实例。

**异常**
- `NemuIpcIncompatible`：DLL 路径都不存在，或 MuMu 版本太旧（<3.8.13）。

---

#### `NemuIpcImpl.connect(on_thread: bool = True) -> None`

向指定实例发起 IPC 连接。已连接（`self.connect_id > 0`）则直接返回，幂等。

**参数**
- `on_thread`：True 时把 DLL 调用放到工作线程跑（默认，避免主线程被卡死）。

**副作用**：设置 `self.connect_id`（>0 表示成功）。

**异常**
- `NemuIpcError("Connection failed, ...")`：模拟器没开 / `nemu_folder` 错 / `instance_id` 错。

---

#### `NemuIpcImpl.disconnect() -> None`

断开 IPC。未连接时无操作，幂等。

---

#### `NemuIpcImpl.reconnect() -> None`

= `disconnect()` + `connect()`，由 `@retry` 装饰器在某些错误下自动调用。

---

#### `NemuIpcImpl.screenshot(timeout: float = 0.5) -> np.ndarray`

截图。

**返回**：`np.ndarray`，shape `(height, width, 4)`，dtype `uint8`，色彩空间 **BGRA**，**上下颠倒**。  
调用方必须自己做 `cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)` + `cv2.flip(img, 0)`，否则保存的 PNG 是反的、颜色还原也不对（参考 `dev_tools/ipc_smoke_test.py`）。

**异常**
- `NemuIpcError`：DLL 调用返回非零。
- `RequestHumanTakeover`：`@retry` 重试用光后抛出。

**边界**
- 第一次调用会自动 `connect()` 并 `get_resolution()`。
- `timeout` 是 DLL 单次调用超时；`@retry` 会动态延长。

---

#### `NemuIpcImpl.down(x: int, y: int) -> None`

按下触摸点。连续多次 `down()` 会被 nemu 当成 swipe。  
**`(x, y)` 是 ADB 经典坐标**（横屏游戏 1920×1080 时 x ∈ [0, 1920], y ∈ [0, 1080]），方法内部用 `convert_xy()` 旋转到 DLL 坐标系。

**异常**
- `NemuIpcError`：DLL 调用失败。
- `RequestHumanTakeover`：重试用光。

**边界**：第一次调用会自动 `connect()` + `get_resolution()`。

---

#### `NemuIpcImpl.up() -> None`

抬起触摸点（手指离开屏幕）。

**异常**
- `NemuIpcError`：DLL 调用失败。
- `RequestHumanTakeover`：重试用光。

---

#### `NemuIpcImpl.serial_to_id(serial: str) -> int | None`

静态方法。从 ADB serial 推断 MuMu 实例 ID。

| serial 示例 | 返回 |
|---|---|
| `127.0.0.1:16384` | 0 |
| `127.0.0.1:16416` | 1 |
| `127.0.0.1:16448` | 2 |
| 不合法 | `None` |

**边界**：仅支持端口 16384 起的 MuMu 默认规则。其他模拟器返回 `None`。

---

#### 异常类

- `NemuIpcIncompatible`：DLL 找不到 / MuMu 版本太旧。**不可重试**。
- `NemuIpcError`：DLL 调用层面的错误（连接失败、捕获失败）。**可重试**。
- `RequestHumanTakeover`（来自 `vendor.alas.module.exception`）：重试用光、需要人工介入。

> 注：以上是 vendor 层。**业务代码不应直接接触 `NemuIpcError` / `NemuIpcIncompatible` / `RequestHumanTakeover`**——`NemuIpcBackend` 把它们翻译成 `core.exceptions` 里的对应类型（见下文 §6 / `core.exceptions`）。

---

### core/exceptions.py

异常树根 `BotError`，所有可预见错误都必须抛它的子类。绝不允许 `raise Exception(...)`。

| 类 | 父类 | 触发场景 |
|---|---|---|
| `BotError` | `Exception` | 所有可预见错误的根。在 worker 顶层捕获它，把运行时崩溃（KeyboardInterrupt 等）和"我们的 bug"分开。 |
| `InputBackendError` | `BotError` | 输入后端层任何错误，具体 backend 必须把原生异常翻译成本类的子类。 |
| `BackendNotAvailable` | `InputBackendError` | DLL 缺失 / MuMu 路径不对 / MuMuPlayerGlobal。**不可重试**。 |
| `BackendConnectionLost` | `InputBackendError` | 连接成功后 IPC 调用挂了；可能可重启模拟器恢复。 |
| `VisionError` | `BotError` | 视觉层任何错误。 |
| `TemplateNotFound` | `VisionError` | `Button.template` 指向的 PNG 不在 disk 上。 |
| `MatchTimeout` | `VisionError` | `wait_for` 超时；`click(Button)` 一次没找到也抛这个。 |
| `OcrError` | `VisionError` | PaddleOCR 初始化或调用失败、输入 shape/dtype 不对。 |
| `NavigationError` | `BotError` | 预留给 Phase 2。 |
| `PluginError` | `BotError` | 预留给 Phase 3。 |

---

### core/logging_config.py

#### `setup_logging(account_id: str | None = None, level: int = logging.INFO, log_dir: pathlib.Path | None = None) -> pathlib.Path`

幂等地装好控制台（带 ANSI 彩色）+ `TimedRotatingFileHandler`（按天滚动，14 天保留）。

**参数**
- `account_id`：非空时日志落到 `logs/<account_id>/bot.log`，否则 `logs/bot.log`。
- `level`：root logger 阈值。
- `log_dir`：覆盖日志根（测试用）。

**返回**：实际写日志的目录。

**异常**：`OSError` — 目录创建失败。

**边界**
- 重复调用安全：自己挂的 handler 带 `_yys_owned` 标记，再次调用时只清掉自己的。Alas vendor 装的 handler 不动。
- 文件 handler 用 UTF-8 编码，与 Windows 终端默认 GBK 解耦。

#### `get_logger(name: str) -> logging.Logger`

返回 `logging.getLogger(name)`。首次调用若 `setup_logging` 没跑过会自动跑一次（默认参数）。约定 `name=__name__`。

---

### core/cache/lru.py

#### `TTLCache(max_size: int = 128, default_ttl: float = 5.0, clock=time.monotonic)`

线程安全的 LRU + per-entry TTL。基于 `OrderedDict`。

**构造参数**
- `max_size > 0`：硬上限。
- `default_ttl >= 0`：`set` 不传 ttl 时用这个；`inf` 表示纯 LRU 永不过期。
- `clock`：时间源；测试用 `lambda: now[0]` 之类的注入。

**异常**：`ValueError`（参数非法）。

**公开方法**
- `get(key, default=None) -> V | None`：命中则 bump 到 MRU；过期则静默 evict 并视为 miss。
- `set(key, value, ttl=None) -> None`：`ttl=0` 不写入（明确放弃缓存）；插入后若超 `max_size` evict LRU。
- `invalidate(key) -> bool`：删除单个 key，存在返回 True。
- `clear() -> None`：清空。
- `purge_expired() -> int`：清除全部过期项，返回数量。
- `__len__` / `__contains__` / `keys()`（snapshot 迭代器）。

**边界**
- 多账号场景：截图缓存**必须**每账号一个实例；模板缓存（不可变内容）跨账号共享 OK，由 `TemplateRepository` 内部封装。
- `set` 时复制语义：不做防御性拷贝，调用方负责传不可变对象或显式 `.copy()`。

---

### core/vision/button.py

#### `Button(template, threshold=0.85, region=None, click_offset=(0,0), post_delay=0.5, retry=3, name=None)`

冻结（frozen=True）dataclass，描述一个可点击的 UI 元素。**全项目唯一合法的"按钮"表达**，禁止散落 `(x, y)` 硬编码。

**字段**
- `template` *(str)*：模板逻辑名，相对 `templates/`，不带 `.png`。例 `"main_menu/profile_btn"` → `templates/main_menu/profile_btn.png`。允许 `/` 或 `\`，`TemplateRepository` 会归一化。
- `threshold` *(float, (0, 1])*：`cv2.matchTemplate` 通过阈值。0.85 默认；干净 UI 可保留，文字/抗锯齿区域调低，复杂背景调高。
- `region` *((x1, y1, x2, y2) | None)*：ADB 屏幕坐标的搜索框。`None` = 全屏。限制 region 是最便宜的提速 + 防误匹配手段。
- `click_offset` *((dx, dy))*：相对匹配中心的点击偏移。
- `post_delay` *(float, >=0)*：点击后强制 `time.sleep` 的秒数。让下一次截图能看到 UI 动画后的稳定状态。`click(button, post_delay=...)` 可覆盖。
- `retry` *(int, >=0)*：保留字段；`wait_for` 实际由 `timeout + interval` 控制。
- `name` *(str | None)*：日志/异常里显示用；不传则用 `template`。

**构造异常**
- `ValueError`：`template` 空 / `threshold ∉ (0,1]` / `region` 反向 / `post_delay<0` / `retry<0`。

**便捷工厂**
- `Button.simple(template, **overrides) -> Button`
- `Button.in_region(template, region, **overrides) -> Button`

**实例方法**
- `display_name`（property）：`name or template`。
- `with_(**overrides) -> Button`：克隆并替换字段；用于一次性调点击延迟等。

**边界**：frozen + 全部字段不可变 → 可哈希，可作缓存 key、可跨线程共享。

---

### core/vision/template_repository.py

#### `TemplateRepository(root: Path | None = None, max_cached: int = 512)`

加载和缓存模板 PNG。**跨账号共享**（CLAUDE.md S5 明确豁免），单进程一份就够。

**构造参数**
- `root`：模板根目录，默认 `<project>/templates`。
- `max_cached`：LRU 上限。

**属性 & 方法**
- `root` *(Path)*：当前根目录。
- `resolve(name: str) -> Path`：纯路径计算，把逻辑名映射到磁盘绝对路径。容忍 `.png` 后缀、混合 `/`、`\`。
- `get(name: str) -> np.ndarray` 和别名 `load(name) -> np.ndarray`：返回模板，自动缓存。`(H, W, 3)` BGR 或 `(H, W, 4)` BGRA（带 alpha 的模板原样保留，由 `TemplateMatcher` 当 mask 使用）。
- `invalidate(name: str | None = None) -> None`：清单个或全部。模板被 `dev_tools/template_extractor.py` 覆盖后调用。

**异常**
- `TemplateNotFound`：文件不存在或 `cv2.imread` 解码失败。

---

### core/vision/template_matcher.py

#### `TemplateMatcher(repository: TemplateRepository | None = None)`

`cv2.matchTemplate` 的 `Button` 化包装。只回答"在不在 / 在哪里"，不做点击。

**属性**：`repository`（暴露给调用者做 invalidate）。

**方法**
- `find(screenshot, button) -> (x, y) | None`：找到则返回 click 中心点（含 `click_offset`），否则 None。
- `find_all(screenshot, button) -> list[(x, y)]`：所有 ≥ threshold 的位置，相邻 ≤ template 一半的合并为一个。
- `find_by_name(screenshot, template_name, threshold=0.85, region=None) -> (x, y) | None`：旧式快速调用，等价于 `find(screenshot, Button(...))`。生产代码优先用 `Button` 形态。

**参数约束**
- `screenshot`：必须 `np.ndarray`，dtype `uint8`，shape `(H, W, 3)` — backend 已经把 BGRA + 倒置统一规范化了，业务代码看到的就是这个。

**异常**
- `VisionError`：截图 shape/dtype 不合规 / 模板通道异常。
- `TemplateNotFound`：模板 PNG 缺失（由 `TemplateRepository.get` 抛出）。

**边界**
- 模板带 alpha 通道时会拆出来当 `cv2.matchTemplate` 的 `mask`：透明像素不参与评分。利于"按钮在变化背景上"的鲁棒匹配。
- 单一颜色（零方差）模板会让 `TM_CCOEFF_NORMED` 退化（处处 NaN/1.0）——避免做纯白/纯黑模板。

---

### core/vision/ocr.py

PaddleOCR 包装。**单进程单例**（CLAUDE.md S5 唯一豁免），通过 `_call_lock` 串行调用，保证线程安全。

#### `OcrEngine.instance(lang: str = "ch") -> OcrEngine`

返回进程内单例，懒构造。第一次调用的 `lang` 决定该实例的语言，之后传不同语言不会生效。

**异常**：`OcrError` — paddleocr 没装 / 引擎初始化失败。

#### `OcrEngine.recognize(image: np.ndarray) -> list[(text, confidence, (x1, y1, x2, y2))]`

对 BGR 截图跑一次 OCR。坐标相对 `image`。空列表 = 没识别到。

**异常**：`OcrError` — shape/dtype 不对 / 引擎调用挂了。

#### `OcrEngine.find_text(image, keyword, min_confidence=0.6, case_sensitive=False) -> (x1, y1, x2, y2) | None`

找到首个包含 `keyword` 的检测框（substring match），按 confidence 过滤。

**边界**
- paddleocr 是惰性 import（`__init__` 内部），所以 `import core.vision` 不会强依赖它。
- `recognize` 内部用 RLock 串行；高吞吐场景再考虑多引擎池。

---

### core/input_backend/base.py

#### `InputBackend(account_id: str, matcher: TemplateMatcher | None = None)` — 抽象基类

Strategy 模式根接口。**禁止直接实例化**；继承它实现具体后端。所有后端必须按 `account_id` 构造，原生异常必须翻译到 `InputBackendError` 子类。

**构造异常**：`ValueError` — `account_id` 为空。

**只读属性**
- `account_id` *(str)*：构造期固化。
- `matcher` *(TemplateMatcher)*：共享或私有的 matcher。

**抽象方法（子类必须实现）**
| 方法 | 语义 | 异常 |
|---|---|---|
| `connect() -> None` | 打开传输。幂等。 | `BackendNotAvailable` / `BackendConnectionLost` |
| `disconnect() -> None` | 关闭传输。幂等。 | — |
| `is_connected() -> bool` | 当前是否持有可用传输。 | — |
| `screenshot() -> np.ndarray` | BGR `(H, W, 3) uint8`，**已正向**（非 BGRA、非倒置）。 | `BackendNotAvailable` / `BackendConnectionLost` |
| `click_xy(x, y, randomize=True) -> None` | ADB 坐标点击；`randomize=True` 时由后端做几像素抖动。 | 同上 |
| `long_click_xy(x, y, duration) -> None` | 按住 `duration` 秒。 | 同上；`ValueError` if `duration<=0` |
| `swipe(p1, p2, duration) -> None` | 带惯性的快速滑动。 | 同上 |
| `drag(p1, p2, duration) -> None` | 无惯性的拖动。 | 同上 |

**高层方法（基类已实现，子类不要重写）**
- `click(target: Button | (x, y), *, post_delay=None, randomize=True) -> (x, y)`：智能分派。`Button` → 截图 + 匹配 + 点击；`(x, y)` → 直接点。`Button` 没找到抛 `MatchTimeout`。
- `find(button) -> (x, y) | None`：一次截图 + 匹配。
- `is_visible(button) -> bool`：糖。
- `wait_for(button, timeout=10, interval=0.5) -> (x, y)`：阻塞轮询；用 `time.monotonic`；超时抛 `MatchTimeout`，参数 ≤ 0 抛 `ValueError`。
- 上下文管理器：`with backend:` 等价于 connect/disconnect。

**`_jitter(x, y, radius=3) -> (x, y)`**：保护方法，提供给所有子类的统一抖动实现。

---

### core/input_backend/nemu_backend.py

#### `NemuIpcBackend(account_id: str, mumu_folder: str, instance_id: int = 0, display_id: int = 0, matcher: TemplateMatcher | None = None)`

`InputBackend` 的 nemu IPC 实现。底层封装 `vendor.alas.module.device.method.nemu_ipc.NemuIpcImpl`。

**构造期行为**
- 校验 `mumu_folder`：存在且不含 `MuMuPlayerGlobal`。
- 懒 import nemu_ipc（避免 `core.input_backend` 模块加载时拉入 Alas 整套运行时）。
- 构造 `NemuIpcImpl`（只加载 DLL；不连接）。

**构造异常**
- `BackendNotAvailable`：路径不存在 / Global 版 / DLL 缺失或太旧 / vendor 包加载失败。

**实现说明**
- `screenshot()`：内部把 BGRA → BGR + `cv2.flip(img, 0)`，上层永远拿到正向 BGR。
- `click_xy()`：`down → sleep 20ms → up`，模拟干净的 tap；`randomize=True` 时 `_jitter` ±3 像素。
- `swipe()` vs `drag()`：通过插值步数和末端 hold 时长区分（swipe = 少步无 hold = 惯性滑；drag = 多步 + 0.08s hold = 控制拖）。
- 所有 DLL 调用走 `self._call_lock`（RLock）串行，保护触摸状态不被多线程下错。
- 翻译表：`NemuIpcIncompatible → BackendNotAvailable`；`NemuIpcError → BackendConnectionLost`；其他底层异常（含 `RequestHumanTakeover`）→ `BackendConnectionLost`。

---

### core/input_backend/factory.py

#### `get_input_backend(account_id: str, backend_name: str = "nemu", *, matcher=None, **kwargs) -> InputBackend`

唯一的 backend 构造入口。Phase 1 只支持 `backend_name="nemu"`。

**`nemu` 所需 kwargs**
- `mumu_folder` *(str, 必填)*
- `instance_id` *(int, 可选, default 0)*
- `display_id` *(int, 可选, default 0)*

**返回**：未连接的 `InputBackend`。调用方手动 `.connect()` 或用 `with` 块。

**异常**
- `BackendNotAvailable`：未知 backend / 缺必填 kwargs / 多余 kwargs / 具体 backend 拒绝其配置。

---

### dev_tools/template_extractor.py（开发工具，禁被生产代码 import）

CLI 入口：`python dev_tools/template_extractor.py --mumu <root> [--instance N] [--display D] [--account-id ID]`

交互快捷键：`S` 刷新截图、拖框选区域、`C` 裁剪并提示保存名（如 `main_menu/profile_btn`）、`A` 切换 alpha 抠图（点击预览窗采样背景色，`+/-` 调容差，`W` 存 BGRA 版本）、`Q` 退出。模板写入 `templates/<name>.png`。

### dev_tools/vision_debug.py（开发工具，禁被生产代码 import）

CLI 入口：`python dev_tools/vision_debug.py --screenshot <path> --template <name> [--threshold X] [--region X1 Y1 X2 Y2] [--all] [--out path]`

把匹配框 + 中心点画到原图上，用来调 `Button.threshold` / `Button.region`。

---

### core/navigation/graph.py

#### `Vertex(id, name, recognizer, dwell_time=500, owner=None)`（frozen dataclass）

游戏中一个稳定的 UI 状态。

- `id`：组装后的全限定名，如 `daily_reward.entry`。子图内写 bare name，merge 时由 DSL 加前缀。
- `name`：日志/工具用的人类可读标签；不传默认 = `id`。
- `recognizer`：识别"是否在这个界面"。`ScreenRecognizer` 接受 `Button` / `str`（等价 `Button.simple(...)`）/ `(screenshot)->bool` 三种形式；其他类型在使用时报 warning 并跳过。
- `dwell_time`（int 毫秒）：到达此 vertex 后默认等待时间。`Navigator` 在每条边走完后会等这么久再做识别确认。
- `owner`：所属命名空间。`merge()` 统一覆盖为传入的 namespace，根图为 `"main"`。

#### `Edge(src, dst, action, cost=1.0, risky=False, tags=(), cooldown=0.0)`（frozen dataclass）

- `src` / `dst`：全限定 vertex id（含点）或根命名空间 bare name。
- `action`：`Callable[[NavigationContext], None]`，由 DSL action 工厂或自定义函数生产。
- `cost`：路径权重（秒级估算）。
- `risky`：标记为"危险"操作（消耗资源、不可逆等）。`PathFinder(avoid_risky=True)` 会绕开。
- `tags`：自由 tag 元组，`PathFinder(avoid_tags=[...])` 用来排除。
- `cooldown`：保留字段（Phase 2 只存不执行）。

#### `GameGraph()`

NetworkX `DiGraph` 的封装，附带命名空间合并和 dangling-edge 校验。

- `add_vertex(id, *, name=None, recognizer=None, dwell_time=500, owner=None) -> Vertex`：注册一个 vertex。**重复 id 抛 `GraphValidationError`**；id 已是 ghost（被 `add_edge` 自动建出来）的会被原地"补全"，不会冲突。
- `add_edge(from_id, to_id, *, action, cost=1.0, risky=False, tags=None, cooldown=0.0) -> Edge`：注册一条 edge。**允许引用尚未注册的 vertex**（跨命名空间前向引用），由 `validate()` 决定后续处理。`(from_id, to_id)` 重复抛 `GraphValidationError`。`cost < 0` / `cooldown < 0` 抛 `ValueError`。
- `get_vertex(id) -> Vertex` / `get_edge(from_id, to_id) -> Edge`：查找；不存在抛 `UnknownVertex`。
- `has_vertex(id) -> bool` / `has_edge(from_id, to_id) -> bool` / `__contains__` / `__len__`。
- `vertex_owner(id) -> str | None`：返回 owner；不存在或仍是 ghost 返回 None。
- `vertices() -> Iterator[Vertex]` / `edges() -> Iterator[Edge]` / `vertex_ids() -> list[str]`：只迭代"已注册"节点，自动跳过 ghost。
- `merge(other, namespace) -> GameGraph` ⭐：把 `other` 合并进来，把所有"已注册"vertex 的 owner 改成 `namespace`，并复制所有 edge。**前置条件：`other` 的所有 vertex id 必须以 `<namespace>.` 开头**（这是 DSL 保证的），否则抛 `GraphValidationError`；和 `self` 已有 vertex 重名也抛。`other` 中的 ghost endpoint（跨命名空间前向引用）随 edge 一起带过来，后续由 `validate()` 解决。
- `validate(*, strict=False) -> list[Edge]`：扫一遍 dangling edges（任一端点是 ghost）。默认从图中删除并 log warning，返回被删的 edge 列表；`strict=True` 时抛 `GraphValidationError`。`self.dangling_edges` 持有最近一次的结果，供调试。
- `subgraph_of(namespace) -> GameGraph`：浅拷贝出只含某个 owner 的 vertex + 完全在该 owner 内的 edge，调试用。
- `describe() -> dict`：`{vertices, edges, by_owner, dangling_dropped}`。
- `nx -> nx.DiGraph`：直接拿底层图，给 PathFinder/可视化工具用；外部不要在生产代码里改。

---

### core/navigation/builder.py — DSL

DSL 入口都依赖一个 **thread-local 上下文栈**，所以 `vertex()` / `edge()` 必须在 `subgraph()` 或 `root_graph()` 块内调用，否则抛 `GraphValidationError`。

#### `NavigationContext(backend, extras=None)`（dataclass）

每个 action 收到的"上下文对象"。Phase 2 只用 `.backend`（`InputBackend` 实例）；`extras` 是 dict，Phase 3 会塞 cache、stop_event 等。

#### 上下文管理器

- `subgraph(name, *, graph=None)` ⭐：进入插件子图上下文。`name` 不能为空。块内 vertex/edge 默认 `owner=name`，bare name 自动加 `<name>.` 前缀。返回（yield）目标 `GameGraph`。
- `root_graph(*, graph=None)`：进入根（无命名空间）上下文。块内 vertex/edge 默认 `owner="main"`，bare name **不加**前缀。用于 `graphs/main.py`。

两者都可以传 `graph=` 复用已有 `GameGraph`，否则新建。

#### `vertex(id, *, name=None, recognizer=None, dwell_time=500, owner=None) -> str`

向当前 builder 注册一个 vertex；返回**已加前缀的全限定 id**。
- `owner=None` 时默认为 builder 默认值（`"main"` for root_graph，namespace for subgraph）。

#### `edge(from_id, to_id, *, action, cost=1.0, risky=False, tags=None, cooldown=0.0) -> (src, dst)`

向当前 builder 注册一条 edge。`from_id` / `to_id` 各自走 builder 的 qualify 规则：
- 不含 `.` 且不是 `_External` → 加 namespace 前缀（root_graph 时不加）；
- 含 `.` → 原样保留；
- `external(...)` 包装 → 始终原样保留（即使不含 `.`，根命名空间的入口就用这个）。

#### `external(name) -> _External`

包装一个名字，告诉 DSL "这是绝对引用，别加前缀"。典型场景：插件子图引用根命名空间的 `main_menu`（不含点，bare 形式会被错误加前缀）。

#### Action 工厂（都返回 `Callable[[NavigationContext], None]`）

- `click_button(button: Button)`：调 `ctx.backend.click(button)`。
- `click_at(x, y, *, randomize=True)`：硬编码点击；草稿里附 "WARNING: hardcoded coordinates" 注释。
- `swipe_to(start, end, duration=0.3)`：两点滑动。
- `swipe_dir(direction, distance=300, duration=0.3)`：从当前截图中心向 `"up"`/`"down"`/`"left"`/`"right"` 滑 `distance` 像素。
- `press_back()`：调 `ctx.backend.press_back()`。**当前 `NemuIpcBackend` 抛 `NotImplementedError`**（nemu DLL 只有触摸通道）；插件可以改用 `click_button(BACK_BTN)`。
- `wait(seconds)`：纯 `time.sleep`。模拟"加载完成后自动到下一界面"。
- `compose(*actions)`：顺序执行。
- `conditional(predicate, then_action, else_action=None)`：运行时分支。`predicate` 是 `(ctx) -> bool`。

---

### core/navigation/assembly.py

#### `GraphAssembler()`

主图 + 多个插件子图 → 一个可运行图。

- `set_main(graph: GameGraph) -> self`：注册主图（再次调用会替换）。
- `add_subgraph(namespace: str, graph: GameGraph) -> self`：注册插件子图。`namespace` 不能为空，**不能含 `.`**（Phase 2 不支持嵌套命名空间）。重复注册抛 `ValueError`。
- `main` / `registered_namespaces`：自省属性。
- `assemble(enabled_plugins: set[str] | None = None, *, strict=False) -> GameGraph` ⭐：
  - 浅拷贝主图，依次 `merge()` 每个 `enabled_plugins` 中的子图。
  - `enabled_plugins=None` → 合并全部已注册子图。
  - 未注册的 namespace 在 `enabled_plugins` 中 → log warning，**不抛**。
  - 禁用的插件相关 dangling edge（如主图指向 `disabled.entry`）被 `validate()` 删除并 warn。
  - `strict=True` 时 dangling edge 抛 `GraphValidationError`。

---

### core/navigation/pathfinder.py

#### `PathFinder(graph: GameGraph)`

**不感知命名空间**，输入输出都用全限定 id。

- `shortest_path(start, end, *, avoid_risky=False, avoid_tags=None) -> list[Edge]`：`networkx.shortest_path` 加 `cost` 权重。被 ban 的 edge 权重设为 `inf`，**只有当存在合法路径时才会绕开**；如果所有路径都被 ban，抛 `NoPathFound`。`start == end` 返回 `[]`。
- `random_path(start, end, *, avoid_risky=False, avoid_tags=None, max_paths=10, max_length_factor=1.5, rng=None) -> list[Edge]` ⭐：先算最短路径长度 L，枚举所有顶点数 ≤ `ceil((L+1) * max_length_factor)` 的简单路径（最多 `max_paths` 条），过滤掉含被 ban edge 的，从剩下的中**均匀随机**选一条。这是"模拟人类不总走最优"的核心。`max_paths < 1` 或 `max_length_factor < 1.0` 抛 `ValueError`。`rng` 注入点供测试用。
- `all_paths(start, end, *, max_length=None) -> list[list[Edge]]`：所有简单路径，`max_length` 用顶点数限制。
- 抛 `UnknownVertex`（start/end 不存在）/ `NoPathFound`（无可达路径）。

---

### core/navigation/recognizer.py

#### `ScreenRecognizer(matcher: TemplateMatcher | None = None)`

判断"当前截图属于哪个 vertex"。

- `detect_current(screenshot, graph) -> str | None`：遍历 `graph.vertices()`，对每个的 recognizer 计算结果，返回第一个命中的 vertex id。**多个命中 log warning 但仍返回第一个**（UI 应当互斥，重叠是图 bug）。recognizer 抛异常 log warning 并跳过。
- `invalidate(vertex_id=None)`：清单个或全部 recognizer 缓存（recognizer 解析过一次后会被缓存，便于热重载模板时强制重算）。
- recognizer 类型：`Button`（用 matcher.find）、`str`（等价 `Button.simple`）、callable `(screenshot) -> bool`；其他类型 log warning 并跳过该 vertex。

---

### core/navigation/navigator.py

#### `Navigator(backend, graph, pathfinder=None, recognizer=None, *, context_extras=None)`

把 backend、graph、PathFinder、ScreenRecognizer 串起来执行导航。

- `goto(target_id, *, mode="shortest", avoid_risky=False, avoid_tags=None, max_path_replans=1, per_edge_timeout=10.0) -> bool` ⭐：
  1. 识别当前 vertex（识别失败抛 `CurrentVertexUnknown`）。
  2. `mode="shortest"` 用 `shortest_path`，`mode="random"` 用 `random_path`；其他值抛 `ValueError`。
  3. 逐 edge 执行：调 `edge.action(ctx)`，等 `dst.dwell_time` 毫秒，再 `detect_current()` 验证到达 `edge.dst`。
  4. **未到达**期望 vertex → 重新识别 + 重新规划，最多 `max_path_replans` 次；耗尽后抛 `EdgeExecutionFailed`。识别完全失败抛 `CurrentVertexUnknown`。
  5. `target_id` 支持全限定（`plugin.foo`）和根命名空间 bare name（`profile`，会查 owner=="main" 的 vertex，多个匹配抛 `UnknownVertex`）。
  6. `per_edge_timeout`：单 edge 超过该耗时只 log warning，不中断（用来抓 `wait(600)` 这种笔误）。
- `is_at(vertex_id) -> bool`：当前 vertex 是否 == 指定 id。识别失败返回 False。
- `detect_current() -> str | None`：截图 + 识别，糖方法。

异常：`UnknownVertex` / `CurrentVertexUnknown` / `NoPathFound` / `EdgeExecutionFailed`，都是 `NavigationError` 子类。

---

### dev_tools/graph_visualizer.py（开发工具，禁被生产代码 import）

CLI：`python dev_tools/graph_visualizer.py (--demo | --build mod:fn) [--out PATH] [--show] [--path FROM TO]`

用 matplotlib + networkx 渲染图。节点按 `owner` 着色，risky edge 画虚线红色，`--path` 高亮一条最短路径。Windows 上自动选 Microsoft YaHei 让 CJK 标签可读。

### dev_tools/screen_inspector.py（开发工具，禁被生产代码 import）

CLI：`python dev_tools/screen_inspector.py --mumu <root> [--instance N] [--display D] [--account-id ID] [--graph mod:fn]`

实时识别工具。打开 MuMu 后跑这个：按 `R` 重新截图 + 跑 `ScreenRecognizer`，在画面上叠加"当前识别为：xxx"。`Q` 退出。`--graph` 不传时用 Phase 2 demo 图。**静态截图驱动，不做视频流。**

### dev_tools/graph_composer.py（开发工具，禁被生产代码 import）⭐

交互式建图工具。CLI：`python dev_tools/graph_composer.py --mumu <root> [--instance N] [--display D] [--account-id ID] [--context-graph mod:fn]`

**核心原则**（CLAUDE.md S3 + Phase 2 spec）：
1. **所有截图通过 `backend.screenshot()`**，禁用 PIL / mss。
2. **完全静态截图驱动**：用户按 `R` 主动刷新，期间不做视频流。
3. **隔离**：模板暂存到 `dev_tools/composer_output/templates_staging/`，用 `P` 一键 promote 到 `templates/`；每次截图存 `composer_output/screenshots/<ts>.png`；草稿即时写入 `composer_output/draft_<session>.py` 和 `state_<session>.json`，崩溃不丢。

**键位**：`R` 刷新 / `V` 标记当前画面为 vertex（含 anchor 模板提取）/ `T` 仅提取模板 / `E` 录制 edge（再选类型 1-6：click_button / wait / press_back / swipe / click_at / compose）/ `W` 对最后一条 edge 加 risky/tag/cost / `U` 撤销最后一步 / `S` 立即保存草稿 / `P` 把 staging 中的模板 promote 到 `templates/` / `H` 帮助 / `Q` 退出（提示保存）。

`click_at` 输出会在草稿里附 "WARNING: hardcoded coordinates" 注释。`press_back` 在 nemu backend 上会抛 `NotImplementedError`，工具会提示改用 `click_button`。

---

### core/cache/manager.py — Phase 3

#### `CacheManager(account_id: str, *, max_bytes=100MB, default_ttl=300.0, clock=time.monotonic)`

字节预算的 LRU + per-entry TTL 缓存。**按 account_id 一个实例**（CLAUDE.md S5），生命周期跟随 `AccountRuntime`。底层不是 `TTLCache`——它按 *条数* 算，截图会撑爆。`CacheManager` 用近似字节大小算预算。

**构造异常**：`ValueError`（`account_id` 空 / `max_bytes <= 0` / `default_ttl < 0`）。

**属性**：`account_id` / `max_bytes` / `total_bytes`（当前已用字节，近似）。

**核心方法**
- `get(key, loader=None, *, ttl=None) -> Any | None`：取；命中则 bump 到 MRU；过期则静默 evict。`loader` 是零参 callable，未命中时**在锁外**调用其结果并存进缓存。`loader` 抛错则原样抛，不写缓存。
- `set(key, value, *, ttl=None) -> None`：插入/覆盖。`ttl=None` 用 `default_ttl`；`ttl<=0` 等价 invalidate。超预算时按 LRU 淘汰；单个 value 超 `max_bytes` 仍然存入但日志告警。
- `set_screenshot(key, image: np.ndarray, *, ttl=60.0) -> None`：糖方法，对 `image` 必须 `np.ndarray`（不是抛 `ValueError`）。默认 TTL 比常规 `set` 短，因为截图很容易过时。
- `invalidate(key) -> bool` / `clear() -> None` / `purge_expired() -> int`。
- `__len__` / `__contains__`（自动剔除已过期）。

**字节估算**：`np.ndarray` 用 `.nbytes`；`bytes`/`bytearray`/`memoryview` 用 `len`；`str` 用 `len(s)*2`；其他用 `sys.getsizeof`。**这是近似值，不是严格上限**——预算只是淘汰触发器。

---

### core/scheduler/plugin_base.py — Phase 3

#### `PluginContext(account_id, backend, navigator, matcher, ocr, cache, logger, extras={}, _stop_event, _pause_event)`（dataclass）

每个 `(account, plugin)` 一份，由 `Scheduler.start_plugin` 构造，作为参数传给 plugin 的所有生命周期方法。**禁止跨方法捕获字段引用做持久状态**（context 在 teardown 后被丢弃，但事件是 worker 拥有的，捕获 `should_stop` 一次是安全的）。

**字段**
- `account_id` *(str, 必填)*：账号 id。
- `backend` *(InputBackend)*：本账号专属 backend，已 connect。
- `navigator` *(Navigator)*：已绑定本账号 backend + 组装好的 graph。
- `matcher` *(TemplateMatcher)*：本账号 backend 的 matcher（模板共享 OK）。
- `ocr` *(OcrEngine | None)*：进程级单例（CLAUDE.md S5 例外）。可能为 None。
- `cache` *(CacheManager)*：本账号专属缓存。
- `logger` *(logging.Logger)*：名字形如 `plugin.<account>.<plugin>`，方便 grep。
- `extras` *(dict)*：自由收纳；插件私有状态可塞这里。
- `_stop_event` / `_pause_event` *(threading.Event)*：worker 拥有，**用 `should_stop()` / `should_pause()` 而非直接读**。

**方法**
- `should_stop() -> bool`：主循环每次迭代必查。
- `should_pause() -> bool`：典型用法是配合 `wait_until_resumed()`。
- `sleep(seconds: float) -> bool` ⭐：可中断 sleep；返回 True iff 期间 stop 被设置（即 `if ctx.sleep(0.5): return` 是早退模板）。`seconds <= 0` 立即返回。底层用 `Event.wait`（monotonic 时基）。
- `wait_until_resumed(*, poll=0.2) -> bool`：阻塞直到 pause 被清除或 stop 被设置；返回 True iff 是 stop 让我们退出。

#### `GameplayPlugin`（abstract base class）

**ClassVars（子类必填）**
- `name: str`：唯一标识 + 图命名空间前缀。不能含 `.`。
- `display_name: str`：日志/UI 显示用；空则 fallback `name`。
- `requires_vertices: List[str]`：全限定 vertex id 列表。worker 启动前 scheduler 验证；缺一个抛 `PluginRequirementUnmet`，不会进 `setup`。

**抽象方法**
- `build_subgraph(cls) -> GameGraph`：classmethod。约定：实现里 `from plugins.<name>.graph import build_subgraph; return build_subgraph()`，让 `graph.py` 当真正的源头。
- `setup(self, ctx)`：一次性 prep，worker 启动后立刻调。抛错则 worker 进 ERROR，**run 跳过，teardown 仍然跑**。
- `run(self, ctx)`：主循环。**必须** 周期性查 `ctx.should_stop()`；理想再查 `ctx.should_pause()`。正常 return = "活干完了"。抛 `BotError` 子类进 ERROR；抛其他异常也是 ERROR（额外 log full traceback）。
- `teardown(self, ctx)`：清理。**无论 run 是否抛错都会跑**，且自身的异常只 log 不再传播（除非 run 没抛错，那这次 teardown 异常就是主因）。

**可选钩子**（默认 no-op）
- `on_pause(self, ctx)`：pause 标志被设置后、plugin 还没察觉前调（在 *调用 pause() 的线程上*）。
- `on_resume(self, ctx)`：resume 后调。

**构造**：插件必须支持 0 参 `__init__`，配置走 `PluginContext.extras` 或 yaml。`GameplayPlugin.__init__` 会校验 `name` 非空且不含 `.`。

**模块函数 `make_logger(account_id, plugin_name)`**：返回 logger 名 `plugin.<account>.<plugin>`，scheduler 给 ctx 用，外部一般不需要。

---

### core/scheduler/registry.py — Phase 3

#### `PluginRegistry()`

扫盘发现 + 类注册 + 子图收集，**进程级共享 OK 但不强求**（只存类，不存实例）。

- `register(plugin_cls)`：手动注册一个类。空 name / 含 `.` / 与已注册的不同类同名 → 抛 `PluginDiscoveryFailed`。重复注册同一个类幂等。
- `discover(plugins_package="plugins", *, skip=None) -> list[type[GameplayPlugin]]`：`pkgutil.iter_modules` 走 `plugins/<x>` 子包，跳过 `__pycache__` 和 dotfiles，import 失败/类校验失败都不抛，**累积到 `self.failed`**。
- `get(name)`：未注册抛 `PluginNotRegistered`。
- `list() -> List[str]`：已注册的 name 排序。
- `failed -> List[PluginFailure]`（dataclass: module / reason / error）：所有未恢复的失败。
- `collect_subgraphs(*, only=None) -> Dict[str, GameGraph]`：调用每个注册插件的 `build_subgraph()`。`only` 限定子集（未知 name 只 warning 跳过）。某个插件 build 抛错 → 不入 result，进 failed。返回非 GameGraph 同样剔除并记 failure。**绝不抛**。

---

### core/scheduler/worker.py — Phase 3

#### `WorkerStatus`（Enum）：`IDLE` / `RUNNING` / `PAUSED` / `STOPPED` / `ERROR`

#### `PluginWorker(plugin, context, *, name=None)`

一个线程包一个插件 + 一个 context。**不可重用**——`stop()` 之后请构造新的 `PluginWorker`。

**属性（线程安全读）**：`plugin` / `context` / `status` / `last_error` / `started_at` / `finished_at` / `is_alive()`。

**方法**
- `start()`：拉起线程。已 RUNNING/PAUSED 或线程还活着抛 `WorkerAlreadyRunning`。会 reset `last_error` + 两个 Event。
- `pause()`：set `_pause_event` + 翻 PAUSED 状态。同步在当前线程跑 `on_pause`（异常只 log）。已 PAUSED / 已 STOPPED / 已 ERROR 都 no-op。
- `resume()`：clear `_pause_event` + 若仍在 PAUSED 则翻回 RUNNING。同步跑 `on_resume`。未在 pause 是 no-op。
- `stop(timeout=10.0) -> bool` ⭐：set stop + clear pause（让卡在 `wait_until_resumed` 的 plugin 立刻醒来）+ join。返回 True iff 在超时内退出。**没退出也不强杀**（Python 不让），日志告警 + 线程保留 daemonic；status 维持当前值（不撒谎说 STOPPED）。**从 IDLE 调 stop 会翻成 STOPPED，方便 scheduler 直接丢弃。**

**线程体**：`setup → run → teardown`。`setup` / `run` 任一抛错：捕获到 `last_error` + 翻 ERROR + 跳过后续阶段；`teardown` 一定跑。**`BotError` 走简短日志，其他异常额外 `traceback.format_exception` 一份**。退出前总是 clear pause event。

---

### core/scheduler/scheduler.py — Phase 3

#### `AccountRuntime(account_id, backend, graph, navigator, matcher, cache, ocr=None)`（dataclass）

per-account 资源捆绑，**由调用方（如 `main.py`）构造**并传给 `Scheduler.register_account()`。Scheduler 自己不构造它，原因是 backend 的 connect/disconnect 应由调用方控制（emergency stop 时不应该断开 device）。

#### `Scheduler(registry, *, graceful_stop_timeout=10.0)`

多账号多插件 worker 管理器 + 命令队列。**内部数据结构**：`{account_id: {plugin_name: PluginWorker}}` —— 哪怕只有一个账号也走这个形状，将来加账号零代码改动。

**调度器自身生命周期**
- `start()`：启动命令队列调度器线程（idempotent）。**不会自动启动 worker**——只是开始消费 `submit()` 来的 callable。
- `shutdown(*, stop_timeout=None)`：`stop_all()` + 关闭 dispatcher。

**账号注册**
- `register_account(runtime: AccountRuntime)`：重复注册同 id 会先 stop 该账号的所有 worker，再替换 runtime。
- `unregister_account(account_id)`：stop 该账号所有 worker，丢弃 runtime + worker 表。
- `registered_accounts() -> List[str]`。

**Worker 控制**（直接调或通过 `submit()`，都线程安全）
- `start_plugin(plugin_name, account_id) -> PluginWorker` ⭐：构造 `PluginContext` + `PluginWorker` + `start()`。校验顺序：`AccountNotRegistered` → `PluginNotRegistered` → `WorkerAlreadyRunning` → `PluginRequirementUnmet`（基于 `plugin.requires_vertices` vs `runtime.graph.has_vertex(...)`）。
- `stop_plugin(plugin_name, account_id, *, timeout=None) -> bool`：没运行就返回 True；否则 worker.stop 的结果。
- `pause_plugin` / `resume_plugin`：no-op 安全。
- `start_all(account_id=None) -> List[PluginWorker]`：**所有 *注册过的* 插件 × 所有 (或指定) 账号**。已经 alive 的 silently skip；其他异常 log 但不中断批次。
- `stop_all(account_id=None, *, timeout=None)`：批量 stop。
- `pause_all` / `resume_all` / `toggle_pause_all`（任一在 PAUSED 则全部 resume，否则把 RUNNING 全 pause —— F9 用这个）。

**状态查询**
- `list_status() -> Dict[acc, Dict[plugin, WorkerStatus]]`：快照。
- `get_worker(plugin_name, account_id) -> PluginWorker | None`。
- `wait_for_idle(timeout=None) -> bool`：轮询 100ms 直到所有 worker 都 `not is_alive()`，或超时。

**命令队列**
- `submit(callable[[], None])`：把 thunk 排队，dispatcher 线程上跑。非 callable 抛 `ValueError`。**dispatcher 吞掉 callable 抛的异常**（log + 继续），所以一个坏 hotkey 不会卡死队列。

---

### core/hotkey/controller.py — Phase 3

#### `HotkeyAction(hotkey, callback, description="")`（dataclass）

一个绑定的快照。`list()` 返回的就是这玩意儿。

#### `HotkeyController(scheduler, *, backend="keyboard")`

**`backend` 取值**
- `"keyboard"`（默认）：用 `keyboard` pip 包。Windows 通常需要管理员权限才能稳定 hook。**包加载失败会自动降级到 "noop" 并 log warning**——主流程不会因为热键不可用就崩。
- `"noop"`：完全不挂 OS hook，只能通过 `trigger()` 程序触发。测试 / 无管理员环境 / CI 都用这个。

**方法**
- `register(hotkey, callback, *, description="") -> None`：绑一个键。重复 key 替换旧绑定；已 `start()` 后会立刻 re-install 新 binding。空 hotkey / 非 callable 抛 `ValueError`。
- `register_defaults()`：装上规范的三个键 ——
  - **F9**：`submit(scheduler.toggle_pause_all)`
  - **F10**：`submit(scheduler.stop_all)`
  - **F12**：`emergency_exit`（best-effort `scheduler.stop_all(timeout=2.0)` → `os._exit(2)`，跳过 atexit/finally；用来在某个 worker 在 C 代码里卡死时仍能退出）
- `list() -> List[HotkeyAction]`：按 hotkey 排序的快照。
- `start()` / `stop()`：装/卸 OS hooks，idempotent。
- `trigger(hotkey)`：测试/CLI 用，直接调对应 callback（callback 抛错只 log）。未注册的 hotkey silent。

**线程模型**：`keyboard` 的事件由其内部线程触发；callback 通过 `scheduler.submit` 立刻把执行权扔给 dispatcher 线程，所以 hook 线程从不阻塞，多个键也不会互相 race。

---

### core/input_backend/fake.py — Phase 3（demo / test 用）

#### `FakeBackend(initial_screen="main_menu", *, account_id="fake", matcher=None)`

`InputBackend` 的内存实现。**仅在 demo / 单测中使用**，禁止在真玩法里 import。状态只有一个 `current_screen` 字符串；fake 的 recognizer（`graphs/_demo_actions`）读它，fake 的 action 写它。截图返回特殊 `_ScreenFrame`（4×4 ndarray 上挂 `_demo_screen` 属性），真 backend 的 `Button` recognizer 不会匹配——这是预期。

`click_xy` / `swipe` / `long_click_xy` / `drag` 都是 no-op（duration<=0 仍然抛 `ValueError`）。`connect/disconnect/is_connected` 是 bool 翻转，没有真 IPC。

## 7. 已知问题与陷阱

- **DLL 截图格式**：返回 BGRA 且上下颠倒。需 `cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)` + `cv2.flip(img, 0, dst=img)`。错过这一步保存的 PNG 颜色异常、上下镜像。
- **DLL 坐标系**：相对 ADB 旋转了 90°。`NemuIpcImpl.down()` 内部已用 `convert_xy()` 处理，调用方传 ADB 坐标即可，**不要自己转**。
- **MuMu 国际版（MuMuPlayerGlobal）不支持 IPC**：本项目仅支持国内版 MuMu 12。Alas 的高层包装类会检测路径含 "MuMuPlayerGlobal" 并拒绝；我们的 wrapper 也应该这么干。
- **DLL 路径差异**：MuMu 12 经典版本 DLL 在 `<root>/shell/sdk/external_renderer_ipc.dll`；MuMu 12 v5.0+ 在 `<root>/nx_device/12.0/shell/sdk/external_renderer_ipc.dll`。`NemuIpcImpl` 会自动按顺序尝试，但传入的 `nemu_folder` 必须是 MuMu 安装**根目录**，不是子目录。
- **vendor 依赖膨胀**：Alas 的 `nemu_ipc.py` 在加载时拉入了 Alas 的整个运行时（ConfigUpdater、Platform、deploy 等），所以 conda env 现装了 ~20 个 pypi 包（adbutils、uiautomator2、pywebio、scipy、rich……）。这是历史包袱，未来切到自研 backend 时可以摘掉。
- **Alas 旧 adbutils 0.11 需要 `pkg_resources`**：所以 `setuptools` 必须 `<81`。在新机器复现时遇到 `ModuleNotFoundError: No module named 'pkg_resources'` 就降 setuptools。
- **Alas logger 启动副作用**：`import vendor.alas.module.logger` 会在 stdout 打印 "START" 横幅、可能写日志目录。Phase 1 的 wrapper 层需要把它隔离/重定向到 `logs/<account_id>/`。
- **Conda 国内镜像有时不稳**：USTC/TUNA 偶尔 SSL/超时。Phase 0 是用代理走 `repo.anaconda.com` 直连 + pip 直连 PyPI 解决的。`.condarc` 上的镜像不一定可靠。
- **`conda run` 在 GBK 终端会崩**：`conda run -n yys <...>` 调用子进程后，conda 试图把 stdout 用 GBK 编码打回终端，遇到非 GBK 字符就 `UnicodeEncodeError`。直接调 `D:\anaconda3\envs\yys\python.exe` 更稳，或先 `$env:PYTHONIOENCODING="utf-8"`。
- **`TM_CCOEFF_NORMED` 对单色模板退化**：纯白/纯黑模板方差为 0，匹配分数处处 NaN 或 1.0，会让 `find_all` 返回成千上万个"匹配"。模板必须带可识别的细节（边框、内部图形、文字等）。已在 `tests/test_template_matcher.py` 的 fixture 里加了图案。
- **`paddleocr` 不在 Phase 1 默认装**：`core/vision/ocr.py` 内部惰性 import，所以 `import core` 不会报错。真要用 OCR 时 `conda run -n yys pip install paddleocr==2.7.3`。`requirements.txt` 已经固定版本。
- **VSCode 默认解释器 ≠ `yys` 环境**：IDE 提示"package not installed"是因为它指向系统 Python310。要么在 VSCode 右下角切到 `D:\anaconda3\envs\yys\python.exe`，要么忽略提示。命令行只用 `yys` python 即可。
- **DSL 与 `merge()` 的分工**：`subgraph()` / `root_graph()` 上下文负责 *所有* 命名空间前缀；`GameGraph.merge()` 已经不再做二次前缀，只做拷贝 + owner 戳 + 命名空间一致性校验。子图内部要引用根命名空间的 vertex（如 `main_menu`，不含点）必须用 `external("main_menu")`，否则会被当成相对名加前缀，merge 后变成 `<plugin>.main_menu` 死边。
- **Ghost endpoint 是合法状态**：跨命名空间 edge 在 merge 之前会在底层 `networkx.DiGraph` 里建出"没有 `vertex` 数据"的占位节点。`GameGraph.vertices()` / `vertex_ids()` 已经自动跳过它们；外部不要直接遍历 `graph.nx.nodes`，要遍历 `graph.vertices()`。`validate()` 会把仍然 ghost 的 endpoint 上的 edge 当 dangling 处理。
- **`press_back()` 在 nemu backend 上不可用**：nemu IPC DLL 只有触摸通道，无系统键。`InputBackend.press_back()` 默认抛 `NotImplementedError`，`NemuIpcBackend` 未重写。需要"返回"语义时用 `click_button(BACK_BTN)`。这是 `graph_composer.py` 在录制 press_back edge 时会主动提示的一种用法。
- **`networkx==3.3` 必须装在 `yys` 环境**：Phase 2 开干前要 `D:\anaconda3\envs\yys\python.exe -m pip install networkx==3.3`。`matplotlib==3.10.9` 也需要装，但只有 `dev_tools/graph_visualizer.py` 用，生产代码绝不 import。
- **`graph_composer` 必须在真模拟器上跑**：工具会真的对模拟器执行点击/滑动来录制 edge——这是录制 edge 的唯一可靠方式，无法 mock 掉。所有调试输出隔离到 `dev_tools/composer_output/`，不会污染正式 `templates/`。

### 线程安全与生命周期（Phase 3 引入）

- **`Navigator` / `PathFinder` / `ScreenRecognizer` 没有内部锁**：约定每个 `(account_id, plugin)` 由它自己的 `PluginWorker` 单线程使用。**禁止**在两个 plugin 之间共享同一个 `Navigator` 实例（Scheduler 自己按账号建一份 Navigator 供该账号所有 plugin 复用——但 plugin 们各跑自己的线程，所以 Navigator 仍可能被并发调用）⚠️——目前 Scheduler 的设计是同一账号上同时跑多个 plugin 时它们共享同一个 Navigator，这是个**潜在线程安全问题**，Phase 4 第一个真插件上线前要么给 Navigator 加锁，要么强制每账号同时只跑一个 plugin。
- **`InputBackend` 的高层方法是线程安全的，但语义上是"独占"**：`click(Button)` 的实现是 screenshot+match+click 三步，多个线程并发调它会拿到同一帧但行动顺序未定。同一账号的 plugin 并发跑也面临这个问题——再次提醒"每账号同时一个 plugin"是 Phase 3 的隐式约束。
- **`TemplateRepository` 跨账号共享是安全的**：模板内容不可变，里头的 LRU 是线程安全的；只在 `dev_tools/template_extractor.py` 写盘后调用 `invalidate(name)` 即可。`CacheManager` 不跨账号，安全。
- **`OcrEngine` 是进程级单例**：内部 RLock 串行化 `recognize` 调用，多线程调安全但**会排队**。OCR 是慢操作，多账号场景下要么池化、要么接受串行。
- **`PluginWorker.stop(timeout=10)` 不强杀**：如果 plugin 忽略 `should_stop()`，线程会保留 daemonic 直到进程退出。F12 用 `os._exit(2)` 是为了这种情况下也能退出。**写 plugin 的人对 `should_stop()` 的频次有责任**——纯 CPU 循环里至少每秒查一次，blocking 操作前必查。
- **`HotkeyController` 在 Windows 上需要管理员**：`keyboard` 包用低层 hook，没管理员时 `import keyboard` 不抛错但 `add_hotkey` 可能失败。控制器会**自动降级 noop 并 log warning**，主进程继续跑——不会因为热键挂了就崩。CI / 服务器跑用 `backend="noop"` 然后通过 `trigger()` 模拟。
- **`Scheduler.start_all` 默认启动 *所有注册过的* 插件**：不传 `account_id` 时，对每个已注册账号 × 每个已注册插件都尝试 `start_plugin`。已经在跑的 silently skip；其他失败会 log 但不中断批次。如果只想启动 enabled 子集，**逐个 `start_plugin` 调用**，别用 `start_all`。
- **`Scheduler` 不会自动 `disconnect` backend**：`shutdown` 只停 worker + dispatcher。Backend 由 `main.py` 负责（典型用 `with backend:` 或 `try/finally`），原因是 emergency stop 的时候不应该切断 device。
- **Plugin name == graph namespace**：插件 `name = "_demo"` ⇒ 它的 vertex 全部前缀 `_demo.`。要在主图里引用，必须用 `"_demo.demo_screen_1"` 这样的全限定 id。**不要**让 plugin 的 `name` 和已有的根 vertex 名重叠（如 `main_menu`），merge 会爆 `GraphValidationError`。
- **`PluginContext.sleep` 是 stop-aware，不是 pause-aware**：pause 时 `sleep` 照样计满 seconds（这是有意——pause 是"暂停业务循环"，不是"无限定阻塞"）。要在 pause 期间挂起，用 `wait_until_resumed(poll=0.2)`。
- **`PluginRegistry.discover` 走 `pkgutil.iter_modules`**：只发现 `plugins/<dir>` 是 Python 包（有 `__init__.py`）的子目录。子目录名以 `__` 开头会被跳过（dunder 保留），但**单下划线开头是 OK 的**（`_demo` 能被发现）。如果新 plugin 不被识别，先检查它有没有 `__init__.py` 并且重新 import。

## 8. 下一步

**Phase 4 目标**：首个真玩法（端到端可跑的业务循环）。

重点关注：
1. **挑一个简单循环作为试点**——例如"每日委托：进入委托界面 → 一键收 → 一键派 → 回主界面"。要求：完全靠图导航 + 模板匹配能跑通，**不依赖 OCR**（OCR 留给更复杂的玩法）。
2. `plugins/<name>/buttons.py`：把所有需要点的按钮、所有需要识别的界面 anchor 全部定义出来。模板用 `dev_tools/template_extractor.py` + `dev_tools/graph_composer.py` 录。
3. `plugins/<name>/graph.py`：用 DSL 构建子图，**必须**和主图 vertex 用 `external(...)` 连起来，避免命名空间漂移成 dangling edge。
4. `plugins/<name>/<name>_plugin.py`：实现 `GameplayPlugin`。`requires_vertices` 写真依赖；`run()` 是真业务循环（不是 demo 那样的来回切屏），每个 navigator 调用前查 `should_stop()`，每个长 `sleep` 用 `ctx.sleep` 而非 `time.sleep`。
5. `graphs/main.py`：把 Phase 2 的 `graphs/_demo.py` 升级成真主图——`main_menu` / `profile` / `shop` / `settings` 等真界面，每个 vertex 配真 `Button` recognizer + 真模板。**Phase 4 之后 `graphs/_demo.py` 可以删，Phase 2 的"假 backend"流程也可以退役**。
6. **真 backend 联调**：把 `main.py` 里的 `FakeBackend` 换成 `get_input_backend(..., "nemu", mumu_folder=...)`，验证 demo 之外的真插件能在 MuMu 上跑起来。先用 `dev_tools/screen_inspector.py` 校准识别再上 plugin。
7. **多账号试运行**：在 config 里注册第二个 `(account_id, instance_id)`，两个 nemu 实例同时跑一遍——验证 §S5 多账号原则没漏。

待解决的设计问题（Phase 3 留下来的）：
- **Navigator 并发**：同一账号上同时跑两个 plugin 会让它们共享 Navigator。要么给 Navigator 加锁（实现简单），要么 Scheduler 强制"每账号同时一个 plugin"（语义清楚但限死扩展性）。Phase 4 选其一。
- **多账号 OCR 串行**：当前 `OcrEngine` 单例 + RLock，多账号同时 OCR 会排队。等出现"OCR 卡死多账号"再加引擎池。
- **`stop_plugin` 不强杀**：plugin 若忽略 `should_stop()` 会泄露线程。给 plugin 写指南或自动检测"长时间不查 should_stop"。
- **配置外置**：目前 `main.py` 的 `_load_config` 是硬编码列表，Phase 4 要换成 YAML（accounts、enabled_plugins、热键自定义、cache 上限），让用户改配置不动代码。

环境层面：
- `keyboard==0.13.5` 已装但**Windows 下非管理员场景会自动降级 noop 并 warning**，不影响开发。CI 上用 `backend="noop"` 通过 `trigger()` 跑测试。
- Phase 4 开干前不需要新装包；如果决定接 OCR，再装 `paddleocr==2.7.3`。
- `dev_tools/graph_composer.py` 在 Phase 4 录新插件图时是主力。每录完一个 vertex / edge 立即在画面上拿 `screen_inspector.py` 校准。
