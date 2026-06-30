from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WeightedResult:
    ip: str
    port: int
    peak_speed_kbps: float
    bandwidth_mbps: float
    rtt_avg_ms: float
    colo: str
    http_latency_ms: float
    rtt_std_ms: float
    score: float = 0


def weighted_sort(
    results: list,
    weight_bandwidth: int = 3,
    weight_rtt: int = 1,
    weight_http: int = 1,
    weight_jitter: int = 2,
) -> list[WeightedResult]:
    scored: list[WeightedResult] = []
    for r in results:
        wr = WeightedResult(
            ip=r.ip,
            port=r.port,
            peak_speed_kbps=getattr(r, "peak_speed_kbps", 0),
            bandwidth_mbps=getattr(r, "bandwidth_mbps", 0),
            rtt_avg_ms=getattr(r, "rtt_avg_ms", 0),
            colo=getattr(r, "colo", ""),
            http_latency_ms=getattr(r, "http_latency_ms", 0),
            rtt_std_ms=getattr(r, "rtt_std_ms", 0),
        )
        bw = wr.bandwidth_mbps * weight_bandwidth
        rtt_score = max(0, 1000 - wr.rtt_avg_ms) * weight_rtt
        http_score = max(0, 1000 - wr.http_latency_ms) * weight_http
        jitter_score = max(0, 500 - wr.rtt_std_ms) * weight_jitter
        wr.score = bw + rtt_score + http_score + jitter_score
        scored.append(wr)

    scored.sort(key=lambda x: (-x.score, -x.bandwidth_mbps))
    return scored