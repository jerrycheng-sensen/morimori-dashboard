"""Project-only navigation; filtering never changes spend windows or settings."""
from datetime import date

from mori.budgets import period_state

STATES = ('進行中', '準備中', '已結案')


def project_entries(settings, today):
    entries = []
    for group in settings.get('project_groups', []):
        entries.append({**group, 'nav_id': 'group:' + group['id'], 'group_id': group['id'],
                        'plan_id': None, 'phase': period_state(group['start'], group['end'], today)})
    group_ids = {g['id'] for g in settings.get('project_groups', [])}
    for plan in settings.get('projects', []):
        if plan.get('group_id') in group_ids:
            continue
        entries.append({**plan, 'nav_id': 'plan:' + plan['id'], 'group_id': None,
                        'plan_id': plan['id'], 'phase': period_state(plan['start'], plan['end'], today,
                                                                    plan.get('status') == '已結案')})
    order = {state: n for n, state in enumerate(STATES)}
    return sorted(entries, key=lambda e: (order[e['phase']], -date.fromisoformat(e['start']).toordinal(),
                                          e['name'], e['nav_id']))


def project_years(entries):
    return sorted({year for e in entries for year in range(date.fromisoformat(e['start']).year,
                                                         date.fromisoformat(e['end']).year + 1)}, reverse=True)


def filter_entries(entries, year, query='', state='全部'):
    query = query.strip().casefold()
    return [e for e in entries if (year is None or date.fromisoformat(e['start']).year <= year <= date.fromisoformat(e['end']).year)
            and (state == '全部' or e['phase'] == state) and (not query or query in e['name'].casefold())]
