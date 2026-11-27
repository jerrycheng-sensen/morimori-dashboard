"""Shared presentation components. Values are escaped; no accounting or API work."""
from html import escape
from pathlib import Path
from mori.money_display import money_html

ICONS = {
    'chart':'<path d="M4 18V6m0 12h16M8 14l4-5 4 3 4-7"/>',
    'budget':'<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 9h18m-6 4h6m-5 3h1"/>',
    'rules':'<path d="M5 4v16M12 4v16M19 4v16"/><path d="M2 8h6m1 8h6m1-6h6"/>',
    'clock':'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'account':'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/><path d="M10 6h7v8M6 10v7h8"/>',
    'key':'<circle cx="8" cy="9" r="5"/><path d="m12 13 8 8m-4-4 3-3m-6 0 3-3"/>',
}


def stylesheet():
    return '<style>'+ (Path(__file__).resolve().parents[1]/'assets/dashboard.css').read_text()+'</style>'


def icon_svg(name='chart'):
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+ICONS.get(name,ICONS['chart'])+'</svg>'


def page_header(title, description, eyebrow='MORI / 廣告智慧儀表板', icon='chart'):
    return ('<header class="mori-page-header"><div><div class="mori-page-eyebrow">'+escape(eyebrow)+'</div><h1>'+escape(title)+
            '</h1><p>'+escape(description)+'</p></div><div class="mori-page-mark">'+icon_svg(icon)+'</div></header>')


def section_heading(title, description='', index=''):
    return '<div class="mori-section-heading"><div><h2>'+escape(title)+'</h2>'+(('<p>'+escape(description)+'</p>') if description else '')+'</div><span>'+escape(index)+'</span></div>'


def insight_card(label, value, note, *, focus=False, empty='尚未辨識', tag='模型估計',platform='combined'):
    number=money_html(value,platform) if value is not None else '<span class="mori-insight-empty">'+escape(empty)+'</span>'
    return ('<article class="mori-insight'+(' focus' if focus else '')+'" data-money-label="'+escape(label,quote=True)+'"><div class="mori-insight-head">'+escape(label)+
            '<span class="mori-insight-tag">'+escape(tag)+'</span></div><div class="mori-insight-value">'+number+'</div><p class="mori-insight-note">'+escape(note)+'</p></article>')


def history_card(project, index):
    from decimal import Decimal
    spend=Decimal(project['spend']);bookings=Decimal(project['bookings'])
    valid=project.get('bookings_valid',True)
    count=f'{bookings:,.2f}'.rstrip('0').rstrip('.') if valid else '事件待核對'
    platform=project.get('analysis_platform','combined')
    stats=[('實際花費',money_html(spend,platform)),('平台回報訂位',escape(count)),('整檔 CPA',money_html(spend/bookings if valid and bookings else None,platform))]
    return ('<article class="mori-history-card"><div class="mori-history-top"><div><h3>'+escape(project['name'])+'</h3><p>'+escape(project['ad_start']+' — '+project['ad_end'])+
            '</p></div><span class="mori-history-index">'+escape(index)+'</span></div><div class="mori-history-stats">'+
            ''.join('<div><span>'+escape(label)+'</span><strong>'+value+'</strong></div>' for label,value in stats)+'</div></article>')


def empty_state(title, description):
    return '<div class="mori-empty-state"><div class="mori-page-mark">'+icon_svg()+'</div><strong>'+escape(title)+'</strong><p>'+escape(description)+'</p></div>'
