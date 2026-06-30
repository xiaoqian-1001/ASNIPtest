import socket
import ssl
from typing import Optional


def ssl_connect(
    ip: str,
    port: int,
    server_hostname: str,
    timeout: int = 10,
) -> ssl.SSLSocket:
    sock = socket.create_connection((ip, port), timeout=timeout)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    ssock = context.wrap_socket(sock, server_hostname=server_hostname)
    ssock.settimeout(timeout)
    return ssock


def build_http_request(host: str, path: str) -> bytes:
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: Mozilla/5.0\r\n"
        f"Accept: */*\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()


def parse_cf_ray(response: bytes) -> tuple[bool, str]:
    header_section = response.decode("utf-8", errors="replace")
    idx = header_section.find("\r\n\r\n")
    if idx >= 0:
        header_section = header_section[:idx]
    for line in header_section.split("\r\n"):
        if line.lower().startswith("cf-ray:"):
            ray_val = line.split(":", 1)[1].strip()
            parts = ray_val.split("-")
            colo = parts[-1].strip() if len(parts) > 1 else ""
            return True, colo
    return False, ""


def read_http_response(ssock: ssl.SSLSocket) -> bytes:
    response = b""
    while True:
        try:
            chunk = ssock.read(65536)
            if not chunk:
                break
            response += chunk
        except socket.timeout:
            break
    return response