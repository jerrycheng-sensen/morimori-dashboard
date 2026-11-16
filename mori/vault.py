"""Encrypted credentials shared by the dashboard and scheduled runner.

The encryption key lives only in deployment secrets, never in the state repo.
"""
from __future__ import annotations
import json
from cryptography.fernet import Fernet, InvalidToken
from mori.core import AppError

FIELDS = {
    "SOURCE_REPO": ("程式儲存庫（擁有者／名稱）", False, "github"),
    "SOURCE_TOKEN": ("GitHub 排程啟動權杖", True, "github"),
    "SOURCE_BRANCH": ("程式分支（未填預設 main）", False, "github"),
    "META_ACCESS_TOKEN": ("Meta 廣告讀取權杖", True, "meta"),
    "META_API_VERSION": ("Meta API 版本", False, "meta"),
    "GOOGLE_CLIENT_ID": ("Google 用戶端 ID", True, "google"),
    "GOOGLE_CLIENT_SECRET": ("Google 用戶端密鑰", True, "google"),
    "GOOGLE_REFRESH_TOKEN": ("Google 更新權杖", True, "google"),
    "GOOGLE_DEVELOPER_TOKEN": ("Google 開發人員權杖", True, "google"),
    "GOOGLE_LOGIN_CUSTOMER_ID": ("Google 管理員帳號 ID（有使用管理員帳號才填）", False, "google"),
    "GOOGLE_API_VERSION": ("Google API 版本", False, "google"),
    "LINE_CHANNEL_ACCESS_TOKEN": ("LINE 通知權杖", True, "line"),
    "LINE_RECIPIENT_ID": ("LINE 通知對象 ID", True, "line"),
    "LINE_RECIPIENTS_JSON": ("LINE 多對象設定（進階）", True, "line"),
}

class CredentialVault:
    def __init__(self, store, key):
        self.store = store
        try:
            self.cipher = Fernet(str(key).encode())
        except (ValueError, TypeError):
            raise AppError("請先在部署 Secrets 設定有效的 CREDENTIALS_KEY，才能加密保存權杖。") from None

    def read(self):
        envelope, sha = self.store.read("credentials.encrypted.json", {})
        if not envelope:
            return {}, sha
        try:
            if envelope.get("version") != 1:
                raise ValueError()
            values = json.loads(self.cipher.decrypt(envelope["ciphertext"].encode()))
            if not isinstance(values, dict) or any(k not in FIELDS or not isinstance(v, str) for k, v in values.items()):
                raise ValueError()
            return values, sha
        except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
            raise AppError("權杖資料無法解密，請確認網頁與排程使用原本相同的 CREDENTIALS_KEY；資料未被覆寫。") from None

    def update(self, changes):
        if any(k not in FIELDS or not isinstance(v, str) for k, v in changes.items()):
            raise AppError("權杖欄位格式不正確。")
        values, sha = self.read()
        # Empty inputs preserve saved credentials. Never replace a token with a mask.
        for key, value in changes.items():
            value = value.strip()
            if value and set(value) <= {"*", "•", "●"}:
                raise AppError("請填入完整權杖，不能使用遮罩字元。")
            if value:
                values[key] = value
        ciphertext = self.cipher.encrypt(json.dumps(values).encode()).decode()
        self.store.write("credentials.encrypted.json", {"version": 1, "ciphertext": ciphertext}, sha,
                         message="更新加密串接設定 [skip ci]")


def resolve_credentials(base, store, key):
    result = dict(base)
    if key:
        saved, _ = CredentialVault(store, key).read()
        result.update({k: v for k, v in saved.items() if v})
    else:
        envelope, _ = store.read("credentials.encrypted.json", {})
        if envelope:
            raise AppError("已有加密權杖，但這個執行環境尚未設定 CREDENTIALS_KEY；已停止以免使用舊憑證。")
    return result
