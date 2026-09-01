# `kazu ssp`

读取少数派的流量使用情况。

## 用法

```bash
uv run kazu ssp
uv run kazu ssp --authorization "Bearer <credential>"
```

选项：

- `--authorization`：完整的 `Bearer <credential>` 文本；传入时覆盖配置文件。
- `--timeout`：请求超时秒数。
- `--verbose`：显示已脱敏的 HTTP 请求与响应。

## Authorization

Authorization 必须是完整的 `Bearer <credential>` 文本。

登录少数派后，在该站点页面的浏览器开发者工具 Console 中运行下面的 JavaScript；它会将正确格式的值复制到剪贴板：

```js
const token = localStorage.getItem("VUE_NAIVE_ACCESS_TOKEN");
if (!token) throw new Error("VUE_NAIVE_ACCESS_TOKEN is not available");
copy(`Bearer ${token}`);
```

令牌来源是登录后的 Local Storage `VUE_NAIVE_ACCESS_TOKEN` 键。

可以临时传入命令行，或保存到用户配置文件：

```toml
[sources.ssp]
authorization = "Bearer <credential>"
```

用户配置文件位置：

- Linux：`~/.config/kazu/config.toml`
- macOS：`~/Library/Application Support/KokomiNetwork/kazu/config.toml`
- Windows：`%LOCALAPPDATA%\\KokomiNetwork\\kazu\\config.toml`
