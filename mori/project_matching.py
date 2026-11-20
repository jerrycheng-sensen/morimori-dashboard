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

def matches(plan, row):
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
