import copy
import hashlib
from datetime import datetime

import pytest
from cryptography.fernet import Fernet

from mori.core import AppError, TAIPEI, default_settings, validate_settings
from mori.invoices import (InvoiceDocuments, DemoInvoiceStore, checked_file, register_invoice,
                           void_invoice, invoice_summary, protect_invoice_history)

NOW = datetime(2026, 11, 22, 9, tzinfo=TAIPEI)
PDF = b'%PDF-1.7\ninvoice fixture\n%%EOF'


def sample():
    s = default_settings()
    s['accounts'] = [{'key':'m','platform':'meta','account_id':'123','name':'Meta'},
                     {'key':'g','platform':'google','account_id':'456','name':'Google'}]
    s['project_groups'] = [{'id': 'project', 'name': '感謝祭', 'start': '2026-10-01', 'end': '2026-11-30', 'status': '進行中'}]
    base = {'group_id': 'project', 'name': '平台', 'budget': 100, 'keyword': '感謝祭',
            'start': '2026-09-29', 'end': '2026-11-18', 'status': '已結案'}
    s['projects'] = [{**base, 'id':'meta', 'account_key':'m'}, {**base, 'id':'google', 'account_key':'g'},
                     {**base, 'id':'meta2', 'account_key':'m', 'group_id':''}]
    return s


def reference():
    return {**checked_file('invoice.pdf', PDF), 'document_id':'a'*32, 'parts':1}


def add(s, plan='meta', amount='60', number='AB12345678', file=None):
    return register_invoice(s, plan, number, '2026-11-01', '2026-11-02', 'TWD', '100', amount,
                            '含稅票面；依預算口徑認列', file or reference(), now=NOW)


def test_invoice_status_is_per_plan_platform_and_does_not_mutate_budgets():
    original = sample()
    s = validate_settings(add(original))
    assert invoice_summary(s,'meta')['status'] == '已儲值'
    assert invoice_summary(s,'meta')['totals']['TWD'] == 60
    assert invoice_summary(s,'google')['status'] == '未儲值'
    assert original == sample() and s['projects'] == original['projects']
    assert not s.get('budget_transactions')
    # A partial invoice is registered, without pretending the whole budget is funded.
    assert invoice_summary(s,'meta')['totals']['TWD'] < s['projects'][0]['budget']


def test_invoice_duplicate_and_split_allocation_constraints():
    s = add(sample())
    with pytest.raises(AppError, match='重複'):
        add(s)
    split = add(s, 'meta2', '40')
    assert invoice_summary(split,'meta2')['totals']['TWD'] == 40
    with pytest.raises(AppError, match='合計'):
        add(s, 'meta2', '41')
    with pytest.raises(AppError, match='相同的發票號碼'):
        add(s, 'meta2', '20', number='wrong-number')


def test_invoice_void_is_append_only_and_last_void_restores_unfunded_state():
    s = add(sample())
    with pytest.raises(AppError):
        void_invoice(s, s['project_invoices'][0]['id'], '')
    canceled = void_invoice(s, s['project_invoices'][0]['id'], '認列金額誤填', now=NOW)
    protect_invoice_history(s, canceled)
    assert invoice_summary(canceled, 'meta')['status'] == '未儲值'
    assert canceled['project_invoices'] == s['project_invoices']
    with pytest.raises(AppError):
        void_invoice(canceled, s['project_invoices'][0]['id'], '再作廢', now=NOW)
    edited = copy.deepcopy(s)
    edited['project_invoices'][0]['allocated_amount'] = '99'
    with pytest.raises(AppError, match='不可覆寫'):
        protect_invoice_history(s, edited)
    assert invoice_summary(add(canceled), 'meta')['status'] == '已儲值'


@pytest.mark.parametrize('amount', ['0','-1','101','NaN','1.001'])
def test_invalid_invoice_money_is_not_saved(amount):
    with pytest.raises(AppError):
        add(sample(), amount=amount)


def test_invoice_reference_and_account_binding_validation():
    with pytest.raises(AppError):
        register_invoice(sample(),'meta','n','2026-11-01','2026-11-01','TWD',100,50,'',{},now=NOW)
    s = add(sample())
    s['accounts'][0]['account_id'] = '999'
    with pytest.raises(AppError, match='不可改換'):
        validate_settings(s)
    s = add(sample())
    s['projects'][0]['group_id'] = ''
    with pytest.raises(AppError, match='不可改換'):
        validate_settings(s)


def test_document_encryption_chunking_roundtrip_and_integrity():
    store = DemoInvoiceStore()
    key = Fernet.generate_key().decode()
    documents = InvoiceDocuments(store, key)
    payload = b'%PDF-1.7\n' + b'confidential-invoice-' * 50000
    file = documents.save('invoice.pdf', payload)
    assert file['parts'] > 1
    assert all('confidential-invoice' not in str(value) for value in store.files.values())
    assert documents.load(file) == payload
    with pytest.raises(AppError, match='解密失敗'):
        InvoiceDocuments(store, Fernet.generate_key().decode()).load(file)
    forged = {**file, 'sha256': hashlib.sha256(b'other').hexdigest()}
    with pytest.raises(AppError, match='完整性'):
        documents.load(forged)
    store.files.pop(next(iter(store.files)))
    with pytest.raises(AppError, match='不完整'):
        documents.load(file)


def test_upload_failure_does_not_return_completed_attachment():
    class Failing(DemoInvoiceStore):
        def write(self, path, *args, **kwargs):
            if len(self.files) == 1:
                raise AppError('儲存失敗')
            return super().write(path, *args, **kwargs)
    documents = InvoiceDocuments(Failing(), Fernet.generate_key().decode())
    with pytest.raises(AppError, match='儲存失敗'):
        documents.save('invoice.pdf', b'%PDF-' + b'x'*800000)


@pytest.mark.parametrize('name,payload', [('invoice.pdf',b'not a PDF'),('invoice.html',PDF),('invoice.pdf',b''),
                                         ('invoice.pdf', b'%PDF-' + b'x'*(5*1024*1024))])
def test_reject_bad_file_type_empty_or_oversized(name, payload):
    with pytest.raises(AppError):
        checked_file(name,payload)
