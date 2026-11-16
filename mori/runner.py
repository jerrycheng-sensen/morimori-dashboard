from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone, timedelta

from mori.core import (AppError, aggregate, conversion_ready, evaluate, fingerprint, period_until_yesterday,
                       rule_window, select_slot, validate_settings)
from mori.credentials import credentials_from_env
from mori.notifications import LineClient, build_batches, recipient_map
from mori.providers import provider_for
from mori.storage import GitHubStore
from mori.vault import resolve_credentials


def conversion_label(account):
    if account["platform"] == "meta":
        return account.get("meta_action_type") or "未設定"
    if account.get("google_conversion_mode") == "primary":
        return "Google 主要轉換（conversions），非保證為訂位"
    return "Google 指定事件（all_conversions）：" + ",".join(account.get("google_action_ids", []))


def check_rules(settings, credentials, now=None, provider_factory=provider_for, diagnostics=None):
    candidates, errors, reports = [], [], {}
    accounts = {a["key"]: a for a in settings["accounts"]}
    for rule in settings["rules"]:
        detail = {"規則": rule["name"], "資料區間": "—", "回傳明細數": 0, "符合名稱與類型的項目": 0,
                  "花費超過門檻的項目": 0, "異常項目": 0, "結果": "未啟用，未檢查"}
        if diagnostics is not None:
            diagnostics.append(detail)
        account = accounts[rule["account_key"]]
        since, until, state = rule_window(rule, settings, now)
        detail["資料區間"] = f"{since} ～ {until}"
        if state != "生效中":
            detail["結果"] = {"未啟用": "未啟用，未檢查", "尚未開始": "資料日期早於規則起日，略過",
                              "已到期": "資料日期超過規則迄日，略過"}.get(state, state + "，略過")
            continue
        try:
            if not conversion_ready(account):
                raise AppError("尚未設定轉換事件，已停止此規則判斷。")
            key = (account["key"], since.isoformat(), until.isoformat())
            if key not in reports:
                reports[key] = provider_factory(account, credentials).fetch(account, since, until)
            report = reports[key]
            grouped = aggregate(report["rows"], rule)
            detail["回傳明細數"] = len(report["rows"])
            detail["符合名稱與類型的項目"] = len(grouped)
            detail["花費超過門檻的項目"] = sum(x["spend"] > float(rule["minimum_spend"]) for x in grouped)
            found = evaluate(report["rows"], rule)
            detail["異常項目"] = len(found)
            detail["結果"] = ("符合異常條件" if found else "平台未回傳資料" if not report["rows"] else
                            "名稱或活動類型沒有符合" if not grouped else
                            "花費未超過門檻" if not detail["花費超過門檻的項目"] else
                            "未達 CPA／零轉換提醒條件")
            for item in found:
                candidates.append({**item, "rule_id": rule["id"], "rule_name": rule["name"],
                    "account_key": account["key"], "account_name": account["name"],
                    "since": since.isoformat(), "until": until.isoformat(),
                    "conversion_label": conversion_label(account), "_rule": rule})
        except AppError as exc:
            detail["結果"] = "讀取或檢查失敗：" + str(exc)
            errors.append({"rule": rule["name"], "error": str(exc)})
        except Exception:
            detail["結果"] = "資料格式異常，未完成檢查"
            errors.append({"rule": rule["name"], "error": "資料格式不符合預期，已停止此規則判斷。"})
    return candidates, errors


