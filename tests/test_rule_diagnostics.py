from datetime import datetime
from mori.core import TAIPEI, default_settings
from mori.runner import check_rules


def test_preview_explains_filter_threshold_date_and_disabled_rules():
    s = default_settings()
    s['accounts'] = [{'key':'m','name':'Meta','platform':'meta','account_id':'1','meta_action_type':'purchase'}]
    base = {'account_key':'m','enabled':True,'level':'ad','period_days':1,'minimum_spend':50,'cpa_threshold':50,'notify_zero':True}
    s['rules'] = [{**base,'id':'a','name':'未啟用','enabled':False},
                  {**base,'id':'b','name':'日期','starts_on':'2026-11-16'},
                  {**base,'id':'c','name':'篩選','ad_filter':'不存在'},
                  {**base,'id':'d','name':'花費','minimum_spend':100},
                  {**base,'id':'e','name':'CPA未超過','cpa_threshold':100},
                  {**base,'id':'f','name':'異常'}]
    class Provider:
        def fetch(self, account, start, end):
            return {'rows':[{'account_key':'m','currency':'TWD','ad_id':'1','ad_name':'永華店開幕','spend':60,'conversions':1,'impressions':1,'clicks':1}]}
    details = []
    found, errors = check_rules(s, {}, datetime(2026,11,16,9,tzinfo=TAIPEI), lambda *_:Provider(), diagnostics=details)
    assert not errors
    assert len(found) == 1 and found[0]['rule_name'] == '異常'
    assert [d['結果'] for d in details] == ['未啟用，未檢查','資料日期早於規則起日，略過','名稱或活動類型沒有符合','花費未超過門檻','未達 CPA／零轉換提醒條件','符合異常條件']
