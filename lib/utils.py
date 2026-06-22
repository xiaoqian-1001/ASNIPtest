#!/usr/bin/env python3
"""公共工具模块 -- 进度条、网络检测、端口解析、系统信息"""

import os
import re
import sys
import time
import signal
import socket
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

__all__ = [
    "BAR_WIDTH", "write_progress", "write_progress_done",
    "get_public_ip", "get_lan_ip", "detect_isp",
    "parse_ports", "port_is_free", "kill_port_process",
]

BAR_WIDTH = 30
_FILL = "\u2588"
_EMPTY = "\u2591"


def write_progress(pct: float, extra: str = "") -> None:
    filled = int(BAR_WIDTH * pct / 100)
    bar = _FILL * filled + _EMPTY * (BAR_WIDTH - filled)
    sys.stderr.write(f"\r  [{bar}] {pct:.1f}%{extra}")
    sys.stderr.flush()


def write_progress_done(extra: str = "") -> None:
    sys.stderr.write(f"\r  [{_FILL * BAR_WIDTH}] 100.0%{extra}\n")
    sys.stderr.flush()


# ── 公网 IP 获取（并发 HTTP + DNS 兜底） ──

_HTTP_APIS = [
    ("https://api.ipify.org", 5),
    ("https://api-ipv4.ip.sb/ip", 5),
    ("https://ifconfig.me/ip", 5),
    ("https://icanhazip.com", 5),
]

_DNS_QUERIES = [
    (["dig", "+short", "myip.opendns.com", "@resolver1.opendns.com"], 5),
    (["dig", "TXT", "+short", "o-o.myaddr.l.google.com", "@ns1.google.com"], 5),
    (["dig", "+short", "whoami.akamai.net", "@ns1-1.akamaitech.net"], 5),
]


def _try_http_ip(url: str, timeout: int) -> Optional[str]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


def _try_dns_ip(cmd: list[str], timeout: int) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip().strip('"')
        if out and "." in out and out.count(".") == 3:
            parts = out.split(".")
            if all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return out
    except Exception:
        pass
    return None


def get_public_ip() -> str:
    with ThreadPoolExecutor(max_workers=len(_HTTP_APIS)) as ex:
        futures = {ex.submit(_try_http_ip, url, t): url for url, t in _HTTP_APIS}
        for f in as_completed(futures):
            ip = f.result()
            if ip:
                return ip
    for cmd, t in _DNS_QUERIES:
        ip = _try_dns_ip(cmd, t)
        if ip:
            return ip
    return "127.0.0.1"


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


# ── ISP/运营商检测 ──

_IPINFO_TOKEN_PATHS = [
    Path("/root/.ipinfo_token"),
    Path.home() / ".ipinfo_token",
]


def _load_ipinfo_token() -> Optional[str]:
    for p in _IPINFO_TOKEN_PATHS:
        if p.is_file():
            return p.read_text().strip()
    return None


def detect_isp(ip: str) -> tuple[str, str, str]:
    if ip == "127.0.0.1":
        print("  (无法获取公网 IP，跳过运营商检测)")
        return ip, "", ""
    try:
        token = _load_ipinfo_token()
        url = f"https://ipinfo.io/{ip}/json"
        if token:
            url += f"?token={token}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        country = data.get("country", "")
        org = data.get("org", "")
        city = data.get("city", "")
        if country == "CN":
            isp = org.split(" ", 1)[-1] if org else "未知"
            print(f"  地区: {city}, {country}  运营商: {isp}")
        else:
            print(f"  地区: {city}, {country}  机构: {org}")
        return ip, country, org
    except Exception as e:
        print(f"  (获取详情失败: {e})")
    return ip, "", ""


# ── 端口解析 ──

def parse_ports(port_str: str) -> str:
    ports: set[str] = set()
    for part in port_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                pa, pb = int(a), int(b)
                if 1 <= pa <= pb <= 65535:
                    ports.update(str(p) for p in range(pa, pb + 1))
            elif part.isdigit():
                p = int(part)
                if 1 <= p <= 65535:
                    ports.add(part)
        except ValueError:
            continue
    return ",".join(sorted(ports, key=int)) if ports else ""


def port_is_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) != 0
    finally:
        sock.close()


def kill_port_process(port: int) -> bool:
    for tool in (["ss", "-tlnp", f"sport = :{port}"],
                 ["lsof", "-ti", f":{port}"]):
        try:
            r = subprocess.run(tool, capture_output=True, text=True, timeout=5)
            for line in r.stdout.split("\n"):
                pid_match = re.search(r"pid=(\d+)", line)
                if pid_match:
                    os.kill(int(pid_match.group(1)), signal.SIGTERM)
                    time.sleep(0.3)
                    return True
                if line.strip().isdigit():
                    os.kill(int(line.strip()), signal.SIGTERM)
                    time.sleep(0.3)
                    return True
        except Exception:
            continue
    return False
