# NBER Public Econ Radar

这是一个面向公共经济与公共管理方向的 NBER 文献筛选与推送 MVP。

功能：

- 抓取 NBER Working Papers RSS；
- 按公共财政、公共管理、政策评估、教育、健康、劳动、城市、分配、环境规制、政治经济、中国研究等方向打分；
- 每篇文献生成 3 条中文 highlights，每条不超过 10 个汉字；
- 提供 Streamlit 本地网页面板；
- 支持导出 Markdown 和 CSV；
- 支持收藏/忽略反馈记录；
- 支持命令行生成 weekly digest；
- 可通过 SMTP 环境变量发送邮件。

## 1. 安装

```bash
cd nber_public_econ_radar
python -m venv .venv
source .venv/bin/activate  # Windows 用 .venv\\Scripts\\activate
pip install -r requirements.txt
```

## 2. 启动本地网页

```bash
streamlit run app.py
```

打开网页后，点击左侧“抓取并筛选”。

## 3. 命令行生成推送稿

```bash
python cli.py --max-papers 50 --min-score 50
```

生成结果会放在：

```text
output/nber_public_econ_YYYY-MM-DD.csv
output/nber_public_econ_YYYY-MM-DD.md
```

## 4. 邮件推送

先设置环境变量：

```bash
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USER="your_email@example.com"
export SMTP_PASSWORD="your_password_or_app_password"
export EMAIL_FROM="your_email@example.com"
export EMAIL_TO="receiver@example.com"
```

然后运行：

```bash
python cli.py --max-papers 50 --min-score 50 --send-email
```

## 5. 定时推送示例

Linux/macOS 可以用 crontab：

```bash
0 9 * * 1 cd /path/to/nber_public_econ_radar && /path/to/.venv/bin/python cli.py --max-papers 50 --min-score 50 --send-email
```

含义：每周一上午 9 点运行。

## 6. 当前版本说明

本版本不下载 NBER 全文，只处理公开元数据、题名、摘要和链接。这样更稳妥，也避免访问权限问题。

当前 highlights 是规则生成版，不需要 API key。后续可以升级为 LLM 版：输入题名、摘要和 NBER program，输出相关性理由和更自然的 highlights。

## 7. 推荐阈值

- `--min-score 35`：适合选题扫描，召回更多；
- `--min-score 50`：适合每周推送，噪音较少；
- `--min-score 70`：只看强相关文献。
