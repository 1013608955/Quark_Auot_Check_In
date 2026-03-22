# ⭐️ 夸克网盘自动签到

![GitHub stars](https://img.shields.io/github/stars/Liu8Can/Quark_Auot_Check_In) ![GitHub forks](https://img.shields.io/github/forks/Liu8Can/Quark_Auot_Check_In) ![License](https://img.shields.io/github/license/Liu8Can/Quark_Auot_Check_In) ![Last Commit](https://img.shields.io/github/last-commit/Liu8Can/Quark_Auot_Check_In) ![GitHub Actions](https://github.com/Liu8Can/Quark_Auot_Check_In/actions/workflows/quark_signin.yml/badge.svg)

★ 已修复：签到成功后显示最新总容量和签到累计值。

✨ **本项目实现了夸克网盘的自动签到功能**，通过 GitHub Actions 自动执行，领取每日签到奖励空间，让用户无需手动操作！

> 🔨 **关于此修复版本**：
> - 当前版本已修复签到成功后的数据显示问题
> - 签到成功后会重新获取最新的总容量和签到累计值
> - 确保展示的数据为签到成功后的当前值

> 💡 **用户必读**：
> 如果你需要修复签到后的数据显示问题，请下载修复版本的代码。
> 否则使用原版本就可以。

■ 本项目依次修复了原作者的项目。

---

## 🚀 功能简介

- **每日自动签到**：定时运行脚本完成每日签到，领取成长奖励。
  - **新增：每日两次签到尝试**：分别在北京时间早上 9 点和下午 1 点左右尝试签到，增加成功率。
  - **新增：防止重复签到**：脚本会记录当日成功签到状态，避免不必要的重复执行。
  - **新增：随机延迟执行**：每次签到前加入随机延迟，模拟人工操作，降低被检测风险。
- **GitHub Actions 托管**：一键配置后，脚本每天自动运行，实现真正的“一勤永利”。
  - **新增：自动保持仓库活跃**：通过空提交防止 GitHub因仓库不活跃而禁用 Actions。
  - **新增：自动清理旧记录**：自动删除旧的 Workflow 运行记录，保持 Actions 页面整洁。
- 本项目基于 BNDou大佬的项目中夸克网盘自动签到的子功能 https://github.com/BNDou/Auto_Check_In 修改而来
- 感谢  [Spectrollay](https://github.com/Spectrollay) 对工作流的优化
- 感谢  [haozihong ](https://github.com/Spectrollay) 对工作流的优化

---

## 📋 使用指南

### 1️⃣ Fork 项目

点击右上角的 `Fork` 按钮，将本项目复制到自己的 GitHub 仓库。

### 2️⃣ 配置 Cookie 信息

通过 GitHub Secrets 配置用户的 Cookie 信息，具体步骤如下：

#### 🛠️ 获取 COOKIE_QUARK

使用手机抓包工具（小白推荐 [proxypin](https://github.com/wanghongenpin/proxypin)）获取 Cookie 信息：

1. 打开手机抓包工具，访问夸克网盘签到页。
2. 找到接口 `https://drive-m.quark.cn/1/clouddrive/capacity/growth/info` 的请求信息。
3. **推荐方式**：直接复制该请求的完整 URL（包含 `kps`、`sign`、`vcode` 参数）。
4. **或手动整理参数**：复制请求中的 `kps`、`sign` 和 `vcode` 参数。

#### 🔒 配置格式说明

将获取到的信息整理为以下两种格式之一（推荐方式一）：

**方式一：直接粘贴抓包的完整 URL（推荐，脚本自动解析）**
https://drive-m.quark.cn/1/clouddrive/capacity/growth/info?kps=xxx&sign=xxx&vcode=xxx

**方式二：手动整理参数**
kps=abcdefg; sign=hijklmn; vcode=111111111;
plaintext

> 注意：
> - 方式二中无需填写 `user` 字段，脚本会自动按顺序编号。
> - **多账号配置**：多个账号可用 **换行符 `\n`** 或 **`&&`** 分隔。

#### 🔐 添加到 GitHub Secrets

1. 打开 Fork 后的仓库，进入 **Settings -> Secrets and variables -> Actions**。
2. 点击 **Repository secrets** 区域下的 **New repository secret** 按钮。
3. 创建命名为 `COOKIE_QUARK` 的 Secret。
4. 将整理好的 Cookie 信息粘贴到 "Secret" 输入框中并保存。

---

### 3️⃣ 启用 GitHub Actions 及设置权限

1. 打开 Fork 后的仓库，进入 **Actions** 选项卡。如果看到黄色的提示条 "Workflows aren't right ....... enable them"，点击 **"I understand my workflows, go ahead and enable them"** 按钮启用 Actions。
2. **重要：设置 Workflow 权限**
   * 进入仓库的 **Settings -> Actions -> General** 页面。
   * 在 "Workflow permissions" 部分，选择 **"Read and write permissions"**。
   * 点击 "Save" 保存。
   * **此步骤是必需的**，以便 Actions 能够执行“保持仓库活跃”（空提交）和“清理旧的工作流记录”等操作。
3. 启用后，你会看到命名为 `Quark签到` (or `Quark Sign-in`) 的工作流已配置完成。
4. 脚本将按预设时间（北京时间每日约 9:00 和 13:00）自动运行。
   * **运行时间说明**：默认设置在北京时间上午 9 点和下午 1 点左叶运行。由于 GitHub Actions 的计划任务调度机制，实际运行时间可能会有几分钟到几十分钟的延迟，这是正常现象。随机延迟的加入些也会影响确切的启动时间。
   * **执行逻辑**：脚本会先检查当天是否已成功签到。如果已签到，则跳过后续的签到操作。

### 4️⃣ 手动测试运行

1. 进入 **Actions** 选项卡，点击左侧的 `Quark签到` (or `Quark Sign-in`) 工作流。
2. 点击右侧的 **Run workflow** 按钮，然后再次点击绿色 **Run workflow** 按钮，手动触发任务以验证配置是否成功。
3. 你可以点击运行中的 workflow 查看其执行日志和状态。

---

## ❓ 常见问题

1. **签到失败**：

   * 确认 `COOKIE_QUARK` Secret 中的信息准确无误且格式正确。
   * Cookie 可能已过期，请尝试重新抓取并更新 Secret。
   * 检查 Actions 日志，看是否有具体的错误信息。
2. **GitHub Actions 未生效或报错 `Permission denied` / `GH006`：

   * 确保已按照【3️⃣ 启用 GitHub Actions 及设置权限】中的步骤启用了 Actions。
   * **最常见原因：**确保在仓库的 "Settings -> Actions -> General" 中，"Workflow permissions" 已设置为 **"读取和写入权限"**。如果权限不足，空提交和清理记录步骤会失败。
   * 检查 Actions 运行日志，查看具体的错误信息。
3. **Workflow 显示跳过 (Skipped)**：

   * 这是新版功能的正常行为。如果当天的第一次签到尝试（例如上午9点的任务）已经成功，那么下午1点的任务在检查时会发现已签到，从而跳过实际的签到步骤。你可以在 `check-if-already-signed` job 的日志中看到类似 "今天已成功签到，跳过执行" 的信息。

---

## ⚠️ 注意事项

- 本项目仅供学习交流，请勿用于非法用途。
- 如夸克网盘更新接口，需重新获取 Cookie 并调整代码（主要是 `checkIn_Quark.py` 脚本，Workflow 通常无需修改）。
- 频繁手动触发可能会被目标服务限制，请谨慎操作。

---

## 📝 免责声明

本项目为开源项目，作者不对任何因使用本项目产生的後果责任。

---

### 🛡️ 防盗声明

本项目严格遵守 MIT 协议，修改和分发时必须保留原作者订名及协议声明。
若发现违反行为，请通过以下方式联系：
📧 Email: [liucan01234@gmail.com](mailto:liucan01234@gmail.com)

---

✨ **欢迎提交 PR 和 Star 支持项目发展！**

---

## 🐛 修复内容说明

本修复版本主要修复了以下问题：

1. **签到成功后显示的数据不准确**：
   - 原版本在签到成功后仍使用签到前的总容量和签到累计值
   - 修复版本会在签到成功后重新获取最新的 `growth_info` 数据
   - 确保显示的总容量（total_capacity）和签到累计（sign_reward）为签到后的当前值

2. **显示格式保持不变**：
   - 修复前：`🔍 普通用户 | 总容量: 16.68 GB | 签到累计: 2.68 GB`（实际签到成功后应该是 `2.70 GB`）
   - 修复后：`📱 第1个账号 → 🔍 普通用户 | 总容量: 16.70 GB | 签到累计: 2.70 GB | ✅ 签到成功 | 获得: 20.00 MB | 连签进度: 5/7`（数据更准确）

### 示例对比

**修复前（老版本）**：
```
📱 第1个账号
🔍 普通用户 | 总容量: 16.68 GB | 签到累计: 2.68 GB
✅ 签到成功 | 获得: 20.00 MB | 连签进度: 5/7
```
问题：签到累计显示 2.68 GB 是签到前的值，签到成功后应为 2.70 GB。

**修复后（新版本）**：
```
📱 第1个账号
🔍 普通用户 | 总容量: 16.70 GB | 签到累计: 2.70 GB
✅ 签到成功 | 获得: 20.00 MB | 连签进度: 5/7
```
✅ 数据准确，反映签到成功后的最新状态。

---

## 📦 下载与更新

1. **下载修复版本**：直接克隆此仓库即可获得修复后的代码
2. **在原仓库应用修复**：将 `checkIn_Quark.py` 中 `do_sign()` 方法的签到成功分支中的代码替换为修复版本。

---

🎉 感谢使用！如有问题请提 Issue。
