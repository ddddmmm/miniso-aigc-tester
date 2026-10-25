# 名创优品 AIGC 营销素材测试工具

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Web%20UI-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

面向品牌营销场景的 AIGC 素材（**商品图 / IP 创意图 / 视频分镜 / 短视频**）生成效果测试与验收工具。
把"生成 → 记录 → 复核 → 报告"串成一条可复现的流水线，同时提供 **命令行（CLI）** 和 **网页（Streamlit）** 两种入口，共用同一套核心代码。

---

## 一、项目背景

品牌营销团队用 AI 大量生成商品图、IP 图和视频素材时，会遇到两个现实问题：

1. **生成效果难量化**：一张图"好不好"靠口头描述，没有统一标准，无法横向比较；
2. **问题难复现**：某次生成出现主体残缺、角色走样、文字乱码，关掉页面就无法还原，也说不清是提示词、参数还是接口的问题。

本工具把每次生成当作一次"测试用例"：用模板固化提示词、自动记录每轮参数和接口响应、按统一维度打分、生成可分享的 HTML 报告，并支持**回归对比**（同一用例再次执行时，自动标出退化项），让 AIGC 素材的质量验收变得可量化、可追溯。

---

## 二、核心能力

- **双形态入口**：同一套核心逻辑，CLI 负责自动化 / 批量 / 回归，Streamlit 负责可视化生成、上传参考图、打分和看报告。
- **三种模型提供方（Provider）**：
  - `mock`（默认）：**离线、不联网、不花钱**，返回内置样例图，用于跑通流程和自动化回归；
  - `openai`：对接 OpenAI 兼容接口（gpt-image-1 / DALL·E 系列）；
  - `ark`：对接火山引擎豆包 Seedream（国内网络直连，已接入真实出图）。
- **提示词模板库**：12 个 Markdown 模板，覆盖商品图、IP 创意图、视频分镜三大类，每个模板含固定结构和可直接使用的示例。
- **批量测试**：一份 YAML 测试套件（含多轮调参、跳过、异常用例），逐轮执行并自动写 JSONL 日志。
- **复核打分**：9 个评分维度直接对应"主体 / 构图 / 风格 / 文字 logo / 角色一致性 / 镜头衔接"等审核要点，自动生成预填打分表。
- **HTML 报告**：自包含单文件（图片 base64 内嵌），含通过率、各维度均分、用例明细、问题清单，并支持与上次结果做回归对比。

---

## 三、岗位 JD 对照表

| 招聘岗位职责 | 本项目对应实现 |
|---|---|
| 调试图片 / 视频 Skills、提示词、参考素材、参数与 Python 脚本，验证模型调用与生成流程 | `providers.py` 多 Provider 封装、`templates/` 模板库、`--reference` 参考图、`generate` / `video` 命令，已跑通 mock 与火山真实调用 |
| 复核图片主体 / 构图 / 风格、视频动作 / 镜头衔接 / 角色一致性并记录问题 | `review.py` 的 9 个评分维度与问题清单，Streamlit 复核页可直接打分 |
| 整理测试样例、复现多轮交互与异常、结合日志和接口响应定位、回归验证 | `testcases/smoke.yaml`（含多轮、空提示词、非法尺寸异常）、JSONL 日志、`report.py` 回归对比自动标红 |
| 维护 Skill 文件、提示词模板与测试记录，协助 API 联调与发布验收 | 模板 / 用例 / 报告分层目录，配置化 Key 管理，HTML 报告可直接用于验收交付 |

---

## 四、快速开始

**环境要求**：Python 3.12 及以上，Windows / macOS / Linux 均可。

```powershell
# 1. 克隆（或解压）后进入项目目录
cd miniso-aigc-tester

# 2. 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 以可编辑模式安装（自动装好全部依赖，注册 aigc 命令）
pip install -e .

# 4. 跑通离线 mock 全流程（无需任何 Key，不联网）
aigc run          # 批量执行测试套件，生成图片 / 视频并写日志
aigc review       # 依据运行结果生成复核打分表
aigc report       # 生成自包含 HTML 报告
```

执行完用浏览器打开 `reports/` 目录下最新的 `.html` 文件即可查看报告。

---

## 五、使用说明

### 5.1 命令行（CLI）

