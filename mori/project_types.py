"""Project-purpose taxonomy; no dependency on management/closure status."""
import re

PROJECT_TYPES = ('檔期', '新店開幕', '特殊專案')
BASELINE_NAMES = ('足球燒肉應援祭', '感謝祭第5彈')


def canonical_name(value):
    return re.sub(r'[\W_]+', '', str(value)).casefold()


def project_type(project):
    if project.get('category') in PROJECT_TYPES:
        return project['category']
    if canonical_name(project.get('name', '')) in {canonical_name(n) for n in BASELINE_NAMES}:
        return '檔期'  # These two baseline projects were explicitly confirmed.
    known = {'新北林口店開幕':'新店開幕','台南永華店開幕':'新店開幕','桃竹四家加碼案':'特殊專案'}
    return known.get(canonical_name(project.get('name','')), '待分類')


def baseline_groups(settings):
    groups = settings.get('project_groups', [])
    output = []
    for name in BASELINE_NAMES:
        found = [g for g in groups if canonical_name(g['name']) == canonical_name(name)]
        if len(found) != 1:
            from mori.core import AppError
            raise AppError('模型基礎專案尚未找到或名稱重複：' + name)
        if project_type(found[0]) != '檔期':
            from mori.core import AppError
            raise AppError('模型基礎專案須分類為檔期：' + name)
        output.append(found[0])
    return output
