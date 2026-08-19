# 夸克自动签到项目全面优化分析报告

- 分析基准：`main @ eedd6d8`（已拉取最新，含 WPush Retry 修复）
- 项目规模：1 个 Python 脚本（419 行）、2 个 GitHub Actions workflow、README、LICENSE
- 总体评价：项目经过多轮修复后质量不错（Session 复用、统一请求封装、时区处理、类型防御都已到位），但仍有 **1 个已验证的潜在 bug、1 个日志泄密风险**，以及若干工程化短板。

---

## 一、checkIn_Quark.py（核心脚本）

### 🔴 高优先级

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 1 | **`json` 参数遮蔽标准库，错误处理链断裂（已实测验证）** | `_request()` 签名 `def _request(self, method, url, params=None, json=None)` | 函数内 `except json.JSONDecodeError`（第 215 行）解析到的是**参数**而非 `json` 模块。GET 时参数为 `None`、POST 时为 payload 字典，一旦接口返回非法 JSON，except 子句本身抛 `AttributeError: 'NoneType'/'dict' object has no attribute 'JSONDecodeError'`，绕过所有请求异常处理，直接冒泡到 `main()` 的账号级 try/except，报错信息完全无法定位。**修法**：参数改名 `json_body`（或 `payload`），或模块 `import json` 改为局部引用。 |
| 2 | **公开仓库 Actions 日志泄漏 Cookie 片段** | `parse_cookie_from_url` 第 116 行 `url_str[:80]`；`get_env` 第 147 行 `item[:50]` | 本仓库是 public，Actions 运行日志对任何人都可见。解析失败时打印 URL 前 80 字符，`https://drive-m.quark.cn/1/clouddrive/capacity/growth/info?kps=` 就占了 74 字符，剩余 6+ 字符是 kps 明文开头；多账号场景第 50 字符也会截到 kps。虽是部分泄漏，但 sign/vcode 凭据碎片落日志不合规。**修法**：只打印失败原因 + 参数缺失布尔值，不打印原文；或做脱敏（`re.sub(r'(kps|sign|vcode)=[^&]+', r'\1=***', s)` 后再截断）。 |
| 3 | **配置错误时 `sys.exit(0)`（成功码退出）** | `get_env()` 第 117/125/153 行 | 未配置/解析失败 COOKIE_QUARK 时以退出码 0 结束，语义上是"成功"。当前 workflow 靠 grep `$GITHUB_OUTPUT` 兜底才没出事，但任何依赖退出码的调用方（本地运行、其他 CI）都会误判。**修法**：改 `sys.exit(1)`。 |

### 🟡 中优先级

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 4 | `_request` 成功判定逻辑有漏洞 | 第 223 行 `if result.get("code") != 0 and not result.get("data")` | `code != 0` 但 `data` 非空时会**穿透判定被当作成功**返回 data。对 `growth/sign` 而言，签到失败但响应带 data 时会被误判为签到成功并写入缓存，导致当天不再重试。建议改为 `code != 0` 一律走错误分支，`data` 存在与否不参与成功判定。 |
| 5 | 所有错误统一返回 `{}`，无法区分失败原因 | `_request` 全函数 | Cookie 失效、网络错误、限流、JSON 异常对外表现完全相同，`do_sign` 只能输出笼统提示，排查全靠翻日志。建议返回 `(ok, data, err_type)` 或抛出自定义异常。 |
| 6 | GITHUB_OUTPUT 写入逻辑三处重复 | `main()` 第 393-396 行、`__main__` 第 413-416 行、workflow shell 第 101-108 行 | 同一段"打开文件追加 overall_success="写了三遍，shell 层还 grep 回来再写一遍（同 key 写两次）。建议脚本内提取 `_write_output(key, value)` 函数，shell 层直接信任脚本退出码即可，可删掉 grep 逻辑。 |
| 7 | POST 重试策略作用于非幂等接口 | 第 24-31 行全局 Retry 挂载 | `allowed_methods` 含 POST，`status_forcelist` 含 429/5xx——`growth/sign`（签到）请求超时/502 时会被**自动重复提交**。本场景服务端有当日去重所以无害，但属于"碰巧安全"。建议给签到 POST 单独挂 `Retry(total=0)` 的 adapter，或从 `allowed_methods` 移除 POST（推送接口 WPush 幂等性尚可，签到接口不该重试）。 |

