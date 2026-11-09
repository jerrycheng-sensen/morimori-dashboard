import uuid
import json

import requests

from mori.core import AppError


def recipient_map(credentials):
    try:
        recipients = json.loads(credentials.get("LINE_RECIPIENTS_JSON") or "{}")
        if not isinstance(recipients, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in recipients.items()):
            raise ValueError()
    except (ValueError, TypeError):
        raise AppError("LINE_RECIPIENTS_JSON 必須是對象代號與 LINE ID 的 JSON 物件。") from None
    if credentials.get("LINE_RECIPIENT_ID"):
        recipients.setdefault("default", credentials["LINE_RECIPIENT_ID"])
    return recipients


class LineClient:
    def __init__(self, token, session=None):
        if not token:
            raise AppError("尚未設定 LINE_CHANNEL_ACCESS_TOKEN。")
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def quota(self):
        values = []
        for path in ("quota", "quota/consumption"):
            try:
                response = self.session.get(f"https://api.line.me/v2/bot/message/{path}",
                                            headers=self.headers, timeout=20)
                if not response.ok:
                    raise AppError(f"LINE 額度查詢失敗（HTTP {response.status_code}）。")
                values.append(response.json())
            except (requests.RequestException, ValueError):
                raise AppError("LINE 額度查詢連線失敗。") from None
        return {"limit": values[0].get("value") if values[0].get("type") == "limited" else None,
                "used": values[1].get("totalUsage", 0)}

    def push(self, recipient, text, retry_key):
        if not recipient or recipient[0] not in ("U", "C", "R"):
            raise AppError("請先設定有效的 LINE 個人／群組 ID。")
        try:
            response = self.session.post("https://api.line.me/v2/bot/message/push", timeout=30,
                headers={**self.headers, "X-Line-Retry-Key": retry_key},
                json={"to": recipient, "messages": [{"type": "text", "text": text}]})
        except requests.RequestException:
            raise AppError("LINE 發送結果尚未確認；已保留相同重試碼供下次重試。") from None
        # 只有具 accepted request id 的 409 才能視為同一 retry key 已送達。
        if response.status_code == 409 and response.headers.get("x-line-accepted-request-id"):
            return "already-accepted"
        if not response.ok:
            raise AppError(f"LINE 發送失敗（HTTP {response.status_code}），請檢查額度與收件對象。")
        return "accepted"


def build_batches(candidates, recipient, slot):
    chunks, texts, ids = [], [], []
    header = f"⚠️ 森森廣告異常提醒\n檢查時段：{slot}\n"
    for item in candidates:
        cpa = "無轉換" if item["cpa"] is None else f'{item["cpa"]:,.2f}'
        text = (f'\n【{item["account_name"]}｜{item["rule_name"]}】\n'
                f'{item["entity_name"]}\n資料：{item["since"]}～{item["until"]}\n'
                f'花費 {item["currency"]} {item["spend"]:,.2f}｜轉換 {item["conversions"]:g}｜CPA {cpa}\n'
                f'事件：{item["conversion_label"]}\n原因：{item["reason"]}\n')
        # 名稱長度不影響訊息上限，完整結果仍保存在私人執行紀錄。
        text = text[:1600]
        if len(header + "".join(texts) + text) > 4500 and texts:
            chunks.append({"text": header + "".join(texts), "fingerprints": ids})
            texts, ids = [], []
        texts.append(text)
        ids.append(item["fingerprint"])
    if texts:
        chunks.append({"text": header + "".join(texts), "fingerprints": ids})
    for chunk in chunks:
        chunk["recipient"] = recipient
        chunk["retry_key"] = str(uuid.uuid5(uuid.NAMESPACE_URL, recipient + "|" + "|".join(chunk["fingerprints"])))
    return chunks
