# 需求实施计划

- [ ] 1. 实现 CF-RAY 校验模块 ray_checker.py
   - 创建 `ray_checker.py`，实现 `ray_check()` 函数
   - 对每个候选 IP:端口发起 HTTP GET 请求，检查 `CF-RAY` 响应头
   - 从 `CF-RAY` 值提取三字码头作为数据中心代码
   - 支持并发，使用 `ThreadPoolExecutor` + `urllib3` 连接池
   - 失败时降级到备用通道，不丢弃候选

- [ ] 2. 实现 RTT 排序模块 rtt_sorter.py
   - 创建 `rtt_sorter.py`，实现 `rtt_sort()` 函数
   - 使用 `socket.create_connection` 测量 TCP 握手时间，3 次取平均
   - 记录最小延迟和标准差（抖动指标）
   - 按 RTT 升序排序，截取前 K 个
   - 不可达 IP 直接过滤

- [ ] 3. 实现滑动窗口速度测速模块 speed_tester.py
   - 创建 `speed_tester.py`，实现 `speed_test()` 函数
   - 使用 `socket.create_connection` + `ssl.wrap_socket` 强制域名绑定到候选 IP
   - 1 秒滑动窗口计算瞬时峰值速度
   - 达到带宽阈值时提前终止该 IP 测速
   - 解析 `CF-RAY` 头提取数据中心

- [ ] 4. 实现综合加权排序模块 weighted_scorer.py
   - 创建 `weighted_scorer.py`，实现 `weighted_sort()` 函数
   - 评分公式：带宽 x3 + (1000-延迟) + (1000-HTTP延迟) + (500-抖动)
   - 按综合评分降序排列，评分相同时按带宽降序排列

- [ ] 5. 实现裂变发现模块 fission_discoverer.py
   - 创建 `fission_discoverer.py`，实现 `fission_discover()` 函数
   - 阶段1：IP 反查域名（site.ip138.com、dnsdblookup.com、ipchaxun.com 三源轮换）
   - 阶段2：域名解析 IPv4 地址
   - 去重合并，支持最大深度和最大 IP 数限制

- [ ] 6. 改造 run.py — 新增 CLI 参数并集成新模块
   - 新增 `--ray-check`、`--self-speed`、`--top-k`、`--bandwidth`、`--fission` 等参数
   - 改造 `_run_cfst_speedtest()` 支持新模块调度
   - 新增集成步骤：CF-RAY 校验 → RTT 排序 → 速度测试 → 加权排序
   - 不启用新标志时行为与现有版本完全一致

- [ ] 7. 检验 — 运行验证
   - 不启用任何新标志运行，确认行为不变
   - 启用 `--self-speed` 运行，确认测速模块正常工作
   - 确认所有模块导入正常，无语法错误