"""Shared platform branding and truthful budget utilisation indicators."""
import base64
from decimal import Decimal
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
