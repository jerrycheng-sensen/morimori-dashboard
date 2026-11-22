"""Find paid attribution units outside every project, using exact period reports."""
import copy
import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from mori.account_funding import account_identity
from mori.core import AppError, TAIPEI, validate_settings
from mori.project_matching import matches, unit_identity


def scan(settings, fetch, start, end, only_account=None):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if end < start or (end - start).days > 1095:
        raise AppError('請選擇三年內的查詢期間。')
    accounts = {account_identity(a): a for a in settings['accounts']
                if only_account is None or account_identity(a) == only_account}
    result = {'pending': [], 'conflicts': [], 'covered': [], 'errors': [], 'warnings': [],
              'since': str(start), 'until': str(end), 'at': datetime.now(TAIPEI).isoformat()}
    for physical, account in accounts.items():
        candidates = [p for p in settings['projects'] if account_identity(next(a for a in settings['accounts'] if a['key'] == p['account_key'])) == physical]
        # Within each segment, a plan is either active for the entire interval or absent.
        # Meta keeps whole-period API amounts; daily rounded amounts are never summed.
        cuts = {start, end + timedelta(days=1)}
        for plan in candidates:
            for boundary in (date.fromisoformat(plan['start']), date.fromisoformat(plan['end']) + timedelta(days=1)):
                if start < boundary <= end:
                    cuts.add(boundary)
        cuts = sorted(cuts)
        rows_for_account = {'pending': [], 'conflicts': [], 'covered': []}
        try:
            for left, stop in zip(cuts, cuts[1:]):
                right = stop - timedelta(days=1)
                report = fetch(account, left, right)
                if not report.get('currency') or not isinstance(report.get('rows'), list):
                    raise AppError('平台明細不完整，無法確認是否漏列。')
                if account['platform'] == 'google' and not report.get('attribution_detail'):
                    raise AppError('Google 尚未提供廣告／素材群組明細，無法檢查。')
                if report.get('warnings'):
                    # A live campaign/detail mismatch cannot certify complete coverage.
                    raise AppError('平台明細尚未完整同步，請稍後重新檢查。')
                active = [p for p in candidates if p['start'] <= str(left) and p['end'] >= str(right)]
                seen = set()
                for row in report['rows']:
                    cost = Decimal(str(row.get('spend_raw', row.get('spend'))))
                    if not cost.is_finite() or cost < 0 or row.get('currency') != report['currency']:
                        raise AppError('花費或幣別資料不正確，未使用不完整數據。')
                    if cost == 0:
                        continue
                    unit = unit_identity(row)
                    if not unit:
                        raise AppError('部分有花費的廣告缺少 ID，無法安全歸案。')
                    first = date.fromisoformat(str(row.get('date', left)))
                    last = date.fromisoformat(str(row.get('date_stop', row.get('date', right))))
                    if first < left or last > right or last < first:
                        raise AppError('平台回傳日期不符，請重新檢查。')
                    identity = (tuple(sorted(unit.items())), str(first), str(last))
                    if identity in seen:
                        raise AppError('平台回傳重複明細，已停止檢查。')
                    seen.add(identity)
                    owners = [p['id'] for p in active if matches(p, row)]
                    status = 'pending' if not owners else 'covered' if len(owners) == 1 else 'conflicts'
                    key = hashlib.sha256(json.dumps([physical, unit, str(first), str(last)], sort_keys=True).encode()).hexdigest()[:24]
                    rows_for_account[status].append({'key': key, 'account_key': account['key'], 'physical': physical,
                        'platform': account['platform'], 'account_name': account['name'], 'unit': unit, 'row': row, 'since': str(first), 'until': str(last),
                        'amount': str(cost), 'currency': report['currency'], 'owners': owners})
            for status, values in rows_for_account.items():
                result[status].extend(values)
        except (AppError, KeyError, ValueError, TypeError, InvalidOperation) as exc:
            message = str(exc) if isinstance(exc, AppError) else '明細格式不完整，請重新檢查。'
            result['errors'].append(account['name'] + '：' + message)
    return result


def assign(settings, fetch, item, plan_id, today=None):
    today = today or datetime.now(TAIPEI).date()
    plan = next((p for p in settings['projects'] if p['id'] == plan_id), None)
    account = next((a for a in settings['accounts'] if plan and a['key'] == plan['account_key']), None)
    if not account or not plan.get('group_id') or tuple(item['physical']) != account_identity(account):
        raise AppError('請選擇同一廣告帳號、已設定平台投放計畫的專案。')
    if max(plan['start'], item['since']) > min(plan['end'], item['until']):
        raise AppError('這筆花費不在所選計畫的廣告走期內，請先確認或調整投放日期。')
    # Validate the entire target window, not only the visible pending row.
    fresh = scan(settings, fetch, plan['start'], min(plan['end'], str(today)), account_identity(account))
    if fresh['errors']:
        raise AppError('儲存前核對失敗：' + '；'.join(fresh['errors']))
    same = lambda r: r['unit'] == item['unit']
    if any(same(r) for r in fresh['covered'] + fresh['conflicts']):
        raise AppError('此廣告在所選走期內已有歸屬或重複歸案，請先調整原專案條件。')
    if not any(same(r) for r in fresh['pending']):
        raise AppError('重新核對後沒有這筆待歸案花費，請更新清單。')
    updated = copy.deepcopy(settings)
    target = next(p for p in updated['projects'] if p['id'] == plan_id)
    target.setdefault('assigned_units', []).append(copy.deepcopy(item['unit']))
    target.setdefault('assignment_history', []).append({'action': 'assign', 'unit': copy.deepcopy(item['unit']),
        'at': datetime.now(TAIPEI).isoformat(), 'checked_since': fresh['since'], 'checked_until': fresh['until']})
    return validate_settings(updated)


def undo(settings, plan_id, unit):
    updated = copy.deepcopy(settings)
    plan = next(p for p in updated['projects'] if p['id'] == plan_id)
    plan['assigned_units'] = [u for u in plan.get('assigned_units', []) if u != unit]
    plan.setdefault('assignment_history', []).append({'action': 'undo', 'unit': copy.deepcopy(unit), 'at': datetime.now(TAIPEI).isoformat()})
    return validate_settings(updated)


def reclassify(result, settings):
    """Reapply a manual binding to the last checked rows, retaining their read time."""
    updated = copy.deepcopy(result)
    rows = updated['pending'] + updated['covered'] + updated['conflicts']
    for category in ('pending', 'covered', 'conflicts'):
        updated[category] = []
    accounts = {a['key']: a for a in settings['accounts']}
    for row in rows:
        row['owners'] = [p['id'] for p in settings['projects']
                         if account_identity(accounts[p['account_key']]) == tuple(row['physical'])
                         and p['start'] <= row['since'] and p['end'] >= row['until']
                         and matches(p, row['row'])]
        category = 'pending' if not row['owners'] else 'covered' if len(row['owners']) == 1 else 'conflicts'
        updated[category].append(row)
    return updated
