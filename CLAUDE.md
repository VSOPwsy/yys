# CLAUDE.md — AI 工作记忆

## 1. 产品目标

基于 MuMu 12 国服模拟器的游戏（阴阳师）自动化脚本：通过 nemu IPC（DLL 截图 + 注入触摸）避免 ADB 检测，支持多账号、多玩法热插拔，玩法之间共享图导航。

## 2. 当前进度

- ✅ Phase 0：项目骨架 + IPC 冒烟测试
- ✅ Phase 1：核心抽象层（异常体系 / 日志 / TTL 缓存 / Button / TemplateRepository / TemplateMatcher / OCR / InputBackend 抽象 + NemuIpcBackend / 工厂 / dev_tools 模板提取与匹配调试 / 52 项单元测试）
- ⬜ Phase 2：图导航系统（NetworkX 实例化、跨命名空间 vertex/edge、最短路径搜索）
- ⬜ Phase 3：Plugin 与线程（Worker 池、命令队列、停止 Event、热加载）
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
│   ├── exceptions.py              # 异常树根 BotError 及全部子类（Phase 1）。
│   ├── logging_config.py          # setup_logging / get_logger，彩色 + 按天滚动（Phase 1）。
│   ├── input_backend/             # Strategy 模式：抽象输入接口 + 具体实现（nemu_backend.py）+ 工厂。
│   ├── vision/                    # 视觉栈：Button、TemplateRepository、TemplateMatcher、OcrEngine。
│   ├── navigation/                # 图导航：vertex/edge 模型、路径搜索、跨命名空间合并。
│   ├── scheduler/                 # 调度：Plugin 基类、Worker 线程、命令队列。
│   ├── hotkey/                    # 全局热键（启动/暂停玩法）。
│   └── cache/                     # 带 TTL 的内存缓存（lru.py: TTLCache）。
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

## 8. 下一步

**Phase 2 目标**：基于 NetworkX 搭起图导航层。

重点关注：
1. `core/navigation/vertex.py` / `edge.py`——`Vertex` = 稳定 UI 状态（如 `main.main_menu`、`plugins.daily.entry`），`Edge` 持有 `action`（`Button` 引用或 lambda(backend) 回调）、`cost`（耗时）、`risky`（消耗资源）。
2. `core/navigation/graph.py`——`Navigator` 类，按账号构造（多账号就绪）。内部用 `networkx.DiGraph`。支持 `register_vertex(qualified_name, ...)`、`register_edge(src, dst, ...)`、`shortest_path(src, dst, avoid_risky=True)`。
3. **命名空间合并**：主图（`graphs/main.py`）只注册全局骨架；插件子图（`plugins/<name>/graph.py`）注册自己的 vertex，引用别人 vertex 必须用全限定名 `<plugin>.<vertex>`。**重复定义即报错**。
4. `core/navigation/runner.py`——`travel(navigator, target_vertex)`：拿当前截图 → 识别当前 vertex → 沿最短路径执行 edges → 每步后验证到达。失败时抛 `NavigationError` 子类（`NoPathFound`、`UnknownVertex`、`EdgeExecutionFailed`）。
5. `tests/test_navigation_*.py`——纯图操作单元测试 + 一个模拟 backend 的集成测试。

环境层面：
- `networkx==3.3` 已在 `requirements.txt`，但**还没装**。开始 Phase 2 前：`D:\anaconda3\envs\yys\python.exe -m pip install networkx==3.3`。
