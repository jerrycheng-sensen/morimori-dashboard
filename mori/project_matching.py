"""Literal project attribution shared by budget matching and validation."""
from mori.core import AppError

FIELDS = {'campaign_name': '廣告活動', 'adset_name': '廣告群組',
          'ad_id': '廣告（以 ID 精確指定）', 'ad_name': '廣告名稱（僅 Meta）',
          'asset_group_name': '素材群組名稱（PMax）', 'asset_group_id': '素材群組 ID（PMax）',
          'headlines': '標題', 'descriptions': '說明',
          'paths': '路徑'}

def conditions(plan):
    return plan.get('match_conditions') or [{'field': plan.get('match_field', 'campaign_name'),
                                            'text': plan.get('keyword', '')}]

def validate_matching(plan, platform):
    units = plan.get('assigned_units', [])
    if not isinstance(units, list) or len(units) > 10000:
        raise AppError('手動歸案資料格式不正確。')
    for unit in units:
        if (not isinstance(unit, dict) or set(unit) != {'kind', 'id', 'campaign_id', 'adset_id'}
                or unit['kind'] not in ('ad', 'asset_group')
                or not all(isinstance(unit[k], str) and unit[k].isdigit() for k in ('id', 'campaign_id'))
                or not isinstance(unit['adset_id'], str) or (unit['adset_id'] and not unit['adset_id'].isdigit())
                or (platform == 'meta' and unit['kind'] != 'ad')):
            raise AppError('手動歸案的廣告 ID 格式不正確。')
    rules = conditions(plan)
    if not isinstance(rules, list) or not 1 <= len(rules) <= 6:
        raise AppError('請設定 1～6 個廣告認列條件。')
    if plan.get('match_mode', 'all') not in ('all', 'any'):
        raise AppError('廣告認列條件組合不正確。')
    allowed = set(FIELDS) if platform == 'google' else {'campaign_name', 'adset_name', 'ad_name'}
    if platform == 'google':
        allowed.remove('ad_name')
    for rule in rules:
        if not isinstance(rule, dict) or rule.get('field') not in allowed or not isinstance(rule.get('text'), str) or not rule['text'].strip():
            raise AppError('請選擇有效的廣告認列欄位並填寫文字。')
        if not any(t.strip() for t in rule['text'].split('|')):
            raise AppError('認列文字不可只有分隔符號。')
        if rule['field'] in ('ad_id', 'asset_group_id') and not rule['text'].strip().isdigit():
            raise AppError('廣告／素材群組 ID 請填完整數字。')

def unit_identity(row):
    kind = 'asset_group' if row.get('asset_group_id') else 'ad'
    value = row.get('asset_group_id') if kind == 'asset_group' else row.get('ad_id')
    if not value or not row.get('campaign_id'):
        return None
    return {'kind': kind, 'id': str(value), 'campaign_id': str(row['campaign_id']),
            'adset_id': '' if kind == 'asset_group' else str(row.get('adset_id') or '')}


def matches(plan, row):
    unit = unit_identity(row)
    if unit and unit in plan.get('assigned_units', []):
        return True
    def match(rule):
        value = row.get(rule['field']) or ''
        values = value if isinstance(value, list) else [value]
        text = rule['text'].strip().casefold()
        if rule['field'] in ('ad_id', 'asset_group_id'):
            return str(value) == text
        # Never match across two different assets or path segments.
        tokens = [t.strip() for t in text.split('|') if t.strip()]
        return any(t in str(item).casefold() for t in tokens for item in values)
    checks = [match(rule) for rule in conditions(plan)]
    return any(checks) if plan.get('match_mode', 'all') == 'any' else all(checks)


def verified_match(plan, row):
    """True/False when attribution is certain; None if a required name is unknown.

    An unrelated, verified condition can exclude a row even if another field is
    unavailable. Explicit immutable-ID assignments do not depend on names.
    """
    if row.get('names_verified') is not False:
        return matches(plan, row)
    unit = unit_identity(row)
    if unit and unit in plan.get('assigned_units', []):
        return True
    verified = set(row.get('verified_name_fields', []))
    checks = []
    for rule in conditions(plan):
        if rule['field'] in ('campaign_name', 'adset_name', 'ad_name') and rule['field'] not in verified:
            checks.append(None)
        else:
            checks.append(matches({'match_conditions': [rule]}, row))
    if plan.get('match_mode', 'all') == 'any':
        return True if True in checks else None if None in checks else False
    return False if False in checks else None if None in checks else True
