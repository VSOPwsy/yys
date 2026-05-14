# 每日签到插件 (daily_reward)

Phase 4 的参考实现。把"每日签到 / 领取每日奖励"这条最短业务回路完整地跑一遍，作为后续玩法的模板。

## 1. 目标流程

```
任意界面
    │  navigator.goto("daily_reward.sign_in_panel", humanize=True)
    ▼
签到面板
    │  is_already_claimed(ctx)?  ── 是 ──┐
    │                                     │
    │  否：click(CLAIM_TODAY_BTN)         │
    │       read_reward_count(ctx) (OCR) │
    │       click(CONFIRM_REWARD_BTN)     │
    ▼                                     │
返回主界面 ◄──────────────────────────────┘
```

成功结束 → worker 进入 STOPPED；任何未预期异常都会被 `handle_unexpected_error` 拦住，先存截图到 `logs/<account>/error/`，再尝试最多 3 次 `recover_to_main`。

## 2. 依赖的图节点

`requires_vertices`：

- `main_menu`（根命名空间，由 `graphs/main.py` 注册）
- `daily_reward.sign_in_panel`（本插件子图）

Scheduler 在启动 worker **前**做存在性校验；缺一个就 `PluginRequirementUnmet` 不进 `setup`。

## 3. 模板清单（必须先抠出来）

工具：`python dev_tools/template_extractor.py --mumu <root>`
落点：`templates/daily_reward/`、`templates/main/`

| 模板逻辑名 | 用途 | 抓取建议 |
| --- | --- | --- |
| `main/main_menu_anchor` | `main_menu` 顶点的识别锚点 | 主界面左上角 LOGO / 角标这类只在主界面出现的元素 |
| `main/sign_in_entry_btn` | 主界面 → 签到面板的入口按钮 | 主界面右上活动栏里的"签到"图标，最好框紧 |
| `main/home_return_btn` | 子界面返回主界面 | 通用左上角"家"图标 |
| `main/close_popup_btn` | 通用关闭弹窗 'X' | 常规弹窗右上角的关闭按钮 |
| `daily_reward/sign_in_panel_anchor` | `sign_in_panel` 顶点识别锚点 | "签到"标题栏 / 日历表格独有 chrome |
| `daily_reward/already_claimed_anchor` | 已签到状态识别 | 已领取后覆盖在领取按钮上的"已领取/✔"图标 |
| `daily_reward/claim_today_btn` | 领取今日 | "领取"主按钮 |
| `daily_reward/confirm_reward_btn` | 奖励弹窗确认 | "好的"或弹窗右上角 X |
| `daily_reward/sign_in_close_btn` | 关闭签到面板 | 签到面板自身的关闭按钮 |

> **小提示**：模板要带可识别细节（边框、文字），全白/全黑会让 `TM_CCOEFF_NORMED` 退化。详见 CLAUDE.md §7。

## 4. OCR 配置（可选）

`read_reward_count` 依赖 `ctx.ocr`（PaddleOCR 单例）。如果 OCR 未装，函数返回 `None`，不影响主流程。

启用 OCR：

```powershell
conda run -n yys pip install paddleocr==2.7.3
```

读取区域定义在 `buttons.py` 的 `REWARD_COUNT_REGION`，默认按 1280x720 设。如果你的模拟器分辨率不同，调整这个常量（或者用 `dev_tools/template_extractor.py` 在裁剪后查看坐标）。

## 5. 联调步骤

1. 在 `config/config.yaml` 里把 `daily_reward.enabled` 设成 `true`，确认 `mumu_folder` 和 `instance_id` 对你的环境。
2. 按"模板清单"用 `dev_tools/template_extractor.py` 抠出全部 PNG。
3. 用 `dev_tools/screen_inspector.py` 校准每个 vertex 的识别锚点：
   ```powershell
   D:\anaconda3\envs\yys\python.exe dev_tools/screen_inspector.py --mumu <root> --graph graphs.main:build_main_graph
   ```
   在主界面按 `R`，看是否能识别成 `main_menu`；切到签到面板后按 `R`，看是否能识别成 `daily_reward.sign_in_panel`。
4. 跑一遍：
   ```powershell
   D:\anaconda3\envs\yys\python.exe main.py
   ```
   按 F9 / F10 / F12 验证暂停 / 停止 / 紧急退出。

## 6. 已知限制

- **press_back 不可用**：nemu IPC DLL 没有系统键通道，关闭面板用 `click_button(SIGN_IN_CLOSE_BTN)`，不是 `press_back`。详见 CLAUDE.md §7。
- **OCR 是串行单例**：多账号并发跑时 `read_reward_count` 会排队。Phase 4 默认每账号同时只跑一个插件，所以暂时不是瓶颈。
- **奖励数量 OCR 仅 best-effort**：因为奖励本质上由 click 完成，OCR 只是写日志记数。脚本不会因为 OCR 失败而判定签到失败。

## 7. 调整 / 扩展

- 想把签到改成"领完直接退出脚本"而不是"回主界面继续下一个插件"——在 `run()` 末尾直接 `return`，**不要** `sys.exit()`。worker 自然进入 STOPPED，调度器会移到下一个账号。
- 想换"星期几只领特定奖励"——OCR `read_reward_count` 之前加一个 `date.today().isoweekday()` 判断，决定是否点击 `CLAIM_TODAY_BTN`。
- 想把这个插件改成可重入（用户手动触发）——把 `setup` 里 `self.claimed = False` 的重置保留即可，类已经支持 stop → 重新 start。