### 🟢 低优先级

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 8 | 死代码/冗余防御 | `get_growth_info`/`get_growth_sign` 的 `isinstance(result, dict)` 判断；`query_balance` 第 275-277 行 else 分支 | `_request` 已保证返回 dict，这些判断永不为假，`query_balance` 的 else 分支不可达。 |
| 9 | `CACHE_FILE` 用 `os.getcwd()` | 第 19 行 | 依赖运行目录，换目录运行脚本会把缓存写到别处。建议 `os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_success_date")`。 |
| 10 | `PYTHONIOENCODING` 设置是安慰剂 | 第 405 行 `os.environ.setdefault` | 该环境变量必须在解释器启动前设置才生效，脚本内设置对当前进程无效（GH Actions ubuntu 默认 UTF-8 所以没暴露）。 |
| 11 | 魔法数字散落 | timeout=20/15、截断 2000/50/80、moduleCode | 建议集中为模块级常量，便于维护。 |
| 12 | `do_sign` 内重复的 `isinstance(x, dict)` 收口 | 第 291-302、320-325 行 | `cap_composition`/`cap_sign`/`updated_cap_composition` 三处同样的"取值 + 判 dict + 兜底"模式，可提取 `_as_dict(value)` 工具函数。 |
| 13 | 纯函数零测试 | `parse_cookie_string`、`parse_cookie_from_url`、`convert_bytes` | 三个纯函数非常适合单测（尤其 URL 解析的 `+`/空格/unquote 边界），当前无任何测试。 |
| 14 | `unquote().replace(" ", "+")` 的隐式 hack | 第 107-108 行 | 假设 kps/sign 值中合法空格应转 `+`，若真实值含空格会被破坏。目前靠经验行为支撑，建议加注释说明来源，避免后人误删。 |

## 二、GitHub Actions Workflows

### 🟡 中优先级

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 15 | **`quark_signin.yml` 授予了未使用的 `actions: write` 权限** | 第 11 行 | 整个签到流程没有调用任何 Actions API（删运行记录的步骤不存在），按最小权限原则应删除，只留 `contents: read`。 |
| 16 | **skip 的运行也会保存缓存** | `cache-save` 步骤 `if: always()` | 已签到跳过的 run 会把恢复出来的旧缓存文件再以当天 key 存一遍（内容相同的重复条目），每天 2 次运行造成缓存条目翻倍。建议 `if: always() && steps.check_sign.outputs.skip == 'false'`。 |
| 17 | 无 `concurrency` 配置 | 两个 workflow | 若上一次运行因 GitHub 调度延迟拖到下一次触发窗口，可能并发跑两个签到。加 `concurrency: { group: quark-signin, cancel-in-progress: false }` 即可。 |
| 18 | `pip install requests` 不锁版本、无 requirements.txt | 第 89 行 | 依赖飘移风险（`requests<2.27` 的 `resp.json()` 异常类型不同，恰好影响 #1 的修复写法）。建议加 `requirements.txt`（`requests>=2.31`）并用 `pip install -r`。 |

### 🟢 低优先级

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 19 | 日期计算重复 | `gen_date` 步骤与 `check_sign` 步骤 | 两处都 `export TZ + date '+%Y-%m-%d'`，`check_sign` 可直接复用 `steps.gen_date.outputs.date_str`。 |
| 20 | `python-version: '3.x'` 不固定 | 第 84 行 | 大版本漂移风险（zoneinfo 需 ≥3.9），建议固定 `'3.12'` 或 `'3.11'`。 |
| 21 | 用完整 cron 字符串判断早晚班 | 随机延迟步骤 | `if [ "${{ github.event.schedule }}" = "0 1 * * *" ]` 脆弱（改 cron 就失效），可改用 `github.event_name` 或直接统一延迟区间。 |

