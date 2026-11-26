"""Project/platform invoice evidence. No payment, wallet or ad mutations."""
from __future__ import annotations

import copy
import hashlib
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from cryptography.fernet import Fernet, InvalidToken

from mori.core import AppError, TAIPEI
from mori.budget_ledger import money

MAX_FILE = 5 * 1024 * 1024
CHUNK = 500_000


def invoice_quote(platform, ad_amount, tax_basis=None, rounding='whole'):
    """User-specified rates; estimate components without mutating project money."""
    if platform not in ('meta', 'google') or rounding not in ('whole', 'cents'):
        raise AppError('發票試算的平台或進位方式不正確。')
    if platform == 'google':
        tax_basis = 'ad'
    if tax_basis not in ('ad', 'ad_plus_service'):
        raise AppError('請先確認 Meta 稅額以廣告費或廣告費加服務費計算。')
    base = money(ad_amount)
    if base <= 0:
        raise AppError('本次廣告可用金額須大於零。')
    unit = Decimal('1') if rounding == 'whole' else Decimal('.01')
    rate = Decimal('.03') if platform == 'meta' else Decimal(0)
    service = (base * rate).quantize(unit, rounding=ROUND_HALF_UP)
    tax_base = base + service if tax_basis == 'ad_plus_service' else base
    tax = (tax_base * Decimal('.05')).quantize(unit, rounding=ROUND_HALF_UP)
    return {'version': 1, 'ad_amount': str(base), 'service_rate': str(rate),
            'service_amount': str(service), 'tax_rate': '0.05', 'tax_basis': tax_basis,
            'tax_amount': str(tax), 'total': str(base + service + tax), 'rounding': rounding}


def validate_quote(row):
    quote = row.get('charge_quote')
    if quote is None:
        return  # Preserve legacy invoices without guessing historical fees.
    if not isinstance(quote, dict):
        raise AppError('發票費稅試算資料格式不正確。')
    expected = invoice_quote(row['platform'], row['allocated_amount'], quote.get('tax_basis'), quote.get('rounding'))
    if quote != expected or money(row.get('invoice_difference')) != money(row['face_amount']) - money(expected['total']):
        raise AppError('發票費稅試算與本專案認列金額不一致，請重新計算。')
    if money(row['invoice_difference']) != 0 and not str(row.get('note', '')).strip():
        raise AppError('實際發票金額與試算總額不同，請在備註說明差異原因。')


def checked_file(name, content):
    name = str(name).replace('\\', '/').split('/')[-1]
    if not name or len(name) > 180 or any(ord(c) < 32 for c in name):
        raise AppError('發票檔名不正確。')
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_FILE:
        raise AppError('請上傳非空白的發票，每個檔案最多 5 MB。')
    suffix = name.rsplit('.', 1)[-1].lower()
    signatures = {'pdf': (b'%PDF-', 'application/pdf'), 'png': (b'\x89PNG\r\n\x1a\n', 'image/png'),
                  'jpg': (b'\xff\xd8\xff', 'image/jpeg'), 'jpeg': (b'\xff\xd8\xff', 'image/jpeg')}
    if suffix not in signatures or not content.startswith(signatures[suffix][0]):
        raise AppError('僅接受內容與副檔名相符的 PDF、PNG、JPG 發票。')
    return {'name': name, 'mime': signatures[suffix][1], 'size': len(content),
            'sha256': hashlib.sha256(content).hexdigest()}


class InvoiceDocuments:
    """Encrypted chunks in the existing private state repo, never public URLs."""
    def __init__(self, store, key):
        self.store = store
        try:
            self.cipher = Fernet(str(key).encode())
        except (ValueError, TypeError):
            raise AppError('發票加密需要部署設定 CREDENTIALS_KEY，請到 API 與權杖設定檢查。') from None

    def save(self, name, content):
        file = checked_file(name, content)
        encrypted = self.cipher.encrypt(content).decode('ascii')
        doc_id = uuid.uuid4().hex
        chunks = [encrypted[i:i+CHUNK] for i in range(0, len(encrypted), CHUNK)]
        for i, value in enumerate(chunks):
            self.store.write(f'invoice-documents/{doc_id}/{i}.json', {'version': 1, 'ciphertext': value}, None,
                             message='保存加密發票附件 [skip ci]')
        # Only return a reference after every chunk has been persisted.
        return {**file, 'document_id': doc_id, 'parts': len(chunks)}

    def load(self, file):
        validate_reference(file)
        encrypted = []
        for i in range(file['parts']):
            chunk, _ = self.store.read(f"invoice-documents/{file['document_id']}/{i}.json", {})
            if chunk.get('version') != 1 or not isinstance(chunk.get('ciphertext'), str):
                raise AppError('發票附件不完整，未提供下載；請檢查私人資料備份。')
            encrypted.append(chunk['ciphertext'])
        try:
            content = self.cipher.decrypt(''.join(encrypted).encode('ascii'))
        except (InvalidToken, UnicodeError):
            raise AppError('發票附件解密失敗，請確認原本的加密金鑰。') from None
        if len(content) != file['size'] or hashlib.sha256(content).hexdigest() != file['sha256']:
            raise AppError('發票附件完整性核對失敗，未提供下載。')
        checked_file(file['name'], content)
        return content


