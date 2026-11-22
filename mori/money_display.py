"""Presentation only: never feed rounded display strings back into accounting."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import re


def plan_platform(settings, plan_id):
    plan = next((p for p in settings['projects'] if p['id'] == plan_id), {})
    return next((a['platform'] for a in settings['accounts'] if a['key'] == plan.get('account_key')), 'combined')


def money_text(value, platform='combined'):
    if value is None:
        return '—'
    amount = Decimal(str(value))
    if not amount.is_finite():
        return '—'
    places = 0 if platform == 'meta' else 2
    rounded = amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    return f'{rounded:,.{places}f}'


def money_html(value, platform='combined'):
    text = money_text(value, platform)
    if '.' not in text:
        return escape(text)
    integer, fraction = text.rsplit('.', 1)
    return f'{integer}<span class="mori-money-fraction">.{fraction}</span>'


def soften_decimals(text):
    """For already formatted, escaped monetary prose; never use on arbitrary HTML."""
    return re.sub(r'(?<=\d)(\.\d{2})(?!\d)', r'<span class="mori-money-fraction">\1</span>', escape(str(text)))


def money_metric(target, label, value, platform='combined', prefix='', empty='—'):
    formatted = money_text(value, platform) if value is not None else empty
    content = money_html(value, platform) if value is not None else escape(empty)
    target.markdown(f'<article class="mori-money-metric" data-money-label="{escape(label, quote=True)}" '
                    f'data-money-value="{escape(formatted, quote=True)}"><div class="mori-money-label">{escape(label)}</div>'
                    f'<div class="mori-money-value">{escape(prefix)}{content}</div></article>', unsafe_allow_html=True)


def money_note(target, text):
    target.markdown('<p class="mori-money-note">' + soften_decimals(text) + '</p>', unsafe_allow_html=True)


def money_table(target, df, platforms, money_columns):
    """Readable financial table; underlying numeric dataframe remains exportable."""
    headers = ''.join('<th scope="col">' + escape(str(c)) + '</th>' for c in df.columns)
    rows = []
    for index, (_, row) in enumerate(df.iterrows()):
        cells = []
        for column, value in row.items():
            if value is None or str(value) == 'nan':
                value_html = '—'
            elif column in money_columns and str(value) != '':
                try:
                    value_html = money_html(value, platforms[index])
                except (InvalidOperation, ValueError, TypeError):
                    value_html = soften_decimals(value)
            else:
                value_html = soften_decimals(value) if isinstance(value, str) else escape(str(value))
            cells.append('<td>' + value_html + '</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    target.markdown('<div class="mori-money-table" tabindex="0"><table><thead><tr>' + headers +
                    '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>', unsafe_allow_html=True)
