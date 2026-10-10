"""Register a native Windows task through schtasks.exe and XML, without PowerShell.

Schema: https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema
CLI: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create
"""
import csv
from datetime import datetime
import io
import ntpath
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

TASK_NAME = 'ClipsSocialBotBuffer'
NAMESPACE = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
NS = {'t': NAMESPACE}
ET.register_namespace('', NAMESPACE)


class TaskError(RuntimeError):
    pass


def _element(parent, name, value=None, **attrs):
    item = ET.SubElement(parent, f'{{{NAMESPACE}}}{name}', attrs)
    if value is not None:
        item.text = str(value)
    return item


def _arguments(root):
    return f'"{root / "main.py"}" maintain'


def build_task_xml(root, user_sid, date=None):
    root = Path(root).resolve()
    if not re.fullmatch(r'S-\d+(?:-\d+)+', user_sid):
        raise TaskError('No se pudo identificar el usuario Windows; no se registrara la tarea.')
    date = date or datetime.now()
    task = ET.Element(f'{{{NAMESPACE}}}Task', {'version': '1.2'})
    info = _element(task, 'RegistrationInfo')
    _element(info, 'Description', 'Clips Social Bot: reconciliar Buffer y rellenar la cola local; requiere la sesion del usuario.')
    _element(info, 'URI', '\\' + TASK_NAME)
    triggers = _element(task, 'Triggers')
    daily = _element(triggers, 'CalendarTrigger')
    _element(daily, 'StartBoundary', date.strftime('%Y-%m-%d') + 'T03:15:00')
    _element(daily, 'Enabled', 'true')
    _element(_element(daily, 'ScheduleByDay'), 'DaysInterval', '1')
    logon = _element(triggers, 'LogonTrigger')
    _element(logon, 'Enabled', 'true')
    _element(logon, 'UserId', user_sid)
    _element(logon, 'Delay', 'PT1M')
    principal = _element(_element(task, 'Principals'), 'Principal', id='BotUser')
    _element(principal, 'UserId', user_sid)
    _element(principal, 'LogonType', 'InteractiveToken')
    _element(principal, 'RunLevel', 'LeastPrivilege')
    settings = _element(task, 'Settings')
    for key, value in {
        'MultipleInstancesPolicy': 'IgnoreNew',
        'DisallowStartIfOnBatteries': 'false',
        'StopIfGoingOnBatteries': 'false',
        'AllowHardTerminate': 'true',
        'StartWhenAvailable': 'true',
        'AllowStartOnDemand': 'true',
        'Enabled': 'true',
        'Hidden': 'false',
        'RunOnlyIfIdle': 'false',
        'WakeToRun': 'false',
        'ExecutionTimeLimit': 'PT1H',
    }.items():
        _element(settings, key, value)
    action = _element(_element(task, 'Actions', Context='BotUser'), 'Exec')
    _element(action, 'Command', root / '.venv' / 'Scripts' / 'pythonw.exe')
    _element(action, 'Arguments', _arguments(root))
    _element(action, 'WorkingDirectory', root)
    return ET.tostring(task, encoding='utf-16', xml_declaration=True)


def _decode(raw):
    if isinstance(raw, str):
        return raw
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    if b'\x00' in raw[:50]:
        return raw.decode('utf-16-le')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('mbcs' if os.name == 'nt' else 'cp1252')


def parse_task_xml(raw):
    try:
        document = ET.fromstring(_decode(raw))
        if document.tag != f'{{{NAMESPACE}}}Task':
            raise TaskError('El Programador devolvio un XML de tarea desconocido.')
        return document
    except (ET.ParseError, UnicodeError):
        raise TaskError('No se pudo leer la tarea existente; no se sobrescribira.') from None


def _path_equal(left, right):
    return ntpath.normcase(ntpath.normpath(left or '')) == ntpath.normcase(ntpath.normpath(str(right)))


def owns_task(document, root, user_sid):
    root = Path(root).resolve()
    actions = document.findall('t:Actions/t:Exec', NS)
    principals = document.findall('t:Principals/t:Principal', NS)
    if len(actions) != 1 or len(principals) != 1:
        return False
    return (
        len(list(document.find('t:Actions', NS))) == 1
        and _path_equal(actions[0].findtext('t:Command', namespaces=NS), root / '.venv' / 'Scripts' / 'pythonw.exe')
        and actions[0].findtext('t:Arguments', namespaces=NS) == _arguments(root)
        and _path_equal(actions[0].findtext('t:WorkingDirectory', namespaces=NS), root)
        and principals[0].findtext('t:UserId', namespaces=NS) == user_sid
    )


def _require_xml_value(document, path, expected, default=None):
    """Compare effective XML values, including documented Windows defaults.

    schtasks may omit default-valued properties on export. Boolean XML values
    can also be written as 1/0. Never treat an unknown value as a default.
    """
    value = document.findtext(path, namespaces=NS)
    omitted = value is None
    actual = default if omitted else value.strip()
    if expected in ('true', 'false'):
        actual = {'1': 'true', '0': 'false'}.get(actual, actual)
    if actual != expected:
        name = path.rsplit('/', 1)[-1].removeprefix('t:')
        detail = ' (valor predeterminado; campo omitido)' if omitted and default is not None else ''
        raise TaskError(f'La tarea registrada no confirma {name}: Windows devuelve '
                        f'{actual!r}{detail}; se esperaba {expected!r}.')


