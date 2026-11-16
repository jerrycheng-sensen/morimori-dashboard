"""Admin-only connection setup. No decrypted secret is rendered as a widget value."""
from __future__ import annotations
import hashlib
import hmac
import json
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from mori.core import AppError, TAIPEI
from mori.providers import provider_for
from mori.vault import CredentialVault, FIELDS


def signature(creds, account, key):
    # HMAC, rather than a plain digest, also protects low entropy configuration.
    selected = {k: v for k, v in creds.items() if k.startswith(account['platform'].upper() + '_')}
    payload = json.dumps([selected, account], sort_keys=True).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def connection_panel(store, creds, secret, accounts, demo=False):
    st.subheader('權杖與連線管理')
    st.caption('輸入以密碼遮罩顯示；儲存後不回填完整權杖。已有的欄位留空即可保留。')
    vault_key = str(secret('CREDENTIALS_KEY'))
    vault = None
    if vault_key and not demo:
        try:
            vault = CredentialVault(store, vault_key)
        except AppError as exc:
            st.error(str(exc))
    if not vault:
        st.info('表單的加密儲存尚未啟用。請先由部署管理員在 Streamlit Secrets 設定 CREDENTIALS_KEY。原有 Secrets 權杖仍可讀取。')
        with st.expander('一次性啟用說明'):
            st.write('產生 Fernet 加密金鑰，存入 Streamlit Secrets 的 CREDENTIALS_KEY；需要背景巡檢時，將同一把金鑰存入 GitHub Actions Secrets。金鑰不能放進程式碼或私人設定庫。')
            st.code('python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"', language='bash')
            st.caption('這是給部署管理員執行的指令。不要把產生的金鑰貼到對話。更換金鑰前必須先完成資料重新加密。')

    vault_values = {}
    if vault:
        vault_values, _ = vault.read()
    inventory = []
    for key, (label, sensitive, group) in FIELDS.items():
        present = bool(creds.get(key))
        inventory.append({'平台': {'meta': 'Meta', 'google': 'Google', 'line': 'LINE', 'github': 'GitHub'}[group],
                          '欄位': label,
                          '設定狀態': '已儲存' if present else '未設定',
                          '目前內容': '********' if present and sensitive else str(creds.get(key) or '—'),
                          '套用來源': '加密表單' if vault_values.get(key) else ('部署 Secrets' if present else '—')})
    st.dataframe(pd.DataFrame(inventory), hide_index=True, width='stretch')
    st.caption('已儲存代表系統讀到設定；連線是否可用，請看下方各廣告帳號的實際測試結果。')

    for group, title in [('meta', 'Meta 廣告串接（先完成這裡）'),
                         ('google', 'Google Ads 串接（稍後設定）'), ('line', 'LINE 通知串接'),
                         ('github', 'GitHub 排程啟動設定')]:
        with st.expander(title, expanded=group == 'meta'):
            with st.form('credential_form_' + group, clear_on_submit=True):
                changes = {}
                for key, (label, sensitive, field_group) in FIELDS.items():
                    if field_group != group:
                        continue
                    changes[key] = st.text_input(label, value='', type='password' if sensitive else 'default',
                                                 placeholder='已設定；留空保留，輸入新值以更換' if creds.get(key) else '尚未設定',
                                                 help=key, disabled=not bool(vault))
                submitted = st.form_submit_button('加密儲存並套用', disabled=not bool(vault))
            if submitted:
                try:
                    if not any(v.strip() for v in changes.values()):
                        st.info('沒有輸入新值，原設定保留。')
                    else:
                        vault.update(changes)
                        st.session_state.pop('connection_checks', None)
                        st.session_state.pop('report_view', None)
                        st.session_state.save_notice = '串接設定已加密儲存並套用至網頁；請執行連線測試。'
                        st.rerun()
                except AppError as exc:
                    st.error(str(exc))

    with st.expander('系統基礎設定（初次部署使用，平常不必更動）'):
        bootstrap = []
        for key, label in [('STATE_REPO', '私人資料庫位置'), ('STATE_TOKEN', '私人資料庫存取權杖'),
                           ('CREDENTIALS_KEY', '權杖加密金鑰'), ('APP_PASSWORD', '管理登入密碼')]:
            bootstrap.append({'設定': label, '狀態': '已設定' if secret(key) else '未設定',
                              '內容': '********' if secret(key) else '—'})
        st.dataframe(pd.DataFrame(bootstrap), hide_index=True, width='stretch')
        st.caption('這些設定負責啟動資料讀取與解密，因此保留於部署環境。若要更換，須由部署管理員處理；平台權杖請使用上方表單。')

    st.subheader('廣告帳號是否已連上')
    st.caption('測試只讀取數據，不調整投放、不發送通知。成功讀取與訂位數核對是兩個不同步驟。')
    if not accounts:
        st.info('請先在下方新增廣告帳號，再回來測試。')
    checks = st.session_state.setdefault('connection_checks', {})
    rows = []
    for account in accounts:
        check = checks.get(account['key'], {})
        current_signature = signature(creds, account, str(secret('APP_PASSWORD')))
        valid = check.get('signature') == current_signature
        status = check.get('status', '尚未測試') if valid else '尚未測試／設定已變更'
        rows.append({'帳號': account['name'], '平台': account['platform'], '連線狀態': status,
                     '測試時間（台灣）': check.get('at', '—') if valid else '—',
                     '訂位口徑': '已指定，仍須與廣告後台核對' if (account.get('meta_action_type') if account['platform'] == 'meta' else account.get('google_action_ids')) else '尚未指定'})
        if st.button('測試連線並讀取數據｜' + account['name'], key='test_connection_' + account['key'], disabled=demo):
            try:
                end = datetime.now(TAIPEI).date() - timedelta(days=1)
                with st.spinner('正在向廣告平台讀取最近七天數據…'):
                    report = provider_for(account, creds).fetch(account, end - timedelta(days=6), end)
                status = '已連線，已讀取數據' if report['rows'] else '已連線，此區間未回傳廣告數據'
                checks[account['key']] = {'signature': current_signature, 'status': status,
                                         'at': datetime.now(TAIPEI).strftime('%Y/%m/%d %H:%M')}
                if account['platform'] == 'meta':
                    actions = sorted({a for r in report['rows'] for a in r.get('available_actions', [])})
                    checks[account['key']]['actions'] = actions
                st.rerun()
            except AppError as exc:
                checks[account['key']] = {'signature': current_signature, 'status': '連線失敗，請檢查授權與設定',
                                         'at': datetime.now(TAIPEI).strftime('%Y/%m/%d %H:%M')}
                st.error(str(exc))
            except Exception:
                st.error('連線測試未完成，請稍後重試。')
        if valid and check.get('actions'):
            with st.expander(account['name'] + '｜實際回傳的事件代碼'):
                st.write(check['actions'])
                st.caption('同一筆訂位可能對應多種購買彙總事件；只指定一種，並與後台購買數核對。')
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    st.caption('驗證結果只保留於本次登入，代表最後一次測試結果；權杖仍可能在之後失效。LINE 與背景巡檢尚須分別驗證，不能由網頁讀取成功推定。')
