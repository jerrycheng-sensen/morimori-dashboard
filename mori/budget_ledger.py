"""Append-only internal budget allocations; no platform spending mutations."""
from __future__ import annotations

import copy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import uuid

from mori.core import AppError, TAIPEI


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result != result.quantize(Decimal('.01')):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise AppError('金額必須是有效數字，最多兩位小數。') from None


def cost(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError()
        # Google cost is measured in micros; retain that precision without float noise.
        return result.quantize(Decimal('.000001'))
    except (InvalidOperation, ValueError, TypeError):
        raise AppError('花費資料格式不正確，無法檢核結餘。') from None


def impacts(entry):
    amount = money(entry['amount'])
    if entry['kind'] == 'transfer':
        return {entry['source_id']: -amount, entry['target_id']: amount}
    if entry['kind'] in ('reversal', 'transfer_correction'):
        return {key: money(value) for key, value in entry['effects'].items()}
    return {entry['target_id']: amount}


def balance(settings, plan_id, through=None):
    through = through or datetime.now(TAIPEI).date()
    plan = next(p for p in settings['projects'] if p['id'] == plan_id)
    original = money(plan['budget'])
    incoming = outgoing = adjustment = Decimal(0)
    for entry in settings.get('budget_transactions', []):
        if date.fromisoformat(entry['effective_on']) > through:
            continue
        delta = impacts(entry).get(plan_id, Decimal(0))
        if entry['kind'] == 'transfer_correction':
            # Present the corrected net transfer, not a fictitious return loan.
            change = money(entry['amount']) - money(entry['previous_amount'])
            if plan_id == entry['source_id']:
                outgoing += change
            elif plan_id == entry['target_id']:
                incoming += change
        elif entry['kind'] == 'adjustment':
            adjustment += delta
        elif delta > 0:
            incoming += delta
        else:
            outgoing -= delta
    return {'original': float(original), 'incoming': float(incoming), 'outgoing': float(outgoing),
            'adjustment': float(adjustment), 'adjusted': float(original + incoming - outgoing + adjustment)}


def plan_label(settings, plan_id):
    plan = next(p for p in settings['projects'] if p['id'] == plan_id)
    account = next(a for a in settings['accounts'] if a['key'] == plan['account_key'])
    group = next((g for g in settings.get('project_groups', []) if g['id'] == plan.get('group_id')), None)
    platform = 'Meta' if account['platform'] == 'meta' else 'Google Ads'
    return f"{group['name'] if group else plan['name']}｜{platform}｜{plan['name']}"


def checked_result(results, plan_id):
    result = results.get(plan_id)
    if not result or result.get('error') or result.get('not_started') or not result.get('currency'):
        raise AppError('請先成功讀取相關計畫的花費及幣別；讀取失敗不能建立預算異動。')
    return result


def base_entry(settings, effective_on, reason, operation_id=None, now=None):
    now = now or datetime.now(TAIPEI)
    effective = date.fromisoformat(str(effective_on))
    if effective > now.astimezone(TAIPEI).date():
        raise AppError('第一版不接受未來生效的異動，請填今天或實際發生日期。')
    if not reason.strip():
        raise AppError('請填寫異動原因／用途。')
    return {'id': operation_id or uuid.uuid4().hex, 'effective_on': str(effective),
            'created_at': now.isoformat(), 'reason': reason.strip()}


def append(settings, entry):
    from mori.core import validate_settings
    updated = copy.deepcopy(settings)
    if any(t['id'] == entry['id'] for t in updated.get('budget_transactions', [])):
        raise AppError('這筆異動已儲存，請勿重複送出。')
    updated.setdefault('budget_transactions', []).append(entry)
    return validate_settings(updated)


def transfer(settings, source_id, target_id, amount, effective_on, reason, results, operation_id=None, now=None):
    if source_id == target_id:
        raise AppError('來源與接收計畫不能相同。')
    amount = money(amount)
    if amount <= 0:
        raise AppError('轉移金額必須大於零。')
    source, target = checked_result(results, source_id), checked_result(results, target_id)
    if source['currency'] != target['currency']:
        raise AppError('來源與接收計畫幣別不同，不能直接轉移。')
    local_day = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()
    available = (money(balance(settings, source_id, local_day)['adjusted']) - cost(source['spend'])).quantize(Decimal('.01'), rounding=ROUND_FLOOR)
    if amount > available:
        raise AppError(f'轉移金額超過來源可用結餘（依本次花費資料：${available:,.2f}）。')
    entry = base_entry(settings, effective_on, reason, operation_id, now)
    entry.update({'kind': 'transfer', 'source_id': source_id, 'target_id': target_id,
                  'source_label': plan_label(settings, source_id), 'target_label': plan_label(settings, target_id),
                  'amount': float(amount), 'currency': source['currency'],
                  'source_spend': source['spend'], 'source_data_until': source.get('until'),
                  'target_data_until': target.get('until')})
    return append(settings, entry)


def transfer_amount(settings, entry_id):
    old = next((t for t in settings.get('budget_transactions', []) if t['id'] == entry_id), None)
    if not old or old['kind'] != 'transfer':
        raise AppError('請選擇原始預算轉移紀錄。')
    value = money(old['amount'])
    for entry in settings.get('budget_transactions', []):
        if entry.get('corrects') == entry_id:
            value = money(entry['amount'])
    return value


def correct_transfer(settings, entry_id, amount, reason, results, operation_id=None, now=None,
                     expected_amount=None):
    entries = settings.get('budget_transactions', [])
    old = next((t for t in entries if t['id'] == entry_id), None)
    if not old or old['kind'] != 'transfer' or any(t.get('reverses') == entry_id for t in entries):
        raise AppError('只能修正尚未沖回的原始預算轉移。')
    previous, amount = transfer_amount(settings, entry_id), money(amount)
    if expected_amount is not None and money(expected_amount) != previous:
        raise AppError('這筆轉移已被修正，請重新載入後再確認。')
    if amount < 0 or amount == previous:
        raise AppError('請填寫不同於目前金額、且不小於零的正確轉移金額。')
    source, target = checked_result(results, old['source_id']), checked_result(results, old['target_id'])
    if source['currency'] != old['currency'] or target['currency'] != old['currency']:
        raise AppError('目前幣別與原紀錄不同，已停止修正。')
    cost(source['spend']); cost(target['spend'])
    day = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()
    change = amount - previous
    entry = base_entry(settings, day, reason, operation_id, now)
    # This corrects an allocation error. Existing spend is factual and may exceed
    # the corrected allocation; never require fabricated funding to hide it.
    entry.update(kind='transfer_correction', corrects=entry_id, previous_amount=float(previous),
                 amount=float(amount), effects={old['source_id']:float(-change), old['target_id']:float(change)},
                 source_id=old['source_id'], target_id=old['target_id'],
                 source_label=plan_label(settings, old['source_id']), target_label=plan_label(settings, old['target_id']),
                 currency=old['currency'], source_spend=source['spend'], target_spend=target['spend'],
                 source_data_until=source.get('until'), target_data_until=target.get('until'))
    return append(settings, entry)


def adjustment(settings, plan_id, amount, effective_on, reason, results, operation_id=None, now=None):
    amount = money(amount)
    if not amount:
        raise AppError('追加／減列金額不能為零。')
    result = checked_result(results, plan_id)
    if money(balance(settings, plan_id)['adjusted']) + amount < cost(result['spend']):
        raise AppError('減列後的可用預算小於已發生花費，請先核對或調整減列金額。')
    entry = base_entry(settings, effective_on, reason, operation_id, now)
    entry.update({'kind': 'adjustment', 'target_id': plan_id, 'source_id': '', 'source_label': '預算追加／減列',
                  'target_label': plan_label(settings, plan_id), 'amount': float(amount),
                  'currency': result['currency'], 'source_data_until': result.get('until')})
    return append(settings, entry)


def reverse(settings, entry_id, reason, results, operation_id=None, now=None):
    entries = settings.get('budget_transactions', [])
    old = next((t for t in entries if t['id'] == entry_id), None)
    if not old or old['kind'] not in ('transfer', 'adjustment'):
        raise AppError('只能沖回原始轉移或追加／減列紀錄。')
    if any(t.get('corrects') == entry_id for t in entries):
        raise AppError('這筆轉移已有修正，請使用「修正轉移金額」；改為零可取消轉移。')
    if any(t.get('reverses') == entry_id for t in entries):
        raise AppError('此異動已沖回，不能再次沖回。')
    effects = {key: -value for key, value in impacts(old).items()}
    for key, delta in effects.items():
        result = checked_result(results, key)
        if result['currency'] != old['currency']:
            raise AppError('目前幣別與原紀錄不同，已停止沖回。')
        if money(balance(settings, key)['adjusted']) + delta < cost(result['spend']):
            raise AppError('沖回會使相關計畫預算小於已發生花費，請先核對結餘。')
    entry = base_entry(settings, (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date(), reason, operation_id, now)
    entry.update({'kind': 'reversal', 'reverses': entry_id, 'amount': old['amount'], 'currency': old['currency'],
                  'effects': {key: float(delta) for key, delta in effects.items()},
                  'source_id': old.get('target_id', ''), 'target_id': old.get('source_id', ''),
                  'source_label': old.get('target_label', ''), 'target_label': old.get('source_label', ''),
                  'original_source_label': old.get('source_label', ''), 'original_target_label': old.get('target_label', '')})
    return append(settings, entry)


def validate_ledger(settings):
    if not settings.get('budget_transactions'):
        return
    plans = {p['id']: p for p in settings['projects']}
    seen, reversed_ids, corrected_amounts = {}, set(), {}
    for entry in settings.get('budget_transactions', []):
        if not entry.get('id') or entry['id'] in seen:
            raise AppError('預算異動識別碼必須唯一。')
        if entry.get('kind') not in ('transfer', 'adjustment', 'reversal', 'transfer_correction') or not entry.get('currency') or not str(entry.get('reason', '')).strip():
            raise AppError('預算異動內容不完整。')
        date.fromisoformat(entry['effective_on'])
        datetime.fromisoformat(entry['created_at'])
        amount = money(entry['amount'])
        if (entry['kind'] == 'transfer_correction' and amount < 0) or (entry['kind'] != 'transfer_correction' and (not amount or (entry['kind'] != 'adjustment' and amount <= 0))):
            raise AppError('預算異動金額不正確。')
        if entry['kind'] == 'transfer' and (entry['source_id'] == entry['target_id'] or not entry.get('source_id')):
            raise AppError('預算轉移來源與接收計畫不正確。')
        if entry['kind'] == 'transfer_correction':
            old = seen.get(entry.get('corrects'))
            if not old or old['kind'] != 'transfer' or old['id'] in reversed_ids:
                raise AppError('修正必須對應尚未沖回的原始轉移紀錄。')
            previous = corrected_amounts.get(old['id'], money(old['amount']))
            change = amount - previous
            if (money(entry.get('previous_amount')) != previous or not change
                    or entry.get('source_id') != old['source_id'] or entry.get('target_id') != old['target_id']
                    or entry['currency'] != old['currency']
                    or impacts(entry) != {old['source_id']:-change, old['target_id']:change}
                    or entry['effective_on'] < old['effective_on']):
                raise AppError('轉移修正金額、方向或對應紀錄不正確。')
            corrected_amounts[old['id']] = amount
        if entry['kind'] == 'reversal':
            old = seen.get(entry.get('reverses'))
            if not old or old['kind'] not in ('transfer', 'adjustment') or old['id'] in reversed_ids or old['id'] in corrected_amounts:
                raise AppError('沖回紀錄必須對應尚未沖回的原始異動。')
            expected = {key: -value for key, value in impacts(old).items()}
            if impacts(entry) != expected or entry['currency'] != old['currency'] or amount != money(old['amount']):
                raise AppError('沖回金額必須完整抵銷原始異動。')
            reversed_ids.add(old['id'])
        for key in impacts(entry):
            if key not in plans:
                raise AppError('預算異動連結的計畫不存在，不能刪除有紀錄的計畫。')
        seen[entry['id']] = entry
    for key in plans:
        if balance(settings, key)['adjusted'] < 0:
            raise AppError('調整後預算不能小於零。')


def protect_history(before, after):
    from mori.invoices import protect_invoice_history
    protect_invoice_history(before, after)
    existing = before.get('budget_transactions', [])
    if after.get('budget_transactions', [])[:len(existing)] != existing:
        raise AppError('已儲存的預算異動不可覆寫或刪除，請使用修正轉移金額或沖回功能。')
    locked = {key for t in existing for key in impacts(t)}
    plans = {p['id']: p for p in after['projects']}
    for old in before['projects']:
        if old['id'] in locked:
            new = plans.get(old['id'])
            if not new or new.get('budget') != old.get('budget') or new.get('account_key') != old.get('account_key') or (new.get('group_id') or '') != (old.get('group_id') or ''):
                raise AppError('已有異動的計畫須保留原始預算及歸屬；請用追加／減列或沖回調整。')