```powershell
# 生成单张图片（默认 mock，离线）
aigc generate "名创优品香薰机，白色极简，木质桌面，温暖自然光"

# 指定模型 / 尺寸 / 输出
aigc generate "圣诞小熊促销图" --model gpt-image-1 --size 1536x1024 --output outputs/bear.png

# 带参考图（图生图，保证商品 / IP 一致性）
aigc generate "同一商品换个场景" --reference references/product.png

# 批量执行测试套件
aigc run --suite testcases/smoke.yaml

# 生成视频（mock 模式输出占位 GIF）
aigc video "盲盒开箱短视频，8 个镜头" --size 9:16 --duration 40

# 配置管理
aigc config show
aigc config set ark_api_key "你的火山Key"
aigc config path
aigc version
```

### 5.2 网页（Streamlit）

```powershell
streamlit run app.py
```

浏览器自动打开后，左侧切换 Provider 和素材类型，页面包含：

- **首页**：选模板 → 编辑提示词 → 上传参考图 → 生成 → 保存；
- **批量测试**：选择套件一键执行，查看每条用例状态；
- **复核打分**：按维度拖动滑块打分、记录问题；
- **报告查看**：在线预览并下载 HTML 报告。

---

## 六、接入真实模型

默认 `mock` 即可使用全部功能。需要真实出图时：

- **火山引擎豆包（推荐，国内直连）**：在[火山方舟控制台](https://console.volcengine.com/ark)开通 Seedream 模型，把 Key 写入配置：
  ```powershell
  aigc config set ark_api_key "ark-你的Key"
  aigc generate --provider ark "名创优品保温杯，纯白背景，商品居中"
  ```
  也可通过环境变量 `AIGC_API` / `ARK_API_KEY` 提供。
- **OpenAI**：`aigc config set openai_api_key "sk-..."`，调用时加 `--provider openai`。

> 真实出图按调用计费，未成功输出的图片不计费。

---

## 七、复核评分维度

| 场景 | 评分维度（每项 1~5 分，5 最好） |
|---|---|
| 商品图 | 主体准确性、构图、风格一致性、文字与 logo 正确性 |
| IP 创意图 | 上述 4 项 + 角色五官 / 服装 / 配色一致性 |
| 视频 | 动作流畅度、镜头衔接、角色一致性、分镜还原度 |

平均分 ≥ **3.5** 判定该用例通过。

---

## 八、目录结构

```
miniso-aigc-tester/
├── app.py                     # Streamlit 首页
├── pages/                     # Streamlit 子页面（批量测试 / 复核打分 / 报告查看）
├── src/aigc_tester/           # 核心代码包
│   ├── cli.py                 # 命令行入口（generate / run / video / review / report / config）
│   ├── providers.py           # 模型提供方：mock / openai / ark
│   ├── testcase.py            # 测试用例数据模型（Pydantic）
│   ├── runner.py              # 批量执行引擎（多轮 / 异常 / 日志）
│   ├── review.py              # 复核维度与打分表
│   ├── report.py              # HTML 报告与回归对比
│   └── config.py              # 持久化配置
├── templates/                 # 提示词模板（商品图 / IP 创意图 / 视频分镜）
├── testcases/smoke.yaml       # 冒烟测试套件
├── references/                # 参考图（图生图用）
├── assets/                    # mock 内置样例图
├── outputs/                   # 生成产物（图片 / GIF）
├── logs/                      # JSONL 运行日志
├── reviews/                   # 复核打分表（YAML）
├── reports/                   # HTML / JSON 报告
├── tests/                     # 自动化测试
└── pyproject.toml
```

---

## 九、测试

```powershell
pytest -q
```

核心模块均有自动化测试覆盖，离线即可运行（不依赖真实 Key）。

---

## 十、待改进方向

- 接入火山引擎 **Seedance 真实视频生成**（当前视频为 mock 占位，真实接口为"创建任务 → 轮询"的异步模式）；
- 支持更多模型与平台，并做同场景多模型效果横向对比；
- 引入基于规则 / 模型的**自动初评**，减少人工打分工作量；
- 报告增加成本统计、趋势图与历史版本管理；
- 支持 CI 中自动跑回归，把质量门集成到发布流程。

---

## License

本项目基于 [MIT License](LICENSE) 开源。
