"""Join current Meta object names to historical costs by verified immutable IDs."""
from datetime import datetime
import re
from mori.core import AppError, TAIPEI


def refresh_names(get, account, rows):
    identifiers = sorted({str(r['ad_id']) for r in rows if r.get('ad_id')})
    if any(not re.fullmatch(r'\d+', value) for value in identifiers):
        raise AppError('Meta 廣告 ID 格式不正確，無法核對最新名稱。')
    current, issues = {}, {}
    for offset in range(0, len(identifiers), 50):
        chunk = identifiers[offset:offset+50]
        try:
            response = get('', {'ids': ','.join(chunk),
                                'fields': 'id,account_id,name,status,effective_status,campaign{id,name},adset{id,name}'})
            if isinstance(response, dict):
                current.update({identifier: response.get(identifier) for identifier in chunk})
        except AppError as exc:
            # request_json supplies redacted user-facing errors only.
            issues.update({identifier: str(exc) for identifier in chunk})
    checked = datetime.now(TAIPEI).isoformat()
    account_id = str(account['account_id']).removeprefix('act_')
    for row in rows:
        for field in ('ad_name', 'adset_name', 'campaign_name'):
            row['insights_' + field] = row.get(field, '')
        row.update(names_verified=False, name_source='花費報表名稱（最新名稱待核對）', names_checked_at=checked,
                   current_status='UNKNOWN', renamed=False)
        identifier = str(row.get('ad_id') or '')
        data = current.get(identifier)
        row['name_lookup_issue'] = issues.get(identifier, '未取得可驗證的最新名稱或所屬帳號資料。')
        if not isinstance(data, dict) or data.get('error'):
            continue
        campaign, adset = data.get('campaign') or {}, data.get('adset') or {}
        if not isinstance(campaign, dict) or not isinstance(adset, dict):
            continue
        if (str(data.get('id')) != identifier or str(data.get('account_id')) != account_id
                or not all(isinstance(value, str) and value.strip() for value in (data.get('name'), campaign.get('name'), adset.get('name')))
                or not str(campaign.get('id', '')).isdigit() or not str(adset.get('id', '')).isdigit()
                or (row.get('campaign_id') and str(row['campaign_id']) != str(campaign['id']))
                or (row.get('adset_id') and str(row['adset_id']) != str(adset['id']))):
            continue
        row.update(name_lookup_issue='', ad_name=data['name'], campaign_name=campaign['name'], adset_name=adset['name'],
                   campaign_id=str(campaign['id']), adset_id=str(adset['id']), names_verified=True,
                   name_source='依廣告 ID 核對的最新名稱', current_status=data.get('effective_status') or data.get('status') or 'UNKNOWN')
        row['renamed'] = any(row.get('insights_' + f) != row[f] for f in ('ad_name', 'campaign_name', 'adset_name'))
