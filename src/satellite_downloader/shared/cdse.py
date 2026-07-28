# src/satellite_downloader/shared/cdse.py
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CDSEClient:
    """
    Copernicus Data Space Ecosystem (CDSE) 公共客户端。
    从 CopernicusSentinel2Provider 提取的通用能力：
    - OAuth2 认证和令牌刷新
    - HTTP Session、重试、超时
    - Range 断点续传
    - .part 文件、MD5 校验和原子改名
    """

    TOKEN_URL = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
        "protocol/openid-connect/token"
    )
    CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    DOWNLOAD_URL_TEMPLATE = (
        "https://download.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"
    )

    def __init__(
        self,
        username: str,
        password: str,
        timeout: Tuple[int, int] = (15, 90),
    ):
        self.username = username
        self.password = password
        self.timeout = timeout
        self._access_token = ""
        self._token_expiry = 0.0

        self.session = self._create_session()
        self._authenticate()

    def _create_session(self) -> requests.Session:
        """创建带重试机制的 Session"""
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "POST")),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers.update({"User-Agent": "satellite-image-downloader/0.1"})
        return session

    def _authenticate(self) -> None:
        """获取 OAuth2 Token"""
        username = self.username.strip()
        if not username or not self.password:
            raise ValueError("CDSE 用户名和密码不能为空")

        try:
            response = self.session.post(
                self.TOKEN_URL,
                data={
                    "client_id": "cdse-public",
                    "username": username,
                    "password": self.password,
                    "grant_type": "password",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ConnectionError(f"CDSE 登录服务连接失败：{exc}") from exc

        if response.status_code != 200:
            message = "账号或密码错误"
            try:
                detail = response.json().get("error_description")
                if detail:
                    message = detail
            except ValueError:
                pass
            raise ValueError(f"CDSE 登录失败：{message}")

        payload = response.json()
        self._access_token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 600)) - 30

        # 更新默认请求头
        self.session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
        })

    def _ensure_valid_token(self) -> None:
        """检查 Token 是否过期，过期则重新认证"""
        if not self._access_token or time.time() >= self._token_expiry:
            self._authenticate()

    def get(self, url: str, params: Optional[dict] = None) -> requests.Response:
        """发送 GET 请求，自动确保 Token 有效"""
        self._ensure_valid_token()
        return self.session.get(url, params=params, timeout=self.timeout)

    def download(
        self,
        url: str,
        local_path: Path,
        expected_md5: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        cancel_check: Optional[callable] = None,
    ) -> Path:
        """
        断点续传下载文件。

        Args:
            url: 下载 URL
            local_path: 目标文件路径（父目录会自动创建）
            expected_md5: 期望的 MD5 校验值（可选）
            progress_callback: 进度回调函数，接收 (已下载字节, 总字节)
            cancel_check: 取消检查函数，返回 True 表示取消

        Returns:
            下载完成后的文件路径

        Raises:
            ValueError: MD5 校验失败
            RuntimeError: 下载被取消或下载不完整
            requests.RequestException: 网络请求失败
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = local_path.with_suffix(local_path.suffix + ".part")

        # 检查是否已完全下载
        if local_path.is_file():
            if expected_md5 and _matches_md5(local_path, expected_md5):
                if progress_callback:
                    progress_callback(local_path.stat().st_size, local_path.stat().st_size)
                return local_path
            # 文件存在但校验失败，删除后重新下载
            local_path.unlink()

        # 检查 .part 文件是否完整
        if part_path.is_file():
            if expected_md5 and _matches_md5(part_path, expected_md5):
                os.replace(part_path, local_path)
                if progress_callback:
                    progress_callback(local_path.stat().st_size, local_path.stat().st_size)
                return local_path

        # 获取响应（支持断点续传）
        response, existing_size = self._open_download(url, part_path)

        total_size = _response_total(response, existing_size)
        downloaded = existing_size

        if progress_callback:
            progress_callback(downloaded, total_size)

        mode = "ab" if response.status_code == 206 and existing_size else "wb"
        try:
            with part_path.open(mode) as output:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if cancel_check and cancel_check():
                        response.close()
                        raise RuntimeError("下载已取消，可稍后从断点继续")
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)
        except OSError as exc:
            response.close()
            raise RuntimeError(f"写入文件失败：{exc}") from exc
        finally:
            response.close()

        if total_size and downloaded != total_size:
            raise RuntimeError(f"下载不完整：应为 {total_size} 字节，实际为 {downloaded} 字节")

        if expected_md5 and not _matches_md5(part_path, expected_md5):
            raise ValueError("MD5 校验失败，保留 .part 文件以便重新下载")

        os.replace(part_path, local_path)
        return local_path

    def _open_download(self, url: str, part_path: Path) -> Tuple[requests.Response, int]:
        """打开下载连接，支持断点续传"""
        existing = part_path.stat().st_size if part_path.exists() else 0
        self._ensure_valid_token()

        headers = {"Authorization": f"Bearer {self._access_token}"}
        if existing:
            headers["Range"] = f"bytes={existing}-"

        for attempt in range(8):
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    stream=True,
                    allow_redirects=False,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise ConnectionError(f"下载连接失败：{exc}") from exc

            if response.status_code in (301, 302, 303, 307, 308):
                redirect = response.headers.get("Location")
                response.close()
                if not redirect:
                    raise RuntimeError("下载服务返回了无目标地址的重定向")
                url = redirect
                continue
            break
        else:
            raise RuntimeError("下载服务重定向次数过多")

        if response.status_code == 401:
            # Token 可能已过期，刷新后重试
            response.close()
            self._authenticate()
            return self._open_download(url, part_path)

        if response.status_code not in (200, 206):
            detail = response.text[:300]
            response.close()
            raise RuntimeError(f"下载服务返回 HTTP {response.status_code}：{detail}")

        return response, existing

    def download_product(
        self,
        product_id: str,
        destination: Path,
        expected_md5: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        cancel_check: Optional[callable] = None,
    ) -> Path:
        """
        按产品 ID 下载整包产品。

        这是 download() 的便捷包装，自动构造下载 URL。
        """
        url = self.DOWNLOAD_URL_TEMPLATE.format(product_id=product_id)
        return self.download(url, destination, expected_md5, progress_callback, cancel_check)


def _response_total(response: requests.Response, existing: int) -> int:
    """从 Content-Range 或 Content-Length 获取总大小"""
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    try:
        return existing + int(response.headers.get("Content-Length", 0))
    except ValueError:
        return 0


def _matches_md5(path: Path, expected: str) -> bool:
    """计算文件的 MD5 并与期望值比较"""
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected.lower()