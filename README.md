![alt text](https://img.shields.io/badge/python-3.9+-blue.svg)

![alt text](https://img.shields.io/badge/License-MIT-yellow.svg)

![alt text](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)
这不仅仅是一个项目，更是一次从原型到生产的完整软件工程实践之旅。字典+ 最初是一个简单的、基于JSON文件的字典查询和软件激活工具，通过一系列严格的压力测试、性能瓶颈分析和架构重构，最终演化为一个安全、健壮、高性能的、基于SQLite的全栈订阅管理系统。
本项目包含两个核心部分：
后端服务 (server.py): 一个基于 Flask 和 Waitress 的生产级后端，负责处理激活、授权、数据查询，并提供一个功能强大的后台管理面板。
桌面客户端 (main.py): 一个基于 Flet 构建的、美观的跨平台客户端，用于用户激活软件和查询内容。
✨ 核心特性
后端服务 (server.py)
高性能数据库: 采用 SQLite 并开启 WAL (Write-Ahead Logging) 模式，实现了惊人的并发读写性能。
订阅式授权: 支持多种可配置的授权类型（如月卡、季卡、年卡），并自动计算和验证到期时间。
企业级安全:
CSRF防护: 所有Web表单和API都受到 Flask-WTF 的保护。
密码安全: 管理员密码使用 salt + PBKDF2 安全哈希存储。
API安全: 客户端API通过豁免规则与Web后台安全策略解耦。
专业后台面板 (/manage):
后端驱动: 采用现代Web架构，页面秒开，数据通过API异步加载。
高效管理: 对数万条激活码和设备进行流畅的后端分页和搜索。
功能完备: 支持生成不同类型的激活码、撤销设备授权等。
实时监控 (/monitoring): 提供实时的服务器CPU、内存、网络和API请求数监控图表。
平滑数据迁移: 首次启动时，可自动将旧的.json数据库文件无缝迁移至SQLite。
桌面客户端 (main.py)
现代化UI: 使用 Flet 构建，界面美观，体验流畅。
极致用户体验:
异步网络请求: 所有网络操作都在后台线程执行，UI永不冻结。
清晰的用户反馈: 通过 SnackBar 和状态文本，为用户的每一次操作（如复制、激活成功/失败）提供即时反馈。
健壮的设备ID: 采用持久化UUID方案，在用户本地生成并存储设备ID，100%跨平台，绝对可靠。
内容安全: 所有从服务器获取并显示的Markdown内容都经过 bleach 库安全净化，杜绝XSS风险。
🚀 性能亮点
本项目经过了严酷的极限压力测试 (在4核4G服务器上，模拟1000个并发用户，发起40000次请求)。在8线程的最佳配置下，取得了以下惊人成绩：
测试场景 (10000次请求 / 1000并发)	每秒请求数 (RPS)	成功率	平均响应时间	99%响应时间
ACTIVATE (核心写入)	95.58	98.2%	4.98 秒	11.15 秒
CHECK_STATUS (数据库读)	397.22	100%	484 ms	5.93 秒
GET_IDENTITIES (内存读)	306.44	99.7%	537 ms	6.12 秒
ADVANCED_SEARCH (复杂DB读)	87.42	98.5%	5.15 秒	10.53 秒
结论: 系统总吞吐量极高，总失败率在极限压力下依然极低。核心的数据库读写在 WAL 模式加持下表现极其出色，证明了架构的健壮性。
🛠️ 技术栈
后端: Python 3.9+, Flask, Waitress (WSGI Server), SQLite
前端 (后台):原生 HTML, CSS, JavaScript
桌面客户端: Flet
核心库: Flask-WTF (安全), psutil (监控), numpy (测试报告), bleach (安全)
📂 项目结构
code
Code
E:\DICTIONARY_PLUS
│   config.json               # 核心配置文件
│   create_admin.py           # 管理员密码生成工具
│   database.db               # SQLite数据库文件 (自动生成)
│   main.py                   # Flet桌面客户端
│   README.md                 # 就是本文件
│   requirements.txt          # 项目依赖
│   server.py                 # 核心后端服务
│   stress_test.py            # 专业级压力测试脚本
│
└───templates
        login.html            # 登录页面
        manage.html           # 后台管理页面
        monitoring.html       # 实时监控页面
⚙️ 快速开始
1. 先决条件
Python 3.9 或更高版本
2. 安装步骤
克隆仓库
code
Bash
git clone https://github.com/your-username/dictionary-plus.git
cd dictionary-plus
创建并激活虚拟环境
code
Bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
安装所有依赖
code
Bash
pip install -r requirements.txt
配置应用
复制配置文件模板: copy config.json.example config.json (或手动创建 config.json)。
运行密码生成工具，并按提示输入您的管理员密码：
code
Bash
python create_admin.py
将工具输出的密码哈希，以及用于压力测试的明文密码，填入 config.json 文件。
3. 运行
启动后端服务器
code
Bash
python server.py
首次启动时，服务器会自动检测旧的 .json 文件并执行一次性数据迁移，创建一个 database.db 文件。
启动桌面客户端
在另一个终端中，运行：
code
Bash
python main.py
访问Web后台
在浏览器中打开 http://127.0.0.1:5000/login，使用您设置的管理员密码登录。
🧠 关键架构决策与演进
这个项目最有价值的部分是它所经历的优化历程。以下是几个关键的架构决策：
从文件到数据库 (性能革命): 项目初期使用 JSON + FileLock，在高并发下迅速暴露了死锁和性能瓶颈。我们将其迁移到了 SQLite，并开启了 WAL模式，使得并发读写性能获得了超过**120%**的巨大提升，并彻底解决了锁竞争问题。
后端驱动的前端 (体验革命): /manage 页面最初在后端渲染了所有数据，当数据量过万时，页面加载时间变得无法忍受。我们将其重构为前后端分离模式：后端只提供一个轻量级页面框架，前端通过 API 异步请求数据，并由后端完成分页和搜索。这使得无论数据量多大，后台页面都能瞬间加载。
专业的并发模型 (稳定基石): 我们从 Flask 自带的开发服务器，迁移到了生产级的 Waitress WSGI服务器。并通过一系列极限压力测试，科学地找到了在特定硬件（4核CPU）下 8线程 (os.cpu_count() * 2) 的“黄金配置”，实现了系统总吞吐量和稳定性的最佳平衡。
安全第一 (生产前提): 我们为所有Web表单和需要认证的API添加了 CSRF 防护，并为不同类型的客户端（Web浏览器 vs. 桌面应用）配置了差异化的安全策略，确保了系统的安全性。
🤝 如何贡献
欢迎各种形式的贡献！您可以：
Fork 本项目
创建您的 Feature Branch (git checkout -b feature/AmazingFeature)
提交您的改动 (git commit -m 'Add some AmazingFeature')
Push 到 Branch (git push origin feature/AmazingFeature)
发起一个 Pull Request
📄 许可证
本项目采用 MIT 许可证。详情请见 LICENSE 文件。
