from datetime import datetime
from .models import PLATFORMS
from .buffer_client import BufferError


def discover(client, config, emit=print):
    account = client.account()
    organizations = account['organizations']
    for org in organizations:
        emit(f'Organización: {org["name"]} — {org["id"]}')
    if config.organization_id:
        choices = [org for org in organizations if org['id'] == config.organization_id]
    else:
        choices = organizations
    if len(choices) != 1:
        raise BufferError('Configura BUFFER_ORGANIZATION_ID en .env para elegir exactamente una organización.')
    org_id = choices[0]['id']
    channels = client.channels(org_id)
    for channel in channels:
        emit(f'Canal: {channel["service"]} — {channel.get("displayName") or channel["name"]} — {channel["id"]}')
    selected = {}
    for platform in PLATFORMS:
        matches = [c for c in channels if c['service'] == platform]
        configured_id = config.channel_ids.get(platform)
        if configured_id:
            matches = [c for c in matches if c['id'] == configured_id]
        if len(matches) != 1:
            raise BufferError(f'{platform}: configura BUFFER_{platform.upper()}_CHANNEL_ID en .env; '
                              'se requiere exactamente un canal de esa plataforma.')
        channel = matches[0]
        if channel['isDisconnected'] or channel['isLocked'] or channel['isQueuePaused']:
            raise BufferError(f'{platform}: canal desconectado, bloqueado o con cola pausada. Corrige Buffer.')
        if (channel.get('metadata') or {}).get('defaultToReminders') is not False:
            raise BufferError(f'{platform}: Buffer requiere o no confirma autopublicación. '
                              'No se admite notification publishing; activa publicación automática en Buffer.')
        selected[platform] = channel
        emit(f'{platform:10} ✓ conectado y automático')
    return org_id, selected


def check_schedules(channels):
    reference = None
    for platform, channel in channels.items():
        schedule = channel['postingSchedule']
        normalized = tuple(sorted((day['day'], day['paused'], tuple(sorted(day['times']))) for day in schedule))
        if (len(schedule) != 7 or {day['day'] for day in schedule} != {'mon','tue','wed','thu','fri','sat','sun'}
                or any(day['paused'] or sorted(day['times']) != ['10:00','22:00'] for day in schedule)):
            raise BufferError(f'{platform}: configura en Buffer 10:00 y 22:00 todos los días sin pausas.')
        signature = (channel['timezone'], normalized)
        if reference is not None and signature != reference:
            raise BufferError('Las zonas horarias o calendarios Buffer de los tres canales no coinciden.')
        reference = signature


def instant(value):
    if not value:
        raise BufferError('Buffer no asignó fecha; no se puede comprobar la alineación.')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise BufferError('Fecha Buffer sin zona horaria.')
    return date


def check_queues(channels, remote_posts, ignore_ids=(), tolerance_seconds=300):
    ignore_ids = set(ignore_ids)
    times = []
    for channel in channels.values():
        posts = [p for p in remote_posts if p['channelId'] == channel['id'] and p['id'] not in ignore_ids
                 and p['status'] in ('scheduled','sending')]
        times.append(sorted(instant(p['dueAt']) for p in posts))
    if len({len(queue) for queue in times}) != 1:
        raise BufferError('Las colas Buffer tienen distinta longitud. Revisa las publicaciones ajenas al bot antes de añadir clips.')
    for group in zip(*times):
        if (max(group)-min(group)).total_seconds() > tolerance_seconds:
            raise BufferError('Las fechas existentes de las tres colas están desalineadas. Revisa las colas en Buffer.')
