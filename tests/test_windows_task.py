from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest
from app.windows_task import (
    NAMESPACE, NS, TASK_NAME, TaskError, build_task_xml, owns_task, parse_task_xml,
    register_task, verify_task,
)

SID = 'S-1-5-21-1-2-3-1001'


def project(tmp_path):
    root = tmp_path / 'Proyecto con espacios & ñ'
    (root / '.venv' / 'Scripts').mkdir(parents=True)
    (root / '.venv' / 'Scripts' / 'pythonw.exe').touch()
    (root / 'main.py').touch()
    return root


def response(code=0, stdout=b'', stderr=b''):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def native_runner(root, existing=None):
    calls = []
    state = {'xml': existing}
    def run(args, **kwargs):
        calls.append(args)
        if '/Create' in args:
            state['xml'] = Path(args[args.index('/XML') + 1]).read_bytes()
            return response()
        if '/XML' in args:
            return response(stdout=state['xml'])
        listing = f'"\\{TASK_NAME}","N/A","Ready"\r\n' if existing else ''
        return response(stdout=listing.encode())
    return run, calls, state


def test_xml_has_daily_logon_catchup_and_interactive_pythonw(tmp_path):
    root = project(tmp_path)
    document = parse_task_xml(build_task_xml(root, SID, datetime(2026, 10, 9)))
    verify_task(document, root, SID)
    assert document.findtext('t:Triggers/t:CalendarTrigger/t:StartBoundary', namespaces=NS) == '2026-10-09T03:15:00'
    assert document.findtext('t:Triggers/t:LogonTrigger/t:Delay', namespaces=NS) == 'PT1M'
    assert document.findtext('t:Actions/t:Exec/t:Command', namespaces=NS).endswith('pythonw.exe')
    assert document.findtext('t:Actions/t:Exec/t:Arguments', namespaces=NS) == f'"{root / "main.py"}" maintain'
    assert document.findtext('t:Actions/t:Exec/t:WorkingDirectory', namespaces=NS) == str(root)
    assert document.findtext('t:Settings/t:ExecutionTimeLimit', namespaces=NS) == 'PT1H'


def test_new_registration_verifies_readback_without_powershell(tmp_path):
    root = project(tmp_path)
    runner, calls, state = native_runner(root)
    messages = []
    register_task(root, SID, 'schtasks.exe', runner, messages.append)
    create = next(args for args in calls if '/Create' in args)
    assert '/F' not in create
    assert not Path(create[create.index('/XML') + 1]).exists()  # temporary XML removed
    assert all('powershell' not in str(arg).lower() for args in calls for arg in args)
    assert all(arg not in ('/RP', '/RU') for args in calls for arg in args)
    assert any('instalada y verificada' in message for message in messages)


def test_repeat_install_updates_only_own_task(tmp_path):
    root = project(tmp_path)
    runner, calls, state = native_runner(root, build_task_xml(root, SID))
    register_task(root, SID, 'schtasks.exe', runner, lambda message: None)
    assert '/F' in next(args for args in calls if '/Create' in args)


@pytest.mark.parametrize('field, replacement', [
    ('t:Actions/t:Exec/t:Command', 'C:\\other\\pythonw.exe'),
    ('t:Actions/t:Exec/t:Arguments', 'another-script.py'),
    ('t:Actions/t:Exec/t:WorkingDirectory', 'C:\\other'),
    ('t:Principals/t:Principal/t:UserId', 'S-1-5-21-9-9-9-1002'),
])
def test_unrelated_existing_task_not_overwritten(tmp_path, field, replacement):
    root = project(tmp_path)
    document = parse_task_xml(build_task_xml(root, SID))
    document.find(field, NS).text = replacement
    runner, calls, state = native_runner(root, ET.tostring(document, encoding='utf-16'))
    with pytest.raises(TaskError, match='No se sobrescribira'):
        register_task(root, SID, 'schtasks.exe', runner, lambda message: None)
    assert not any('/Create' in args for args in calls)


def test_task_listing_failure_does_not_imply_absence(tmp_path):
    root = project(tmp_path)
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return response(1, stderr=b'Access denied')
    with pytest.raises(TaskError, match='consultar'):
        register_task(root, SID, 'schtasks.exe', runner)
    assert len(calls) == 1


def test_creation_failure_not_reported_as_success(tmp_path):
    root = project(tmp_path)
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return response(1, stderr=b'Access denied') if '/Create' in args else response()
    messages = []
    with pytest.raises(TaskError, match='Access denied'):
        register_task(root, SID, 'schtasks.exe', runner, messages.append)
    assert messages == []


@pytest.mark.parametrize('field', [
    't:Settings/t:StartWhenAvailable',
    't:Settings/t:Enabled',
    't:Triggers/t:LogonTrigger/t:Enabled',
    't:Triggers/t:CalendarTrigger/t:Enabled',
])
def test_verification_rejects_disabled_catchup_or_triggers(tmp_path, field):
    root = project(tmp_path)
    document = parse_task_xml(build_task_xml(root, SID))
    document.find(field, NS).text = 'false'
    with pytest.raises(TaskError):
        verify_task(document, root, SID)


def test_invalid_existing_xml_preserves_task(tmp_path):
    root = project(tmp_path)
    runner, calls, state = native_runner(root, b'not XML')
    with pytest.raises(TaskError, match='no se sobrescribira'):
        register_task(root, SID, 'schtasks.exe', runner)
    assert not any('/Create' in args for args in calls)


def test_missing_python_stops_before_windows_calls(tmp_path):
    def runner(*args, **kwargs):
        pytest.fail('Must not invoke Windows without project prerequisites')
    with pytest.raises(TaskError, match='CONFIGURAR'):
        register_task(tmp_path, SID, 'schtasks.exe', runner)


def test_invalid_user_sid_rejected(tmp_path):
    with pytest.raises(TaskError, match='usuario'):
        build_task_xml(tmp_path, 'someone')
