"""Google format adapters: normalize current copy without allocating asset costs."""
from decimal import Decimal
import re
from mori.core import AppError


def cost_from_micros(metrics):
    raw = str(metrics.get('costMicros', '0'))
    if not re.fullmatch(r'\d+', raw):
        raise AppError('Google 花費未回傳有效整數 micros，已停止加總。')
    return Decimal(raw) / Decimal(1_000_000)


def cost_totals(rows):
    totals = {}
    for row in rows:
        key = (str(row['campaign_id']), row['date'])
        totals[key] = totals.get(key, Decimal(0)) + Decimal(str(row.get('spend_raw', row['spend'])))
    return totals


def attribution_audit(campaign_rows, detail_rows, matched_rows):
    expected, detail, matched = map(cost_totals, (campaign_rows, detail_rows, matched_rows))
    names = {str(r['campaign_id']): r.get('campaign_name', '') for r in campaign_rows}
    relevant = {str(r['campaign_id']) for r in matched_rows}
    output = []
    for key in sorted(expected.keys() | detail.keys() | matched.keys()):
        if key[0] not in relevant:
            continue
        activity, all_detail, accepted = expected.get(key, Decimal(0)), detail.get(key, Decimal(0)), matched.get(key, Decimal(0))
        output.append({'日期': key[1], '廣告活動': names.get(key[0], ''), '廣告活動 ID': key[0],
                       '活動回報花費': str(activity), '全部明細花費': str(all_detail),
                       '條件認列花費': str(accepted), '條件未納入花費': str(all_detail - accepted),
                       '活動與明細差額': str(activity - all_detail)})
    return output


# API field paths and REST JSON paths. Unsupported formats keep their cost and ID,
# but never pretend that unavailable copy fields were read.
FORMATS = [
    ('responsive_search_ad', 'responsiveSearchAd', {
        'headlines': ('headlines',), 'descriptions': ('descriptions',), 'paths': ('path1', 'path2')}),
    ('responsive_display_ad', 'responsiveDisplayAd', {
        'headlines': ('headlines', 'long_headline'), 'descriptions': ('descriptions',)}),
    ('expanded_text_ad', 'expandedTextAd', {
        'headlines': ('headline_part1', 'headline_part2', 'headline_part3'),
        'descriptions': ('description', 'description2'), 'paths': ('path1', 'path2')}),
    ('expanded_dynamic_search_ad', 'expandedDynamicSearchAd', {'descriptions': ('description', 'description2')}),
    ('demand_gen_multi_asset_ad', 'demandGenMultiAssetAd', {
        'headlines': ('headlines',), 'descriptions': ('descriptions',)}),
    ('demand_gen_carousel_ad', 'demandGenCarouselAd', {
        'headlines': ('headline',), 'descriptions': ('description',)}),
    ('demand_gen_video_responsive_ad', 'demandGenVideoResponsiveAd', {
        'headlines': ('headlines', 'long_headlines'), 'descriptions': ('descriptions',),
        'paths': ('breadcrumb1', 'breadcrumb2')}),
    ('demand_gen_product_ad', 'demandGenProductAd', {
        'headlines': ('headline',), 'descriptions': ('description',), 'paths': ('breadcrumb1', 'breadcrumb2')}),
    ('app_ad', 'appAd', {'headlines': ('headlines',), 'descriptions': ('descriptions',)}),
    ('app_engagement_ad', 'appEngagementAd', {'headlines': ('headlines',), 'descriptions': ('descriptions',)}),
    ('app_pre_registration_ad', 'appPreRegistrationAd', {'headlines': ('headlines',), 'descriptions': ('descriptions',)}),
    ('smart_campaign_ad', 'smartCampaignAd', {'headlines': ('headlines',), 'descriptions': ('descriptions',)}),
    ('text_ad', 'textAd', {'headlines': ('headline',), 'descriptions': ('description1', 'description2')}),
    ('video_ad.in_feed', 'videoAd.inFeed', {'headlines': ('headline',), 'descriptions': ('description1', 'description2')}),
    ('video_ad.in_stream', 'videoAd.inStream', {'headlines': ('action_headline',)}),
    ('video_ad.bumper', 'videoAd.bumper', {'headlines': ('action_headline',)}),
    ('video_ad.non_skippable', 'videoAd.nonSkippable', {'headlines': ('action_headline',)}),
]


def camel(name):
    first, *parts = name.split('_')
    return first + ''.join(p.title() for p in parts)


def query_fields():
    return ['ad_group_ad.ad.' + fmt + '.' + field
            for fmt, _, mapping in FORMATS for fields in mapping.values() for field in fields]


def text_values(value):
    if isinstance(value, list):
        return [t for item in value for t in text_values(item)]
    if isinstance(value, dict):
        return text_values(value.get('text', ''))
    return [value] if isinstance(value, str) and value else []


def normalize(ad):
    output = {'headlines': [], 'descriptions': [], 'paths': [], 'available_fields': []}
    for _, json_path, mapping in FORMATS:
        obj = ad
        for part in json_path.split('.'):
            obj = obj.get(part, {}) if isinstance(obj, dict) else {}
        if not obj:
            continue
        for normalized, fields in mapping.items():
            output['available_fields'].append(normalized)
            output[normalized] += [text for field in fields for text in text_values(obj.get(camel(field)))]
    output['available_fields'] = sorted(set(output['available_fields']))
    for field in ('headlines', 'descriptions', 'paths'):
        output[field] = list(dict.fromkeys(output[field]))
    return output


def reconcile(campaign_rows, detail_rows, live_date=None):
    from mori.core import AppError
    expected, actual = cost_totals(campaign_rows), cost_totals(detail_rows)
    warnings = []
    for key in expected.keys() | actual.keys():
        delta = actual.get(key, 0) - expected.get(key, 0)
        if delta == 0:
            continue
        # Separate live requests cannot form an atomic snapshot. Only tolerate
        # differences for today when BOTH complete requests returned this key;
        # missing groups/campaigns and historical discrepancies remain errors.
        if live_date and key[1] == str(live_date) and key in expected and key in actual:
            warnings.append(f'今日活動與明細回報尚未同步：廣告活動 ID {key[0]}，活動 ${expected[key]:,.2f}、明細 ${actual[key]:,.2f}；目前按廣告／素材群組明細認列，後續更新可能回補。')
        else:
            raise AppError(f'Google 廣告／素材群組明細與廣告活動花費未對上：活動 ID {key[0]}，日期 {key[1]}，活動 ${expected.get(key, 0)}、明細 ${actual.get(key, 0)}，差額 ${delta}；已停止認列，請重新更新或核對平台報表。')
    return warnings
