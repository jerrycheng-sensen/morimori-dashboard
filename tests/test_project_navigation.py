from datetime import date

from mori.project_navigation import project_entries, project_years, filter_entries


def test_navigation_uses_project_period_not_closed_ad_state_and_keeps_stable_ids():
    settings = {'project_groups': [
        {'id': 'festival', 'name': '感謝祭第5彈', 'start': '2026-10-01', 'end': '2026-11-30', 'status': '已結案'},
        {'id': 'cross', 'name': '跨年案', 'start': '2026-12-01', 'end': '2027-01-31'}],
        'projects': [{'id': 'meta', 'name': '重複平台名稱', 'group_id': 'festival', 'start': '2026-09-29', 'end': '2026-11-18', 'status': '已結案'},
                     {'id': 'legacy', 'name': '舊平台案', 'start': '2025-01-01', 'end': '2025-01-31', 'status': '已結案'}]}
    rows = project_entries(settings, date(2026, 11, 20))
    assert len(rows) == 3  # Platform children don't become separate projects.
    assert rows[0]['nav_id'] == 'group:festival' and rows[0]['phase'] == '進行中'
    assert project_years(rows) == [2027, 2026, 2025]
    assert [r['name'] for r in filter_entries(rows, 2026, ' 感謝祭 ', '進行中')] == ['感謝祭第5彈']
    assert filter_entries(rows, 2026, '不存在') == []
    assert filter_entries(rows, 2027)[0]['nav_id'] == 'group:cross'
    assert filter_entries(rows, 2025)[0]['nav_id'] == 'plan:legacy'
    # Cross-year lookup must not modify the full project or advertising dates.
    assert filter_entries(rows, 2027)[0]['start'] == '2026-12-01'
