# 代码组织

`kazu/cli.py` 保留应用入口和顶层 parser；具体命令不再由数据源注册。

```text
kazu/
├── cli.py                     # 应用入口
├── clicmds/
│   ├── base.py                # CLICommand 注册约定
│   ├── ssp_cli.py             # SSPCommand：参数、命令执行与服务装配
│   ├── ssp_display.py         # SSPConsole：表格、日志与 trace 展示
│   └── documentation.py       # CLIDocumentation、通用 DocumentationAction
├── sources/
│   └── ssp.py                 # SSPSource、统一采集与每日流量规范化
├── lib/
│   ├── traffic.py               # 通用订阅流量模型、快照和 SubscriptionTrafficSource 协议
│   ├── metrics/
│   │   ├── traffic.py           # SubscriptionTrafficMetrics：持久 Gauge 的注册、清理和更新
│   │   ├── exporter.py        # SubscriptionTrafficExporter：每次 scrape 的采集协调
│   │   └── server.py          # MetricsHTTPServer：HTTP 路由与响应
│   ├── influxdb3/
│   │   ├── client.py          # InfluxDB3Client：配置、查询检查与 HTTP API
│   │   ├── traffic.py           # 订阅流量编解码和 InfluxDB3SubscriptionTrafficWriter
│   │   └── reporter.py        # InfluxDB3Reporter：显式启用、降级与日志
│   └── sspgateway/
│       ├── client.py          # SSPGateway：只读 API 与网关传输
│       ├── codec.py           # GatewayCodec：规范化、签名、加解密
│       ├── bootstrap.py       # load_bootstrap：公开内置配置及解码
│       ├── models.py          # 网关响应和 SSP 原始数据模型
│       ├── traffic.py         # parse_traffic_log：流量响应解析
│       ├── trace.py           # 请求/响应的脱敏格式化函数
│       └── errors.py          # 网关异常类型
└── config.py                  # 配置模型与文件加载
```

## 依赖边界

- `clicmds` 负责 argparse、Rich 展示以及对象的生命周期装配，不实现采集协议或存储格式；命令模块统一以
  `_cli.py` 结尾并由包发现逻辑加载。
- 指标实现统一位于 `lib/metrics/` 包，不再保留同名的 `lib/metrics.py` 模块。
- `sources` 通过 `collect()` 产出 `SubscriptionTrafficSnapshot`；不依赖 CLI、Prometheus 或 InfluxDB。
- `SubscriptionTrafficMetrics` 持有订阅流量 Gauge，负责注册、清理标签和更新值；`MetricsHTTPServer` 不认识 SSP 或数据库。
- `SubscriptionTrafficExporter` 调用装配时传入的采集函数，通过可选回调通知上报方，不绑定 InfluxDB。
- `InfluxDB3Client` 处理 HTTP API；流量表语义属于 writer/codec，上报启用和失败降级属于 reporter。
- `sspgateway` 的脱敏与终端渲染分离；包入口导出 `SSPGateway`、模型、异常和 bootstrap 常量。
- `SSPGateway` 持有 HTTP 客户端及请求配置，`GatewayCodec` 持有认证信息和会话密钥，因此
  使用类管理状态。bootstrap 加载、流量解析和 trace 格式化使用模块函数；不依赖实例的
  校验、编码等辅助函数作为对应模块的私有函数，不额外套一层工具类。
- `normalize_subscription_traffic_usage`、InfluxDB 流量编解码，以及 CLI 参数校验和格式化
  均为各自模块中的普通函数；固定的表名、指标定义和 label 名称使用模块常量。
- `CLICommand.create_all` 使用类级命令注册表，保留为类方法；持有客户端、控制台、
  并发锁或其他实例状态的对象继续使用类管理其职责。

## 一次采集的生命周期

`GET /metrics` → `SubscriptionTrafficExporter` → `SSPSource.collect()` → `SubscriptionTrafficSnapshot`。
`ssp get` 同样调用 `SSPSource.collect()`，展示层从快照读取数据；采集与规范化只有一个入口。
有效快照非阻塞地交给可选的 InfluxDB reporter 后台队列；当天数据用于更新
`SubscriptionTrafficMetrics` 中的 Gauge。采集过程串行，重叠请求返回 503；上报网络
请求只在 worker 中执行，错误由 reporter 记录，不中断指标生成。停止服务时 reporter
停止接收新快照，排空最多一个待处理快照，并在有界期限内等待 worker 后释放资源。

服务装配时创建一个独立 `CollectorRegistry` 和耗时 Gauge，通过
`@scrape_duration.time()` 装饰调用 `source.collect()` 的采集函数，再传入 `SubscriptionTrafficExporter`。
registry 和各 Gauge 在服务实例生命周期内复用；计时只覆盖抓取与规范化，不包含 InfluxDB 上报。
耗时和流量独立注册，最后由 `generate_latest(registry)` 合并到同一次 HTTP 响应。
`SubscriptionTrafficSnapshot` 不携带耗时，因此 InfluxDB 不会保存该指标。

每次请求在同一把锁内采集、更新并生成响应；`SubscriptionTrafficMetrics.update()` 内部先清理各 Gauge
的旧标签，再写入当前快照，避免标签残留和
半更新的响应。失败请求仍返回 503，不输出旧快照。独立 registry 不使用全局 `REGISTRY`，
因此不输出默认的 Process、GC 和 Platform 指标。

业务日期与写入时间均来自同一快照的采集时刻，使用本机时区；配置在启动时加载，
不在每个 scrape 中重载。新增数据源可实现 `SubscriptionTrafficSource` 协议，新增命令放在
`clicmds` 下并继承 `CLICommand`，两者不需要共享继承体系。

## 文档资源与打包

`docs/` 是文档的唯一编辑源。Hatch 的 wheel `force-include` 配置将其打包到
`kazu/_docs/`，`CLIDocumentation` 优先通过 `importlib.resources` 读取包内文档；
源码/可编辑安装未包含该资源时，回退到仓库 `docs/cli/`。
命令通过 `DocumentationAction(command=...)` 注册 `--docs`，由通用 Action 负责展示与退出。
Docker 构建阶段复制 `docs/` 供 wheel 打包，运行阶段仅保留安装后的虚拟环境，不需要
保留构建目录或挂载仓库。