def validate_reference(file):
    if not isinstance(file, dict):
        raise AppError('發票附件索引不正確。')
    name = file.get('name', '')
    types = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}
    if (not isinstance(name, str) or not name or len(name) > 180 or '/' in name or '\\' in name
            or any(ord(c) < 32 for c in name) or types.get(name.rsplit('.', 1)[-1].lower()) != file.get('mime')):
        raise AppError('發票附件檔名或格式不正確。')
    if (not isinstance(file, dict) or not re.fullmatch(r'[0-9a-f]{32}', str(file.get('document_id', '')))
            or type(file.get('parts')) is not int or not 1 <= file['parts'] <= 16
            or type(file.get('size')) is not int or not 0 < file['size'] <= MAX_FILE
            or not re.fullmatch(r'[0-9a-f]{64}', str(file.get('sha256', '')))
            or not isinstance(file.get('name'), str) or not file['name']
            or file.get('mime') not in ('application/pdf', 'image/png', 'image/jpeg')):
        raise AppError('發票附件參照格式不正確。')


def active_records(settings, plan_id=None):
    voided = {v['invoice_id'] for v in settings.get('invoice_voids', [])}
    return [r for r in settings.get('project_invoices', []) if r['id'] not in voided
            and (plan_id is None or r['plan_id'] == plan_id)]


def invoice_summary(settings, plan_id):
    records = active_records(settings, plan_id)
    totals = {}
    for row in records:
        totals[row['currency']] = totals.get(row['currency'], Decimal(0)) + money(row['allocated_amount'])
    return {'status': '已儲值' if records else '未儲值', 'count': len(records), 'totals': totals}


def validate_invoices(settings):
    plans = {p['id']: p for p in settings.get('projects', [])}
    accounts = {a['key']: a for a in settings.get('accounts', [])}
    seen = {}
    for row in settings.get('project_invoices', []):
        if not re.fullmatch(r'[0-9a-f]{32}', str(row.get('id', ''))) or row['id'] in seen:
            raise AppError('發票紀錄編號不正確或重複。')
        plan = plans.get(row.get('plan_id'))
        if not plan:
            raise AppError('已有發票紀錄的平台計畫不可刪除。')
        account = accounts[plan['account_key']]
        if (row.get('account_id') != str(account['account_id']).removeprefix('act_').replace('-', '')
                or row.get('platform') != account['platform'] or row.get('group_id') != plan.get('group_id', '')):
            raise AppError('已有發票紀錄的計畫不可改換專案或廣告帳號。')
        validate_reference(row.get('file'))
        if not re.fullmatch(r'[A-Z]{3}', str(row.get('currency', ''))):
            raise AppError('請使用三碼幣別，例如 TWD。')
        face, allocated = money(row.get('face_amount')), money(row.get('allocated_amount'))
        if face <= 0 or allocated <= 0 or allocated > face:
            raise AppError('發票金額及本專案認列金額須大於零；認列不可超過發票金額。')
        if not str(row.get('invoice_number', '')).strip():
            raise AppError('請填發票號碼／憑證編號。')
        if 'supplier_order_number' in row:
            validate_order_reference(row.get('supplier'), row['supplier_order_number'])
        validate_quote(row)
        date.fromisoformat(row['issued_on'])
        date.fromisoformat(row['registered_on'])
        datetime.fromisoformat(row['created_at'])
        seen[row['id']] = row
    voids = set()
    for entry in settings.get('invoice_voids', []):
        if entry.get('invoice_id') not in seen or entry['invoice_id'] in voids or not str(entry.get('reason', '')).strip():
            raise AppError('作廢須對應一筆尚未作廢的發票，並填寫原因。')
        datetime.fromisoformat(entry['created_at'])
        voids.add(entry['invoice_id'])
    for entry in settings.get('invoice_order_links', []):
        if entry.get('invoice_id') not in seen:
            raise AppError('訂單編號須對應已儲存的發票。')
        validate_order_reference(entry.get('supplier'), entry.get('order_number'))
        datetime.fromisoformat(entry['created_at'])
    active = active_records(settings)
    # A shared invoice can be allocated across projects but never over its face value.
    for row in active:
        same = [r for r in active if r['platform'] == row['platform'] and r['account_id'] == row['account_id']
                and (r['invoice_number'].strip().casefold() == row['invoice_number'].strip().casefold()
                     or r['file']['sha256'] == row['file']['sha256'])]
        if any(r['file']['sha256'] == row['file']['sha256'] and r['invoice_number'].strip().casefold() != row['invoice_number'].strip().casefold() for r in same):
            raise AppError('同一份發票附件須使用相同的發票號碼／憑證編號。')
        if any(r['currency'] != row['currency'] or money(r['face_amount']) != money(row['face_amount']) for r in same):
            raise AppError('同一張發票的幣別及票面金額必須一致。')
        if len({r['plan_id'] for r in same}) != len(same):
            raise AppError('同一平台計畫已登錄這張發票，請勿重複認列；更正請先作廢舊紀錄。')
        if sum((money(r['allocated_amount']) for r in same), Decimal(0)) > money(row['face_amount']):
            raise AppError('此發票跨專案的認列合計已超過票面金額。')


