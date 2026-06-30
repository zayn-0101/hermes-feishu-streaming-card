# V3.8.0 版本说明

V3.8.0 聚焦飞书卡片可读性和流式稳定性。

## 核心改动

- 将主回答与 reasoning / tool timeline 分离展示，默认让最终答案留在最显眼的位置。
- 合并 burst 场景下的卡片更新，并在 terminal card 渲染前 drain pending updates。
- 长 Markdown 表格和 fenced code block 跨卡片分块时保持结构，减少 raw Markdown 和半截 code fence。
- 新增卡片更新 metrics，覆盖 queue、coalescing、drain、Feishu update latency。

## 升级说明

现有用户不需要修改配置。新增卡片选项都是可选项，并使用安全默认值。

## 发布文件

GitHub Releases 包含：

- `hermes-feishu-card-v3.8.0-macos.tar.gz`
- `hermes-feishu-card-v3.8.0-linux.tar.gz`
- `hermes-feishu-card-v3.8.0-windows.zip`
- `hermes-feishu-card-v3.8.0-checksums.txt`

## 验证命令

- `.venv/bin/python -m pytest tests/unit/test_session.py tests/unit/test_render.py tests/unit/test_text.py tests/unit/test_config.py -q`
- `.venv/bin/python -m pytest tests/integration/test_server.py -q`
- `.venv/bin/python -m pytest -q`
