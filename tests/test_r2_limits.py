from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from dataclasses import replace
import pytest
from app.config import Config
from app.storage import R2Storage
from app.r2_budget import OperationBudget, R2BudgetExceeded


def provider(tmp_path, limit=8_000_000_000):
    config=Config(root=tmp_path, dry_run=False, r2_account_id='account',r2_access_key_id='key',
                  r2_secret_access_key='secret',r2_bucket='bucket',r2_public_base_url='https://media.example.org',
                  r2_max_storage_bytes=limit)
    client=Mock()
    client.list_objects_v2.return_value={'Contents':[], 'IsTruncated':False}
    client.list_multipart_uploads.return_value={'Uploads':[], 'IsTruncated':False}
    return R2Storage(config,client,Mock()),client


def test_checks_all_objects_and_pages_before_upload(tmp_path):
    storage,client=provider(tmp_path,limit=100)
    client.list_objects_v2.side_effect=[
        {'Contents':[{'Key':'unrelated/file','Size':60}], 'IsTruncated':True,'NextContinuationToken':'next'},
        {'Contents':[{'Key':'clips/old.mp4','Size':30}], 'IsTruncated':False}]
    with pytest.raises(R2BudgetExceeded,match='Limite preventivo'):
        storage.check_space(11)
    client.put_object.assert_not_called()
    assert client.list_objects_v2.call_args.kwargs['ContinuationToken']=='next'


def test_exact_storage_limit_permitted(tmp_path):
    storage,client=provider(tmp_path,limit=100)
    client.list_objects_v2.return_value={'Contents':[{'Size':90}], 'IsTruncated':False}
    assert storage.check_space(10)==90


def test_partial_inventory_fails_closed(tmp_path):
    storage,client=provider(tmp_path)
    client.list_objects_v2.return_value={'Contents':[], 'IsTruncated':True}
    with pytest.raises(R2BudgetExceeded,match='incompleta'):storage.check_space(1)
    client.put_object.assert_not_called()


def test_nonstandard_objects_block_uploads(tmp_path):
    storage,client=provider(tmp_path)
    client.list_objects_v2.return_value={'Contents':[{'Size':1,'StorageClass':'STANDARD_IA'}]}
    with pytest.raises(R2BudgetExceeded,match='Standard'):storage.check_space(1)


def test_unfinished_multipart_blocks_upload(tmp_path):
    storage,client=provider(tmp_path)
    client.list_multipart_uploads.return_value={'Uploads':[{'Key':'old','UploadId':'u'}]}
    with pytest.raises(R2BudgetExceeded,match='multipart'):storage.check_space(1)
    client.put_object.assert_not_called()


def test_operations_persist_and_block_before_request(tmp_path):
    ledger=tmp_path/'usage.db'
    for i in range(2):OperationBudget(ledger,class_a=2).reserve('A')
    with pytest.raises(R2BudgetExceeded):OperationBudget(ledger,class_a=2).reserve('A')
    # Independent B budget is still available.
    OperationBudget(ledger,class_a=2).reserve('B')


def test_dry_budget_changes_no_files(tmp_path):
    ledger=tmp_path/'data'/'usage.db'
    budget=OperationBudget(ledger,class_a=1,dry_run=True)
    budget.reserve('A')
    with pytest.raises(R2BudgetExceeded):budget.reserve('A')
    assert not ledger.parent.exists()


def test_dry_budget_respects_existing_ledger_without_writing(tmp_path):
    ledger=tmp_path/'usage.db'
    OperationBudget(ledger,class_a=1).reserve('A')
    before=ledger.read_bytes()
    with pytest.raises(R2BudgetExceeded):OperationBudget(ledger,class_a=1,dry_run=True).reserve('A')
    assert ledger.read_bytes()==before


def test_rolling_window_does_not_reset_at_calendar_month(tmp_path):
    ledger=tmp_path/'usage.db'
    moment=datetime(2026,10,31,23,50,tzinfo=timezone.utc)
    OperationBudget(ledger,class_a=1,clock=lambda:moment).reserve('A')
    with pytest.raises(R2BudgetExceeded):
        OperationBudget(ledger,class_a=1,clock=lambda:moment+timedelta(days=1)).reserve('A')
    OperationBudget(ledger,class_a=1,clock=lambda:moment+timedelta(days=34)).reserve('A')


def test_delete_still_allowed_when_operations_exhausted(tmp_path):
    storage,client=provider(tmp_path)
    storage.budget=OperationBudget(tmp_path/'ops.db',class_a=1,class_b=1)
    storage.budget.reserve('A');storage.budget.reserve('B')
    storage.delete('clips/sent.mp4')
    client.delete_object.assert_called_once()
    with pytest.raises(R2BudgetExceeded):storage.exists('clips/sent.mp4')
    client.head_object.assert_not_called()


def test_storage_cap_cannot_be_raised_past_safety_ceiling(tmp_path,monkeypatch):
    monkeypatch.setenv('R2_MAX_STORAGE_BYTES','10000000000')
    with pytest.raises(ValueError,match='limites preventivos'):Config.load(tmp_path)