def register_invoice(settings, plan_id, number, issued_on, registered_on, currency, face_amount,
                     allocated_amount, note, file, record_id=None, now=None, charge_quote=None, supplier_order_number=None):
    now = now or datetime.now(TAIPEI)
    today = now.astimezone(TAIPEI).date()
    if max(date.fromisoformat(str(issued_on)), date.fromisoformat(str(registered_on))) > today:
        raise AppError('發票日期及儲值登錄日期不可晚於今天。')
    plan = next((p for p in settings['projects'] if p['id'] == plan_id), None)
    if not plan:
        raise AppError('請先儲存平台計畫，再登錄發票。')
    account = next(a for a in settings['accounts'] if a['key'] == plan['account_key'])
    updated = copy.deepcopy(settings)
    updated.setdefault('project_invoices', []).append({
        'id': record_id or uuid.uuid4().hex, 'plan_id': plan_id, 'group_id': plan.get('group_id', ''),
        'account_id': str(account['account_id']).removeprefix('act_').replace('-', ''), 'platform': account['platform'],
        'invoice_number': str(number).strip(), 'issued_on': str(issued_on), 'registered_on': str(registered_on),
        'currency': str(currency).strip().upper(), 'face_amount': str(money(face_amount)),
        'allocated_amount': str(money(allocated_amount)), 'note': str(note).strip(),
        'file': copy.deepcopy(file), 'created_at': now.isoformat()})
    if supplier_order_number is not None:
        validate_order_reference('精立數位', supplier_order_number)
        updated['project_invoices'][-1].update(supplier='精立數位', supplier_order_number=supplier_order_number.strip())
    if charge_quote is not None:
        if not isinstance(charge_quote, dict):
            raise AppError('發票費稅試算資料格式不正確。')
        expected = invoice_quote(account['platform'], allocated_amount, charge_quote.get('tax_basis'), charge_quote.get('rounding'))
        if charge_quote != expected:
            raise AppError('發票費稅試算與本專案認列金額不一致，請重新計算。')
        updated['project_invoices'][-1].update(charge_quote=copy.deepcopy(charge_quote),
            invoice_difference=str(money(face_amount) - money(charge_quote['total'])))
    validate_invoices(updated)
    return updated


def validate_order_reference(supplier, order_number):
    if supplier != '精立數位' or not isinstance(order_number, str) or not order_number.strip():
        raise AppError('請填寫精立數位訂單編號。')
    if len(order_number) > 100 or any(ord(c) < 32 for c in order_number):
        raise AppError('訂單編號限 100 字，不可包含換行或控制字元。')


def invoice_order_reference(settings, row):
    """Latest reference; original invoice amounts and evidence remain immutable."""
    reference = {'supplier': row.get('supplier', '精立數位'),
                 'order_number': row.get('supplier_order_number', '')}
    for entry in settings.get('invoice_order_links', []):
        if entry['invoice_id'] == row['id']:
            reference = {'supplier': entry['supplier'], 'order_number': entry['order_number']}
    return reference


def link_invoice_order(settings, invoice_id, order_number, now=None):
    validate_order_reference('精立數位', order_number)
    row = next((r for r in active_records(settings) if r['id'] == invoice_id), None)
    if row is None:
        raise AppError('只能補填或更正有效發票的訂單編號。')
    if invoice_order_reference(settings, row)['order_number'] == order_number.strip():
        raise AppError('訂單編號沒有變更。')
    updated = copy.deepcopy(settings)
    updated.setdefault('invoice_order_links', []).append({
        'invoice_id': invoice_id, 'supplier': '精立數位', 'order_number': order_number.strip(),
        'created_at': (now or datetime.now(TAIPEI)).isoformat()})
    validate_invoices(updated)
    return updated


def void_invoice(settings, invoice_id, reason, now=None):
    updated = copy.deepcopy(settings)
    updated.setdefault('invoice_voids', []).append({'invoice_id': invoice_id, 'reason': reason.strip(),
                                                   'created_at': (now or datetime.now(TAIPEI)).isoformat()})
    validate_invoices(updated)
    return updated


def protect_invoice_history(before, after):
    for key in ('project_invoices', 'invoice_voids', 'invoice_order_links'):
        previous = before.get(key, [])
        if after.get(key, [])[:len(previous)] != previous:
            raise AppError('已儲存的發票紀錄不可覆寫或刪除；更正請先作廢，再重新登錄。')


class DemoInvoiceStore:
    """Only used by explicitly labelled DEMO_MODE; no external writes."""
    def __init__(self):
        self.files = {}

    def write(self, path, data, sha, **kwargs):
        self.files[path] = copy.deepcopy(data)
        return 'demo'

    def read(self, path, default=None):
        return copy.deepcopy(self.files.get(path, default)), None
