#!/usr/bin/env python3
"""
API 精筛 -- CF 反代节点二次验证
用法: python3 verify.py --input cf_hits.txt --output verified.txt [--api URL] [--chunk N] [--concurrent N]
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from lib.utils import write_progress, write_progress_done

MAX_RETRIES = 2
RETRY_CODES = frozenset({429, 502, 503, 504})


def _check_one(ip_port: str, api_url: str) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://090227.xyz",
    }
    for attempt in range(MAX_RETRIES + 1):
        try:
            url = f"{api_url}?proxyip={ip_port}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES:
                time.sleep(min(2 ** attempt, 8))
                continue
            return None
        except (urllib.error.URLError, OSError):
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 8))
                continue
            return None
        except json.JSONDecodeError:
            return None

        if not data.get("success"):
            return None

        pr = data.get("probe_results", {})
        ei = pr.get("ipv4", {}).get("exit") or pr.get("ipv6", {}).get("exit") or {}
        colo = ei.get("colo", data.get("colo", ""))
        country = ei.get("country", "")
        region = ei.get("region", "")
        asn = ei.get("asn", data.get("asn", ""))
        ip, port = ip_port.rsplit(":", 1)
        return f"{ip},{port},TRUE,{colo},{country},{region},,,AS{asn}"
    return None


def _read_input(path: str) -> list[str]:
    lines: list[str] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            lines.append(parts[0] if parts else line)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CF 反代节点 API 精筛（含自动重试）")
    parser.add_argument("--input", required=True, help="输入文件 (cf_hits.txt)")
    parser.add_argument("--output", required=True, help="输出文件 (verified.txt)")
    parser.add_argument("--api", default="https://api.090227.xyz/check")
    parser.add_argument("--chunk", type=int, default=5000, help="分片大小")
    parser.add_argument("--concurrent", type=int, default=32, help="并发数")
    args = parser.parse_args()

    lines = _read_input(args.input)
    total = len(lines)
    if total == 0:
        print("  输入为空，跳过")
        sys.exit(0)

    passed = 0
    start = time.time()

    with open(args.output, "w") as out:
        out.write("IP地址,端口,TLS,数据中心,地区,城市,网络延迟,下载速度,ASN\n")
        for i in range(0, total, args.chunk):
            chunk = lines[i:i + args.chunk]
            with ThreadPoolExecutor(max_workers=args.concurrent) as ex:
                fmap = {ex.submit(_check_one, ip, args.api): ip for ip in chunk}
                for f in as_completed(fmap):
                    r = f.result()
                    if r:
                        out.write(r + "\n")
                        out.flush()
                        passed += 1

            elapsed = time.time() - start
            done = i + len(chunk)
            rate = done / elapsed if elapsed > 0 else 0
            eta_min = (total - done) / rate / 60 if rate > 0 else 0
            write_progress(done / total * 100,
                           f" | 通过 {passed} | {rate:.1f}/s | ETA {eta_min:.1f}m")

    elapsed = int(time.time() - start)
    write_progress_done(f" | 通过 {passed}/{total} | {elapsed // 60}min {elapsed % 60}s")


if __name__ == "__main__":
    main()