def verify_task(document, root, user_sid):
    if not owns_task(document, root, user_sid):
        raise TaskError('La tarea registrada no coincide con este proyecto y usuario.')
    # Defaults from Microsoft's Task Scheduler schema. StartWhenAvailable is
    # false by default, so omission must still fail the catch-up requirement.
    required = {
        'StartWhenAvailable': ('true', 'false'),
        'MultipleInstancesPolicy': ('IgnoreNew', 'IgnoreNew'),
        'Enabled': ('true', 'true'),
    }
    for setting, (expected, default) in required.items():
        _require_xml_value(document, f't:Settings/t:{setting}', expected, default)
    _require_xml_value(document, 't:Principals/t:Principal/t:LogonType', 'InteractiveToken')
    # Windows uses low privileges by default (see Microsoft's "Security
    # Contexts for Running Tasks"); an explicit HighestAvailable remains invalid.
    _require_xml_value(document, 't:Principals/t:Principal/t:RunLevel',
                       'LeastPrivilege', 'LeastPrivilege')
    triggers = document.find('t:Triggers', NS)
    daily = document.find('t:Triggers/t:CalendarTrigger', NS)
    logon = document.find('t:Triggers/t:LogonTrigger', NS)
    if triggers is None or len(list(triggers)) != 2 or daily is None or logon is None:
        raise TaskError('La tarea no confirma disparadores diario y de inicio de sesion.')
    boundary = daily.findtext('t:StartBoundary', namespaces=NS) or ''
    if (not re.fullmatch(r'\d{4}-\d{2}-\d{2}T03:15:00(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?', boundary) or
            daily.findtext('t:ScheduleByDay/t:DaysInterval', namespaces=NS) != '1' or
            logon.findtext('t:UserId', namespaces=NS) != user_sid):
        raise TaskError('La tarea no confirma las 03:15 diarias y tu inicio de sesion.')
    for trigger in ('CalendarTrigger', 'LogonTrigger'):
        _require_xml_value(document, f't:Triggers/t:{trigger}/t:Enabled', 'true', 'true')


def _run(runner, args):
    try:
        return runner(args, capture_output=True, check=False)
    except OSError:
        raise TaskError('No se pudo ejecutar la herramienta nativa del Programador de tareas Windows.') from None


def register_task(root, user_sid, schtasks, runner=subprocess.run, emit=print):
    root = Path(root).resolve()
    if not (root / '.venv' / 'Scripts' / 'pythonw.exe').is_file() or not (root / 'main.py').is_file():
        raise TaskError('Ejecuta CONFIGURAR.bat primero; falta Python del proyecto o main.py.')
    # List names first: a failed single-task query does not establish its absence.
    listing = _run(runner, [str(schtasks), '/Query', '/FO', 'CSV', '/NH'])
    if listing.returncode != 0:
        raise TaskError('Windows no permite consultar sus tareas; comprueba los permisos. No se ha registrado nada.')
    rows = csv.reader(io.StringIO(_decode(listing.stdout)))
    exists = any(row and row[0].lstrip('\\').casefold() == TASK_NAME.casefold() for row in rows)
    if exists:
        result = _run(runner, [str(schtasks), '/Query', '/TN', TASK_NAME, '/XML'])
        if result.returncode != 0:
            raise TaskError('No se puede inspeccionar la tarea existente; no se sobrescribira.')
        if not owns_task(parse_task_xml(result.stdout), root, user_sid):
            raise TaskError('Ya existe una tarea con ese nombre y otro proyecto o usuario. No se sobrescribira.')
    with tempfile.TemporaryDirectory(prefix='clips_social_task_') as directory:
        xml_path = Path(directory) / 'task.xml'
        xml_path.write_bytes(build_task_xml(root, user_sid))
        args = [str(schtasks), '/Create', '/TN', TASK_NAME, '/XML', str(xml_path)]
        if exists:
            args.append('/F')
        result = _run(runner, args)
        if result.returncode != 0:
            message = _decode(result.stderr).strip()
            raise TaskError(f'Windows rechazo el registro de la tarea (codigo {result.returncode}). '
                            f'{message or "Comprueba los permisos del Programador de tareas."}')
    result = _run(runner, [str(schtasks), '/Query', '/TN', TASK_NAME, '/XML'])
    if result.returncode != 0:
        raise TaskError('Se solicito registrar la tarea, pero no pudo verificarse. Abre el Programador de tareas para revisarla.')
    verify_task(parse_task_xml(result.stdout), root, user_sid)
    emit('Tarea instalada y verificada: ClipsSocialBotBuffer.')
    emit('Diaria a las 03:15 y al iniciar sesion (tras un minuto); recupera ejecuciones perdidas.')
    emit('No necesita consola abierta ni contrasenas guardadas. Consulta logs\\bot.log.')
    emit('Mantiene la politica de PowerShell. Usa DRY_RUN=false para programar de verdad.')


def main():
    if os.name != 'nt':
        raise TaskError('Este instalador solo funciona en Windows 10/11.')
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    result = _run(subprocess.run, [str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'])
    if result.returncode != 0:
        raise TaskError('Windows no pudo identificar tu usuario.')
    match = re.search(r'\bS-\d+(?:-\d+)+\b', _decode(result.stdout))
    if not match:
        raise TaskError('No se obtuvo el SID de tu usuario; no se instalara la tarea.')
    register_task(Path(__file__).resolve().parent.parent, match.group(), system / 'schtasks.exe')


if __name__ == '__main__':
    try:
        main()
    except TaskError as error:
        print(f'ERROR: {error}')
        raise SystemExit(1)
