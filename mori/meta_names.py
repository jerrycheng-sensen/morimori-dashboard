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
    # Expanded parent objects can fail even when the ad itself is readable.
    # Retry only incomplete objects with scalar fields, in bounded batches.
    retry = [key for key in identifiers if not isinstance(current.get(key), dict)
             or current[key].get('error') or not current[key].get('name') or not current[key].get('account_id')
             or not isinstance(current[key].get('campaign'), dict)
             or not current[key]['campaign'].get('name')
             or not isinstance(current[key].get('adset'), dict)
             or not current[key]['adset'].get('name')]
    for offset in range(0, len(retry), 50):
        chunk = retry[offset:offset+50]
        try:
            response = get('', {'ids': ','.join(chunk),
                                'fields': 'id,account_id,name,status,effective_status,campaign_id,adset_id'})
            if isinstance(response, dict):
                for key in chunk:
                    data = response.get(key)
                    if isinstance(data, dict) and not data.get('error'):
                        previous = current.get(key)
                        current[key] = {**(previous if isinstance(previous, dict) else {}), **data}
        except AppError as exc:
            issues.update({key: str(exc) for key in chunk})
    account_id = str(account['account_id']).removeprefix('act_')
    parents = set()
    for key, data in current.items():
        if not isinstance(data, dict) or str(data.get('id')) != key or str(data.get('account_id')) != account_id:
            continue
        for parent in ('campaign', 'adset'):
            obj = data.get(parent)
            if not isinstance(obj, dict) or not obj.get('name'):
                value = str(data.get(parent + '_id') or '')
                if value.isdigit():
                    parents.add(value)
    parent_data = {}
    parents = sorted(parents)
    for offset in range(0, len(parents), 50):
        chunk = parents[offset:offset+50]
        try:
            response = get('', {'ids': ','.join(chunk), 'fields': 'id,account_id,name'})
            if isinstance(response, dict):
                parent_data.update(response)
        except AppError:
            pass  # Ad-level verified fields remain usable; missing parents stay unknown.
    for data in current.values():
        if not isinstance(data, dict):
            continue
        for parent in ('campaign', 'adset'):
            key = str(data.get(parent + '_id') or '')
            obj = parent_data.get(key)
            if (isinstance(obj, dict) and str(obj.get('id')) == key
                    and str(obj.get('account_id')) == account_id and not obj.get('error')):
                data[parent] = obj
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
            error = data.get('error') if isinstance(data, dict) else None
            if isinstance(error, dict):
                # Show structured codes only; platform messages can contain private data.
                code = error.get('code')
                subcode = error.get('error_subcode')
                row['name_lookup_issue'] = ('Meta 未提供最新名稱（代碼 ' + str(code) +
                                            ('／子代碼 ' + str(subcode) if subcode else '') + '）。')
            continue
        if str(data.get('id')) != identifier or str(data.get('account_id')) != account_id:
            row['name_lookup_issue'] = '回傳的廣告 ID 或所屬帳號不符，已停止使用這筆名稱。'
            continue
        fields = []
        if isinstance(data.get('name'), str) and data['name'].strip():
            row['ad_name'] = data['name']
            fields.append('ad_name')
        identity_ok = True
        for parent, field, id_field in (('campaign', 'campaign_name', 'campaign_id'),
                                        ('adset', 'adset_name', 'adset_id')):
            obj = data.get(parent)
            obj = obj if isinstance(obj, dict) else {}
            parent_id = str(obj.get('id') or data.get(id_field) or '')
            if row.get(id_field) and parent_id and str(row[id_field]) != parent_id:
                identity_ok = False
                continue
            if parent_id.isdigit() and isinstance(obj.get('name'), str) and obj['name'].strip():
                row[field] = obj['name']
                row[id_field] = parent_id
                fields.append(field)
        if not identity_ok:
            row['name_lookup_issue'] = '廣告所屬活動或群組 ID 不符，已停止使用這筆名稱。'
            continue
        row.update(verified_name_fields=fields, names_verified=len(fields) == 3,
                   name_source='依廣告 ID 核對的最新名稱' if len(fields) == 3 else '部分最新名稱已核對',
                   current_status=data.get('effective_status') or data.get('status') or 'UNKNOWN')
        missing = [label for field, label in (('ad_name', '廣告'), ('campaign_name', '廣告活動'),
                                              ('adset_name', '廣告群組')) if field not in fields]
        row['name_lookup_issue'] = '尚未取得最新名稱：' + '、'.join(missing) if missing else ''
        row['renamed'] = any(row.get('insights_' + f) != row[f] for f in fields)
