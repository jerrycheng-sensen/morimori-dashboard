"""Shared platform branding and truthful budget utilisation indicators."""
import base64
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from html import escape
from pathlib import Path


@lru_cache(maxsize=2)
def platform_brand(platform):
    name = 'Meta' if platform == 'meta' else 'Google Ads'
    filename = 'meta-logo.svg' if platform == 'meta' else 'google-ads-logo.svg'
    data = base64.b64encode((Path(__file__).resolve().parent.parent / 'assets' / filename).read_bytes()).decode()
    return (f'<span class="mori-platform-brand"><img src="data:image/svg+xml;base64,{data}" '
            f'alt="" width="38" height="38"><span>{name}</span></span>')


def budget_progress(ratio, label='預算使用進度'):
    """Keep the true percentage; cap only the drawing, never the amount."""
    label = escape(label)
    if ratio is None:
        return f'<div class="mori-budget-utilisation pending"><span>{label}</span><strong>待資料完整／預算設定</strong></div>'
    ratio = Decimal(str(ratio))
    if not ratio.is_finite() or ratio < 0:
        return budget_progress(None, label)
    percent = ratio * 100
    width = min(percent, Decimal(100))
    state = ' over' if ratio > 1 else ' near' if ratio >= Decimal('.9') else ''
    return (f'<div class="mori-budget-utilisation{state}"><div class="mori-budget-utilisation-label">'
            f'<span>{label}</span><strong>已使用 {percent:.1f}%'+ ('・已超支' if ratio > 1 else '') + '</strong></div>'
            f'<div class="mori-budget-track" role="img" aria-label="{label} {percent:.1f}%">'
            f'<div style="width:{width:.3f}%"></div></div></div>')


def totals_progress(budget, spent, remaining):
    # Remaining is unknown when any plan budget is unset or attribution overlaps.
    if remaining is None or spent is None or not budget or set(budget) != set(spent):
        return budget_progress(None)
    output = []
    for currency, amount in sorted(budget.items()):
        valid = not currency.startswith('?') and amount > 0 and spent[currency] >= 0
        output.append(budget_progress(spent[currency] / amount if valid else None,
                                      '預算使用進度' + ('・' + currency if len(budget) > 1 else '')))
    return ''.join(output)


def removed_ad_rows(plans, accounts, results):
    """Explain only paid Meta ads already included in successful plan totals.

    No extra API reads, date changes, or financial mutations. Keep each plan's
    period separate rather than adding overlapping windows or currencies.
    """
    items, seen = [], set()
    for plan in plans:
        account = accounts.get(plan['account_key'], {})
        result = results.get(plan['id']) or {}
        if account.get('platform') != 'meta' or result.get('error'):
            continue
        for row in result.get('rows', []):
            states = {row.get('current_status'), row.get('configured_status')}
            state = 'DELETED' if 'DELETED' in states else 'ARCHIVED' if 'ARCHIVED' in states else None
            if not state or not row.get('ad_id') or row.get('names_verified') is False:
                continue
            try:
                amount = Decimal(str(row.get('spend_raw', row.get('spend'))))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if not amount.is_finite() or amount <= 0:
                continue
            since = row.get('date') or result.get('since')
            until = row.get('date_stop') or result.get('until')
            key = (plan['id'], str(row['ad_id']), since, until)
            if key in seen:
                continue
            seen.add(key)
            items.append({'平台': 'Meta', '平台計畫': plan['name'], '廣告帳號': account.get('name', ''),
                          '廣告名稱': row.get('ad_name', ''), '廣告 ID': str(row['ad_id']),
                          'API 狀態': '已刪除' if state == 'DELETED' else '已封存',
                          '已計入花費': amount, '幣別': row.get('currency') or result.get('currency'),
                          '花費查詢起日': since, '花費查詢迄日': until,
                          '狀態核對時間': str(row.get('names_checked_at', '未提供'))[:19].replace('T', ' ')})
    return items


def removed_ad_count(items):
    return len({(row['廣告帳號'], row['廣告 ID']) for row in items})


def preview_campaign_totals(rows):
    """Summarise the already matched rows, never add totals per matching rule."""
    groups = {}
    for row in rows:
        key = (row.get('campaign_id', ''), row.get('currency', ''))
        group = groups.setdefault(key, {'廣告活動': row.get('campaign_name', ''),
                                       '廣告活動 ID': key[0], '幣別': key[1],
                                       '認列花費': Decimal(0), '曝光': 0, '點擊': 0, '_units': set()})
        group['認列花費'] += Decimal(str(row.get('spend_raw', row.get('spend', 0))))
        group['曝光'] += int(row.get('impressions') or 0)
        group['點擊'] += int(row.get('clicks') or 0)
        kind = 'asset_group' if row.get('asset_group_id') else 'ad'
        unit = row.get('asset_group_id') or row.get('ad_id')
        if unit:
            group['_units'].add((kind, str(unit)))
    output = []
    for group in groups.values():
        group['廣告／素材群組數'] = len(group.pop('_units'))
        output.append(group)
    return sorted(output, key=lambda r: (str(r['幣別']), -r['認列花費'], str(r['廣告活動 ID'])))
