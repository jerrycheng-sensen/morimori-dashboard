"""Account edits preserve stable references and reject accidental duplicates."""
import copy

from mori.core import AppError, validate_settings


def normalized_id(value):
    return str(value).strip().removeprefix("act_").replace("-", "").strip()


def account_label(account):
    platform = "Meta" if account["platform"] == "meta" else "Google Ads"
    if account["platform"] == "meta":
        event = account.get("meta_action_type") or "未設定訂位事件"
    else:
        event = ",".join(account.get("google_action_ids", [])) or "未設定訂位事件"
    return f'{account["name"]}｜{platform}｜{account["account_id"]}｜{event}｜識別碼 {account["key"]}'


def save_account(settings, account):
    updated = copy.deepcopy(settings)
    existing = next((a for a in updated["accounts"] if a["key"] == account["key"]), None)
    if existing and existing["platform"] != account["platform"]:
        raise AppError("現有帳號不可更換平台，請新增另一個帳號。")
    if existing and normalized_id(existing["account_id"]) != normalized_id(account["account_id"]):
        if any(x.get("account_key") == existing["key"] for group in ("projects", "rules") for x in updated[group]):
            raise AppError("這筆帳號已有專案或規則使用，不能改成另一個廣告帳號；請新增帳號。")
    duplicates = [a for a in updated["accounts"] if a["key"] != account["key"]
                  and a["platform"] == account["platform"]
                  and normalized_id(a["account_id"]) == normalized_id(account["account_id"])]
    # Legacy duplicates remain editable so the user can choose which record to keep.
    identity_changed = not existing or normalized_id(existing["account_id"]) != normalized_id(account["account_id"])
    if duplicates and identity_changed:
        raise AppError("這個平台的廣告帳號已存在。請切換「編輯既有帳號」，不要再次新增。")
    item = {**(existing or {}), **copy.deepcopy(account), "account_id": normalized_id(account["account_id"])}
    if existing:
        updated["accounts"] = [item if a["key"] == item["key"] else a for a in updated["accounts"]]
    else:
        updated["accounts"].append(item)
    return validate_settings(updated)


def account_dependencies(settings, key):
    return [(group, item) for group in ("projects", "rules") for item in settings[group]
            if item.get("account_key") == key]


def delete_account(settings, key, replacement_key=None):
    updated = copy.deepcopy(settings)
    account = next((a for a in updated["accounts"] if a["key"] == key), None)
    if not account:
        raise AppError("帳號已不存在，請重新整理。")
    dependencies = account_dependencies(updated, key)
    if dependencies:
        replacement = next((a for a in updated["accounts"] if a["key"] == replacement_key and a["key"] != key), None)
        if not replacement or replacement["platform"] != account["platform"] or normalized_id(replacement["account_id"]) != normalized_id(account["account_id"]):
            raise AppError("帳號已有專案或規則使用；請先移轉到同一廣告帳號的保留紀錄，或先修改專案與規則。")
        for _, item in dependencies:
            item["account_key"] = replacement_key
    updated["accounts"] = [a for a in updated["accounts"] if a["key"] != key]
    return validate_settings(updated)
