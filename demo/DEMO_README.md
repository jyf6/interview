# Demo 说明

本目录是银发传记采访引导模块的可运行 Demo，包含后端服务与静态测试页面。

## 快速运行

```powershell
cd demo
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写 `DASHSCOPE_API_KEY` 后启动：

```powershell
python main.py
```

浏览器打开：

```text
test_page.html
```

或使用静态服务：

```powershell
python -m http.server 8010 --bind 127.0.0.1
```

访问：

```text
http://127.0.0.1:8010/test_page.html
```

## 当前能力

- 自动开场白
- 产品使用说明弹窗
- 采访引导卡片
- 心理状态卡片
- 采访对话

更多说明见仓库根目录 `README.md`。
