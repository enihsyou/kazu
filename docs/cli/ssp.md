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

## 内置加密配置来源

`BOOTSTRAP_MASTER_KEY` 取自首页加载的 `sec.js`。脚本中的 32 位小写字母数字字符串可用
`:'\\b[a-z0-9]{32}\\b',` 的等价模式定位。

`SECURE_SETTING` 取自 `https://s1.thefew01.top/` 响应中的
`<meta name="secure-setting" content="...">`，无需登录。首页同时提供 `sec.js` 的链接。
`tests/test_ssp_bootstrap.py` 会在网络可用时请求这两个公开资源，并验证它们仍与内置常量一致。
