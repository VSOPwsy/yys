# CLAUDE.md — AI 工作记忆

## 1. 产品目标

基于 MuMu 12 国服模拟器的游戏（阴阳师）自动化脚本：通过 nemu IPC（DLL 截图 + 注入触摸）避免 ADB 检测，支持多账号、多玩法热插拔，玩法之间共享图导航。

## 2. 当前进度

- ✅ Phase 0：项目骨架 + IPC 冒烟测试
- ⬜ Phase 1：核心抽象层（InputBackend / Button / 图导航 / Plugin 基类 / 异常体系 / 多账号容器）
- ⬜ Phase 2：图导航系统（NetworkX 实例化、跨命名空间 vertex/edge、最短路径搜索）
- ⬜ Phase 3：Plugin 与线程（Worker 池、命令队列、停止 Event、热加载）
- ⬜ Phase 4：首个玩法（一个完整的可跑业务循环）

## 3. 强制开发纪律（每次工作必读）

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
│   ├── input_backend/             # Strategy 模式：抽象输入接口 + 具体实现（nemu_backend.py）。
│   ├── vision/                    # 视觉栈：Button、模板匹配、OCR 适配器。
│   ├── navigation/                # 图导航：vertex/edge 模型、路径搜索、跨命名空间合并。
│   ├── scheduler/                 # 调度：Plugin 基类、Worker 线程、命令队列。
│   ├── hotkey/                    # 全局热键（启动/暂停玩法）。
│   └── cache/                     # 带 TTL 的内存缓存。
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

## 7. 已知问题与陷阱

- **DLL 截图格式**：返回 BGRA 且上下颠倒。需 `cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)` + `cv2.flip(img, 0, dst=img)`。错过这一步保存的 PNG 颜色异常、上下镜像。
- **DLL 坐标系**：相对 ADB 旋转了 90°。`NemuIpcImpl.down()` 内部已用 `convert_xy()` 处理，调用方传 ADB 坐标即可，**不要自己转**。
- **MuMu 国际版（MuMuPlayerGlobal）不支持 IPC**：本项目仅支持国内版 MuMu 12。Alas 的高层包装类会检测路径含 "MuMuPlayerGlobal" 并拒绝；我们的 wrapper 也应该这么干。
- **DLL 路径差异**：MuMu 12 经典版本 DLL 在 `<root>/shell/sdk/external_renderer_ipc.dll`；MuMu 12 v5.0+ 在 `<root>/nx_device/12.0/shell/sdk/external_renderer_ipc.dll`。`NemuIpcImpl` 会自动按顺序尝试，但传入的 `nemu_folder` 必须是 MuMu 安装**根目录**，不是子目录。
- **vendor 依赖膨胀**：Alas 的 `nemu_ipc.py` 在加载时拉入了 Alas 的整个运行时（ConfigUpdater、Platform、deploy 等），所以 conda env 现装了 ~20 个 pypi 包（adbutils、uiautomator2、pywebio、scipy、rich……）。这是历史包袱，未来切到自研 backend 时可以摘掉。
- **Alas 旧 adbutils 0.11 需要 `pkg_resources`**：所以 `setuptools` 必须 `<81`。在新机器复现时遇到 `ModuleNotFoundError: No module named 'pkg_resources'` 就降 setuptools。
- **Alas logger 启动副作用**：`import vendor.alas.module.logger` 会在 stdout 打印 "START" 横幅、可能写日志目录。Phase 1 的 wrapper 层需要把它隔离/重定向到 `logs/<account_id>/`。
- **Conda 国内镜像有时不稳**：USTC/TUNA 偶尔 SSL/超时。Phase 0 是用代理走 `repo.anaconda.com` 直连 + pip 直连 PyPI 解决的。`.condarc` 上的镜像不一定可靠。

## 8. 下一步

**Phase 1 目标**：搭核心抽象层，让"截图 + 模板匹配 + 按钮点击 + 异常体系"形成最小可工作闭环，并满足多账号就绪原则。

重点关注：
1. `core/exceptions.py`——定义异常层级（`YysError` 根 → `BackendError`、`VisionError`、`NavigationError`、`PluginError` 等）。把 `NemuIpcError` 适配进来。
2. `core/input_backend/base.py` + `core/input_backend/nemu_backend.py`——抽象 + nemu 实现，构造签名带 `account_id`，禁止类级状态。
3. `core/vision/button.py`——`Button` 类（模板路径 / 阈值 / 搜索区域 / 点击偏移 / 后置延迟）。
4. `core/vision/template_matcher.py`——cv2.matchTemplate 包装，含缓存。
5. `core/cache/lru.py`——带 TTL 的 LRU（截图、模板都用得上）。
6. 一两个端到端集成测试：开 MuMu → 截图 → 匹配一个测试模板 → 点击。

环境层面：
- Phase 1 需要 paddleocr。Phase 1 装它之前先在 `requirements.txt` 里固定版本。
