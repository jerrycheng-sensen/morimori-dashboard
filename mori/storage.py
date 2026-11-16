from __future__ import annotations

import base64
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

from mori.core import AppError, default_settings


class Conflict(AppError):
    pass


class GitHubStore:
    """資料只寫入指定的私人儲存庫，不跟公開的應用程式儲存庫混用。"""

    def __init__(self, repo, token, branch="main", session=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") or not token:
            raise AppError("請先設定私人資料儲存庫 STATE_REPO 與 STATE_TOKEN。")
        if not re.fullmatch(r"[\w./-]+", branch or ""):
            raise AppError("資料分支格式不正確。")
        self.repo, self.branch = repo, branch
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}
        self.base = f"https://api.github.com/repos/{repo}"
        self._private_checked = False

    def _request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, headers=self.headers, timeout=30, **kwargs)
        except requests.RequestException:
            raise AppError("GitHub 連線失敗，請稍後重試。") from None
        if response.status_code in (409, 422):
            raise Conflict("設定已被其他操作更新，請重新載入後再儲存。")
        if response.status_code == 404:
            return None
        if not response.ok:
            raise AppError(f"GitHub 存取失敗（HTTP {response.status_code}），請檢查指定儲存庫與權限。")
        return response.json() if response.content else {}

    def ensure_private(self):
        if not self._private_checked:
            meta = self._request("GET", self.base)
            if not meta or meta.get("private") is not True:
                raise AppError("資料儲存庫必須是私人；已停止讀寫，避免公開廣告資料與通知對象。")
            self._private_checked = True

    def read(self, path, default=None):
        self.ensure_private()
        result = self._request("GET", f"{self.base}/contents/{quote(path, safe='/')}",
                               params={"ref": self.branch})
        if result is None:
            return copy.deepcopy(default), None
        try:
            return json.loads(base64.b64decode(result["content"])), result["sha"]
        except (KeyError, ValueError, TypeError):
            raise AppError("私人儲存庫的資料格式不正確，請先檢查原始資料。") from None

    def write(self, path, data, sha, message="更新廣告監控設定 [skip ci]"):
        self.ensure_private()
        serialized = json.dumps(data, ensure_ascii=False, indent=2).encode()
        if len(serialized) > 900_000:
            raise AppError("私人資料檔接近容量上限，已停止寫入；請先備份並封存舊紀錄。")
        body = {"message": message, "branch": self.branch,
                "content": base64.b64encode(serialized).decode()}
        if sha:
            body["sha"] = sha
        result = self._request("PUT", f"{self.base}/contents/{quote(path, safe='/')}", json=body)
        if not result:
            raise AppError("無法寫入私人資料儲存庫；請檢查分支、Token 與 Contents 寫入權限。")
        return result["content"]["sha"]

    def settings(self):
        return self.read("settings.json", default_settings())

    def runtime(self):
        return self.read("runtime.json", {"completed_slots": [], "receipts": {}, "runs": []})

    def acquire_lock(self, owner, now=None):
        now = now or datetime.now(timezone.utc)
        lock, sha = self.read("runner-lock.json", {})
        if lock.get("expires_at") and datetime.fromisoformat(lock["expires_at"]) > now:
            raise AppError("另一個檢查仍在執行，本次未重複啟動。")
        return self.write("runner-lock.json", {"owner": owner,
                          "expires_at": (now + timedelta(minutes=20)).isoformat()}, sha)

    def release_lock(self, owner):
        lock, sha = self.read("runner-lock.json", {})
        if lock.get("owner") == owner:
            self.write("runner-lock.json", {}, sha)
