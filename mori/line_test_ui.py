"""Explicit, one-off LINE delivery test, independent of anomaly rules and scheduling."""
import hashlib
import uuid
from datetime import datetime

import streamlit as st

from mori.core import AppError, TAIPEI, period_until_yesterday
from mori.notifications import LineClient, build_batches, recipient_map


def sample_message():
    since, until = period_until_yesterday(1)
    item = {"account_name": "森森 Meta（示範）", "rule_name": "台南永華店開幕｜訂位異常（示範）",
            "entity_name": "永華店開幕｜新客｜示範廣告", "since": str(since), "until": str(until),
            "currency": "TWD", "spend": 120, "conversions": 2, "cpa": 60,
            "conversion_label": "offsite_conversion.fb_pixel_purchase",
            "reason": "花費與 CPA 均超過門檻", "fingerprint": "sample-only"}
    body = build_batches([item], "sample-only", "手動推播測試")[0]["text"]
    return ("🧪【LINE 串接測試】\n以下數字為示範，不是真實廣告異常。\n"
            "測試目的：確認此通知對象能收到訊息，並預覽異常回報格式。\n\n" + body +
            "\n收到此訊息只代表手動推播測試成功；不代表背景排程已啟用。")


def render_line_test(creds, demo=False):
    st.subheader("LINE 推播測試")
    st.caption("直接使用已儲存的 LINE 設定發送一則測試，不用新增異常規則，也不會啟動其他規則或排程。")
    try:
        recipients = {k: v for k, v in recipient_map(creds).items() if v}
    except AppError as exc:
        st.error(str(exc))
        return
    if not recipients or not creds.get("LINE_CHANNEL_ACCESS_TOKEN"):
        st.info("請先在上方 LINE 通知串接儲存權杖與通知對象 ID，再執行測試。")
        return
    target = st.selectbox("測試通知對象", list(recipients), key="line_test_recipient")
    recipient = recipients[target]
    kind = "群組" if recipient.startswith("C") else "個人" if recipient.startswith("U") else "其他對象"
    st.write(f"收件對象：{target}｜{kind}｜ID 尾碼 {recipient[-6:]}")
    if not recipient.startswith("C"):
        st.caption("目前選取的不是群組 ID。要驗證群組收訊，請選擇已儲存的 C 開頭群組 ID；不能用個人收訊代替。")
    identity = hashlib.sha256((creds["LINE_CHANNEL_ACCESS_TOKEN"] + "|" + recipient).encode()).hexdigest()
    tests = st.session_state.setdefault("line_delivery_tests", {})
    if identity not in tests:
        tests[identity] = {"text": sample_message(), "retry_key": str(uuid.uuid4()), "accepted": False}
    test = tests[identity]
    st.text(test["text"])
    if st.button("發送 LINE 測試訊息", key="send_line_test", disabled=demo or test["accepted"]):
        try:
            result = LineClient(creds["LINE_CHANNEL_ACCESS_TOKEN"]).push(recipient, test["text"], test["retry_key"])
        except AppError as exc:
            st.error(str(exc))
            st.caption("若重新按下，會沿用同一則訊息及重試碼，避免重複發送。")
        else:
            test["accepted"] = True
            test["at"] = datetime.now(TAIPEI).isoformat()
            test["result"] = result
            st.rerun()
    if test["accepted"]:
        st.success("LINE API 已接受這則測試訊息。請到上述個人／群組聊天室確認是否收到；尚不能只依 API 回應判定送達。")
        st.caption("受理時間：" + test["at"] + "。此測試不會更改異常規則或背景排程。")