## 三、README.md（文档）

### 🟡 中优先级

| # | 问题 | 说明 |
|---|------|------|
| 22 | **宣传了不存在的功能**："自动清理旧记录：自动删除旧的 Workflow 运行记录" | 仓库中没有任何清理 workflow（这也解释了 #15 的残留权限）。README 第 3️⃣ 节还要求用户开 Read and write permissions 来支撑这个不存在的功能。要么补 workflow，要么删文档。 |
| 23 | **Badge 指向错误仓库** | stars/forks/license/last-commit 四个徽章指向 `Liu8Can`（上游原作），Actions 徽章却指向 `1013608955`（本 fork），fork 用户照抄会显示别人的数据。 |

### 🟢 低优先级

| # | 问题 | 说明 |
|---|------|------|
| 24 | 致谢链接复制错误 | 第 33 行 haozihong 的链接又指向 Spectrollay。 |
| 25 | 重试退避描述与代码不符 | 文档写"0.5s → 1s → 2s"，代码 `backoff_factor=1` 实际是 0s/2s/4s（或 1s/2s/4s，取决于 urllib3 版本）。 |
| 26 | 错别字 | "產生的後果责任"（"後果"繁体混入）。 |

## 四、依赖与冗余文件

| # | 优先级 | 发现 |
|---|--------|------|
| 27 | 🟢 低 | 无 requirements.txt / pyproject.toml（见 #18）。运行时依赖仅 `requests`（自带 urllib3），无冗余包——之前清理 pytz 的工作已做完，现状干净。 |
| 28 | 🟢 低 | 本地 `__pycache__/checkIn_Quark.cpython-313.pyc` 是旧版本编译产物（已在 .gitignore 中，未入库），可删除避免误用。 |
| 29 | 🟢 低 | imports 全部在用，无未使用导入/未使用函数；心跳分支（heartbeat）由单独 workflow 维护，main 分支无冗余。 |

## 五、性能与内存

| # | 优先级 | 发现 |
|---|--------|------|
| 30 | 🟢 低 | **无性能瓶颈**：Session 连接复用已做；脚本生命周期秒级，全局 `_http` 未显式 close 属于进程退出即回收，不构成泄漏。 |
| 31 | 🟢 低 | 多账号串行请求是**合理选择**（并行会放大风控风险），若账号多可在账号间加 2-5s 随机间隔进一步降低风险。 |
| 32 | 🟢 低 | 签到成功后为刷新显示多发 1 次 `growth/info` 请求（每账号 +1 请求），是功能权衡，可接受。 |

## 六、错误处理与边界情况总评

**已覆盖良好**：账号级异常隔离（单账号失败不影响其他）、HTTP/超时/JSON/类型四层异常捕获、时区双保险（Python ZoneInfo + shell TZ）、当日重复签到幂等（sign_daily 检查 + 缓存）、缓存写入失败不阻断流程。

**覆盖缺口**（除高优先级 #1-#3 外）：
- 33 | 🟡 中 | `query_balance` 返回值类型不一致（成功返回 balance 值，失败返回字符串"查询失败"），调用方无法区分"余额为 0"和"查询失败"。
- 34 | 🟢 低 | `resp.text` 在 except 分支通过 `'resp' in locals()` 兜底，可读性差且在连接异常时 `resp` 未定义的场景下仅靠这一招防身——重构 `_request` 时建议先初始化 `resp = None`。

---

## 建议修复顺序

1. **立即**：#1（改名 `json` 参数）+ #3（exit(1)）+ #2（日志脱敏）——都是小改动、高风险收益比
2. **顺手**：#15（删多余权限）、#22/#23（README 修正）、#28（删本地 pyc）
3. **小重构**：#4（成功判定）、#6（输出写入去重）、#8/#12（死代码清理）、#16/#17（workflow 加固）
4. **有空再做**：#18（requirements.txt）、#13（补纯函数单测）、其余低优先级项
