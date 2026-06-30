# Requirements Document — 测速优选管道优化

## Introduction

在现有 IP-Tidy 的扫描→检测→验证→测速链路中，引入 4 个开源项目的核心技术，全面提升优选结果的准确性和速度。优化范围覆盖验证精度（CF-RAY 校验）、测速方法（自实现滑动窗口峰值速度）、效率策略（RTT 排序 + Top-K 带宽测试）、IP 发现（裂变式扩充）。

## 参考项目

| 项目 | 核心技术 | 集成方式 |
|------|----------|----------|
| xinyitang3/cfnb | 多源聚合、加权排序、DNS 推送 | 参考加权排序算法 |
| badafans/better-cloudflare-ip | CF-RAY 校验、滑动窗口峰值速度 | 核心算法移植 |
| fscarmen/better-cloudflare-ip | 并发 RTT、libcurl 测速、内置 fallback | 并发模型参考 |
| snowfal1/CloudflareCDNFission | IP↔域名裂变发现 | 可选扩展模块 |

## Glossary

- **IP-Tidy**: 本项目，ASN/CIDR → 端口扫描 → CF 检测 → CSV 输出
- **CF-RAY**: Cloudflare 响应头 `CF-RAY`，包含数据中心 IATA 代码
- **RTT**: Round-Trip Time，往返延迟
- **Top-K**: 按延迟排序取前 N 个候选
- **cf-scanner**: Go 编写的 TLS 证书校验工具
- **verify.py**: Python API 精筛脚本
- **cfst**: CloudflareSpeedTest 外部二进制测速工具
- **裂变发现**: 通过 `IP→域名反查↔DNS 解析` 交替迭代扩充 IP 池

## Requirements

### R1: CF-RAY 头校验（替代/补充 API 精筛）

**User Story:** AS 用户，I want 对 cf-scanner 命中的 IP 进行 HTTP CF-RAY 头校验，so that 确认该 IP 确实路由到 Cloudflare 节点，减少非 CF 误判。

#### Acceptance Criteria

1. WHEN cf-scanner 输出命中 IP 列表，THE system SHALL 对每个 IP 发起 HTTP GET 请求（目标域名 `cloudflare.com`），检查响应头 `CF-RAY` 是否存在
2. IF `CF-RAY` 头不存在，THE system SHALL 将该 IP 标记为"疑似非 CF"，降级到备用验证通道或直接丢弃
3. IF `CF-RAY` 头存在，THE system SHALL 从 `CF-RAY` 值中提取三字码头，作为数据中心位置补充到结果中
4. THE system SHALL 支持并发 CF-RAY 校验，默认并发数由 CPU 核数自动调节
5. IF HTTP 请求超时或失败，THE system SHALL 回退到 verify.py API 精筛通道，不丢失候选

### R2: 自实现滑动窗口峰值速度测速（替代外部 cfst 二进制）

**User Story:** AS 用户，I want IP-Tidy 内置速度测速模块，so that 不依赖外部 cfst 二进制，测速结果更可控。

#### Acceptance Criteria

1. THE system SHALL 对候选 IP 建立 TCP 连接后，通过 Host 头强制将测速域名 `speed.cloudflare.com` 解析到候选 IP
2. THE system SHALL 使用 1 秒滑动窗口计算瞬时下载速度峰值，而非全下载量平均
3. THE system SHALL 在速度测试中同时解析响应 `CF-RAY` 头，提取数据中心信息
4. IF 候选 IP 数量超过阈值（默认 20），THE system SHALL 进入 R3 的 RTT 排序流程
5. THE system SHALL 输出每个候选 IP 的：延迟(ms)、峰值速度(kB/s)、数据中心、实测带宽(Mbps)

### R3: RTT 排序 + Top-K 带宽测试

**User Story:** AS 用户，I want 在大批候选 IP 中先通过 RTT 排序缩小范围，so that 带宽测试只对最有希望的 IP 进行，节省时间和流量。

#### Acceptance Criteria

1. WHEN 候选 IP 超过阈值（默认 20），THE system SHALL 先对所有 IP 进行并发 TCP RTT 测试（3 次握手取平均）
2. THE system SHALL 按 RTT 升序排序，仅保留前 K 个 IP 进入带宽测试阶段
3. K 的默认值为 10，THE system SHALL 支持通过命令行参数 `--top-k N` 自定义
4. THE system SHALL 在 RTT 测试中同步校验 TCP 连通性，标记不可达 IP 为失败
5. IF 候选 IP 少于或等于 K，THE system SHALL 跳过 RTT 排序直接进入带宽测试

### R4: 裂变式 IP/域名发现（可选扩展）

**User Story:** AS 用户，I want 通过 IP↔域名反查迭代扩充候选 IP 池，so that 发现更多可用的 Cloudflare 节点。

#### Acceptance Criteria

1. THE system SHALL 支持可选启用裂变发现模式
2. WHEN 启用裂变模式，THE system SHALL 对已验证 IP 进行域名反查（查询 site.ip138.com 等数据源）
3. THE system SHALL 对反查获得的域名执行 DNS 解析，提取新的 IPv4 地址
4. IF 新 IP 不在已有池中，THE system SHALL 将其加入候选列表进行下一轮验证
5. THE system SHALL 支持设置最大裂变深度（默认 2 轮）和最大 IP 数量（默认 1000）

### R5: 综合加权排序

**User Story:** AS 用户，I want 最终输出按综合权重排序，so that 排名靠前的 IP 在实际使用中表现最优。

#### Acceptance Criteria

1. THE system SHALL 对每个 IP 计算综合评分：`带宽 × 3 + (1000 - 延迟) + (1000 - HTTP延迟) + (500 - 抖动)`
2. WHEN 多个 IP 的综合评分相同，THE system SHALL 按带宽降序排列
3. THE system SHALL 在最终输出表格中显示每个 IP 的延迟、峰值速度、数据中心、综合评分

### R6: 渐进式集成（不影响现有流程）

**User Story:** AS 用户，I want 新功能默认不影响现有扫描流程，so that 保持向后兼容性。

#### Acceptance Criteria

1. THE system SHALL 将所有新增检测/测速功能作为可选后处理步骤，不由 `-c` 标志触发时不执行
2. IF 新模块依赖的数据源（如反查网站）不可用，THE system SHALL 降级并提示用户，不中断主流程
3. THE system SHALL 保持现有 `-c`/`--cfst` 标志行为，新功能可通过 `--ray-check`、`--self-speed` 等新标志分别控制
4. IF 用户不指定任何新标志，THE system SHALL 行为与当前版本完全一致