def execute(store, credentials, now=None, force=False, send=False, provider_factory=provider_for, line_factory=LineClient):
    now = now or datetime.now(timezone.utc)
    settings, _ = store.settings()
    settings = validate_settings(settings)
    runtime, _ = store.runtime()
    slot = select_slot(settings["schedule"], now, runtime["completed_slots"])
    if not force and not slot:
        return {"status": "not-due"}
    slot = slot or f"manual-{now.isoformat()}"
    owner = str(uuid.uuid4())
    summary = {"at": now.isoformat(), "slot": slot, "mode": "send" if send else "preview",
               "anomaly_count": 0, "accepted_batches": 0, "errors": [], "candidates": [], "status": "failed"}
    store.acquire_lock(owner, now)
    try:
        # 取得鎖後重讀，處理不同 workflow 同時啟動的情況。
        runtime, sha = store.runtime()
        if not force and slot in runtime["completed_slots"]:
            return {"status": "already-completed"}
        candidates, errors = check_rules(settings, credentials, now, provider_factory)
        recipients = recipient_map(credentials)
        for item in candidates:
            rule = item.pop("_rule")
            recipient_key = rule.get("recipient_key", "default")
            recipient = recipients.get(recipient_key, "")
            item["recipient_key"] = recipient_key
            item["fingerprint"] = fingerprint(rule, item["entity_id"], item["until"], recipient or recipient_key)
        summary = {"at": now.isoformat(), "slot": slot, "mode": "send" if send else "preview",
                   "anomaly_count": len(candidates), "accepted_batches": 0, "errors": errors,
                   "candidates": candidates[:50], "status": "preview"}
        if send:
            if any(not recipients.get(c["recipient_key"]) for c in candidates):
                raise AppError("有規則未設定 LINE 收件對象，不會標記排程完成。")
            line = line_factory(credentials.get("LINE_CHANNEL_ACCESS_TOKEN", ""))
            fresh = [c for c in candidates if c["fingerprint"] not in runtime["receipts"]]
            runtime.setdefault("pending", [])
            pending_ids = {fp for b in runtime["pending"] for fp in b["fingerprints"]}
            fresh = [c for c in fresh if c["fingerprint"] not in pending_ids]
            for recipient_key in sorted({c["recipient_key"] for c in fresh}):
                runtime["pending"].extend(build_batches([c for c in fresh if c["recipient_key"] == recipient_key], recipients[recipient_key], slot))
            # 先保存固定的訊息內容與 LINE retry key，再發送；回應遺失不會產生新訊息。
            sha = store.write("runtime.json", runtime, sha)
            if runtime["pending"]:
                quota = line.quota()
                if quota["limit"] is not None and quota["used"] >= quota["limit"]:
                    raise AppError("LINE 本月訊息額度已用完，未發送；待發訊息已保留。")
            while runtime["pending"]:
                batch = runtime["pending"][0]
                # LINE retry key 有效期 24 小時；超時不自動補送結果不明的舊訊息。
                created_at = batch.setdefault("created_at", now.isoformat())
                if datetime.fromisoformat(created_at) + timedelta(hours=23) < now:
                    raise AppError("有超過 23 小時的未確認通知，請在網頁確認 LINE 是否收到後解除，避免重複。")
                sha = store.write("runtime.json", runtime, sha)
                line.push(batch["recipient"], batch["text"], batch["retry_key"])
                for fp in batch["fingerprints"]:
                    runtime["receipts"][fp] = now.isoformat()
                runtime["pending"].pop(0)
                sha = store.write("runtime.json", runtime, sha)
                summary["accepted_batches"] += 1
            summary["status"] = "partial-error" if errors else "completed"
            # 已成功的通知有 receipts；有錯誤的規則留待同時段後續巡檢重試。
            if not errors and not force:
                runtime["completed_slots"].append(slot)
        runtime["runs"] = ([summary] + runtime.get("runs", []))[:30]
        runtime["completed_slots"] = runtime["completed_slots"][-124:]
        cutoff = (now - timedelta(days=40)).isoformat()
        runtime["receipts"] = {key: stamp for key, stamp in runtime["receipts"].items() if stamp >= cutoff}
        store.write("runtime.json", runtime, sha)
        return summary
    except AppError as exc:
        # 只記錄固定的安全錯誤；重新讀取以保留已保存的 pending／收件回執。
        latest, latest_sha = store.runtime()
        summary["status"] = "failed"
        summary["errors"] = summary.get("errors", []) + [{"error": str(exc)}]
        latest["runs"] = ([summary] + latest.get("runs", []))[:30]
        store.write("runtime.json", latest, latest_sha)
        raise
    finally:
        store.release_lock(owner)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="不等排程，立即檢查")
    parser.add_argument("--send", action="store_true", help="允許真實發送 LINE")
    args = parser.parse_args()
    credentials = credentials_from_env()
    send = args.send and os.environ.get("LIVE_NOTIFICATIONS_ENABLED", "").lower() == "true"
    try:
        store = GitHubStore(os.environ.get("STATE_REPO", ""), os.environ.get("STATE_TOKEN", ""), os.environ.get("STATE_BRANCH") or "main")
        credentials = resolve_credentials(credentials, store, os.environ.get("CREDENTIALS_KEY", ""))
        result = execute(store, credentials, force=args.force, send=send)
        # 公開程式儲存庫的 Actions log 只輸出狀態，不輸出帳號、花費或通知內容。
        print("Monitor status:", result["status"])
        if result.get("errors"):
            print("Some rules failed. Details are in the private execution history.")
            return 1
        if not send and result["status"] != "not-due":
            print("Preview only. No LINE messages sent.")
        return 0
    except AppError as exc:
        # AppError 只含固定且不含帳號的訊息。
        print("Monitor stopped:", str(exc))
        return 1
    except Exception:
        print("Monitor stopped: unexpected failure. Check the private execution history and configuration.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
