from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from .buffer_client import BufferError
from .captions import Captions, read_captions
from .channels import discover, check_schedules, check_queues, instant
from .cleanup import cleanup_clip
from .database import Database
from .locking import process_lock
from .models import PLATFORMS
from .post_inputs import post_input
from .scanner import scan, file_hash
from .scheduler import available_capacity
from .storage import StorageError
from .r2_budget import R2BudgetExceeded
import requests
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError, ConnectionClosedError


def recoverable_preparation(error):
    if isinstance(error, StorageError):
        return error.retryable
    if isinstance(error, (requests.Timeout, requests.ConnectionError, EndpointConnectionError,
                          ConnectTimeoutError, ReadTimeoutError, ConnectionClosedError)):
        return True
    if isinstance(error, ClientError):
        status = error.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0)
        return status >= 500 or status == 429 or error.response.get('Error', {}).get('Code') in (
            'SlowDown', 'RequestTimeout', 'InternalError', 'ServiceUnavailable')
    return False


def now():
    return datetime.now(timezone.utc)


def public_url(storage, path):
    return storage.base_url + '/' + storage.key(path)


class Workflow:
    def __init__(self, config, buffer, storage, emit=print):
        self.config, self.buffer, self.storage, self.emit = config, buffer, storage, emit
        self.root = config.root

    def _candidates(self, db=None):
        discovered = scan(self.root / 'pendientes')
        existing = [dict(c) for c in db.clips()] if db else []
        known = {c['sha256'] for c in existing}
        return existing + [dict(sha256=c.sha256, filename=c.filename, path=c.path,
                               position=len(existing)+i, public_url=None, captions_json=None)
                           for i,c in enumerate(discovered, 1) if c.sha256 not in known]

    def preview(self, only_one=False):
        # Read-only even when DRY_RUN is false: first-publication confirmation happens later.
        path = self.root / 'data' / 'bot.db'
        db = Database(path, readonly=True) if path.exists() else None
        try:
            candidates = [c for c in self._candidates(db) if not c.get('archived') and
                          (not db or len(db.posts(c['sha256'])) != 3 or not all(p['post_id'] for p in db.posts(c['sha256'])))]
            if only_one:
                # First-publication mode only selects clips with no existing/uncertain posts.
                candidates = [c for c in candidates if not db or all(not p['post_id'] and
                              dict(p).get('intent', '') not in ('creating','uncertain') for p in db.posts(c['sha256']))][:1]
            org, channels = discover(self.buffer, self.config, self.emit)
            check_schedules(channels)
            remote = self.buffer.posts(org, [c['id'] for c in channels.values()], ['scheduled','sending'])
            partial_ids = []
            if db:
                for c in candidates:
                    posts = [dict(p) for p in db.posts(c['sha256'])]
                    if posts and not all(p['post_id'] for p in posts):
                        partial_ids.extend(p['post_id'] for p in posts if p['post_id'])
            check_queues(channels, remote, partial_ids)
            counts = {p: sum(post['channelId']==channels[p]['id'] for post in remote) for p in PLATFORMS}
            self.emit(self.storage.diagnose(dry_run=True))
            self.emit(f'Clips pendientes: {len(candidates)}; capacidad conjunta: {available_capacity(counts, self.config.capacity)}')
            for c in candidates:
                video = Path(c['path'])
                if not video.exists() or file_hash(video) != c['sha256']:
                    raise ValueError('Archivo pendiente ausente o modificado. Revisa la cola local.')
                captions = Captions(**json.loads(c['captions_json'])) if c.get('captions_json') else read_captions(video)
                url = c.get('public_url') or public_url(self.storage, video)
                if c.get('public_url'):
                    self.storage.verify_public_url(url)
                self.emit(f'Archivo: {video}\nSHA-256: {c["sha256"]}\nURL pública: {url}')
                saved = {p['platform']:p['post_id'] for p in db.posts(c['sha256'])} if db else {}
                for p in PLATFORMS:
                    payload = post_input(p, channels[p]['id'], captions, url, self.config.thumbnail_offset_ms)
                    if saved.get(p):
                        self.emit(f'  {p}: conservar post {saved[p]}')
                    else:
                        self.emit(f'  {p}: {channels[p]["id"]}; texto: {payload["text"]!r}; metadata: {payload["metadata"]}')
                        self.emit('    Acción: crear vídeo automático en la cola Buffer si hay capacidad.')
                c['planned_captions'] = asdict(captions)
                c['planned_channels'] = {p:channels[p]['id'] for p in PLATFORMS}
                c['planned_url'] = url
                self.emit('Acciones: subir MP4 una vez si falta en R2; conservar medios hasta 3 estados sent.\n')
            return candidates
        finally:
            if db:
                db.close()

    def run(self, *, only_hash=None, limit=None, expected_plan=None):
        self.expected_plan = expected_plan
        if self.config.dry_run:
            self.preview(only_one=limit == 1)
            self.emit('DRY_RUN: no se ha modificado nada.')
            return
        with process_lock(self.root / 'data' / 'bot.lock'):
            db = Database(self.root / 'data' / 'bot.db')
            try:
                db.register(scan(self.root / 'pendientes'))
                org, channels = discover(self.buffer, self.config, self.emit)
                check_schedules(channels)
                remote = self.buffer.posts(org, [c['id'] for c in channels.values()], ['scheduled','sending'])
                self._reconcile(db, org, channels, remote)
                if not only_hash:
                    self._retry_publishing(db, remote)
                for c in [dict(c) for c in db.clips()]:
                    if not c['archived'] and (not only_hash or c['sha256']==only_hash):
                        try:
                            if cleanup_clip(db, c, self.storage, self.root):
                                self.emit(f'{c["filename"]}: publicado en las tres redes y archivado.')
                        except Exception:
                            db.update_clip(c['sha256'], last_error='No se pudo limpiar/archivar; se reintentará sin recrear posts.')
                            self.emit(f'{c["filename"]}: limpieza pendiente; consulta las carpetas y R2.')
                # Deletions are free; allow already-sent media cleanup before a read-budget check.
                self.storage.diagnose(dry_run=True)
                counts = {p: sum(post['channelId']==channels[p]['id'] for post in remote) for p in PLATFORMS}
                candidates = [dict(c) for c in db.clips() if not c['archived']]
                partial_ids = []
                for c in candidates:
                    posts = db.posts(c['sha256'])
                    if not all(p['post_id'] for p in posts):
                        partial_ids.extend(p['post_id'] for p in posts if p['post_id'])
                check_queues(channels, remote, partial_ids)
                self.emit(f'Capacidad disponible: {available_capacity(counts, self.config.capacity)} clips')
                completed = 0
                for c in candidates:
                    if only_hash and c['sha256'] != only_hash:
                        continue
                    if limit is not None and completed >= limit:
                        break
                    posts = {p['platform']:dict(p) for p in db.posts(c['sha256'])}
                    missing = [p for p in PLATFORMS if not posts[p]['post_id']]
                    if not missing:
                        self._align(db, c, posts, channels, remote)
                        continue
                    if any(posts[p]['intent'] == 'uncertain' or
                           (posts[p]['state'] == 'error' and not posts[p]['retryable']) for p in missing):
                        self.emit(f'{c["filename"]}: requiere revisión; se detiene para conservar el orden.')
                        break
                    if any(posts[p]['attempts'] >= self.config.max_attempts or
                           (posts[p]['next_retry_at'] and instant(posts[p]['next_retry_at']) > now()) for p in missing):
                        self.emit(f'{c["filename"]}: reintento pendiente; se mantiene en cola local.')
                        break
                    if any(counts[p] >= self.config.capacity for p in missing):
                        break
                    if c['preparation_attempts'] >= self.config.max_attempts or (c['next_retry_at'] and instant(c['next_retry_at']) > now()):
                        self.emit(f'{c["filename"]}: preparación pendiente; revisa el error antes de continuar.')
                        break
                    try:
                        self._schedule_clip(db, c, posts, missing, channels, counts, remote)
                    except R2BudgetExceeded as error:
                        db.update_clip(c['sha256'], last_error=str(error), preparation_attempts=0,
                                       next_retry_at=(now()+timedelta(hours=12)).isoformat())
                        self.emit(f'AVISO: {error}')
                        self.emit('Los siguientes clips permanecen locales. Revisa el uso real en Cloudflare; no borres los contadores.')
                        break
                    except BufferError:
                        raise
                    except Exception as error:
                        retryable = recoverable_preparation(error)
                        for platform in missing:
                            db.update_post(c['sha256'], platform, state='error', retryable=int(retryable),
                                           last_error='Error de preparación: revisa MP4, sidecars y R2.')
                        db.update_clip(c['sha256'], last_error='No se pudo preparar el archivo o storage; revisa y reintenta.',
                                       next_retry_at=(now()+timedelta(seconds=min(86400,60*2**c['preparation_attempts']))).isoformat())
                        self.emit(f'{c["filename"]}: error de preparación; cola local conservada.')
                        break
                    fresh = {p['platform']:dict(p) for p in db.posts(c['sha256'])}
                    if not all(p['post_id'] for p in fresh.values()):
                        break
                    self._align(db, c, fresh, channels, remote)
                    completed += 1
                self.emit(f'{completed} clips completados en Buffer en esta ejecución.')
                remaining = sum(not all(p['post_id'] for p in db.posts(c['sha256'])) for c in db.clips())
                self.emit(f'{remaining} quedan en cola local. Puedes cerrar esta ventana.')
            finally:
                db.close()

    def _reconcile(self, db, org, channels, remote):
        by_id = {post['id']:post for post in remote}
        missing_ids = []
        uncertain = []
        for clip in db.clips():
            for p in db.posts(clip['sha256']):
                if p['channel_id'] and p['channel_id'] != channels[p['platform']]['id']:
                    raise BufferError('El canal configurado cambió respecto a SQLite. No se recrearán posts en otro canal.')
                if p['post_id'] and p['state'] != 'sent' and p['post_id'] not in by_id:
                    missing_ids.append(p['post_id'])
                if not p['post_id'] and p['intent'] in ('creating','uncertain'):
                    uncertain.append((dict(clip),dict(p)))
        for post in self.buffer.posts_by_ids(missing_ids):
            by_id[post['id']] = post
        if uncertain:
            history = self.buffer.posts(org, [c['id'] for c in channels.values()])
            for clip, p in uncertain:
                matches = [post for post in history if post['channelId']==channels[p['platform']]['id']
                           and any(a.get('source') == clip['public_url'] for a in post.get('assets', []))]
                if len(matches) == 1:
                    post = matches[0]
                    db.record_post(clip['sha256'], p['platform'], post['id'])
                    by_id[post['id']] = post
                    self.emit(f'{clip["filename"]}: post {p["platform"]} recuperado; no se duplicó.')
                else:
                    db.update_post(clip['sha256'], p['platform'], intent='uncertain', state='error', retryable=0,
                                   last_error='Resultado incierto. Revisa Buffer y usa resolve-uncertain si confirmas ausencia.')
        for clip in db.clips():
            for p in db.posts(clip['sha256']):
                if p['post_id'] not in by_id:
                    continue
                post = by_id[p['post_id']]
                if post['channelId'] != channels[p['platform']]['id']:
                    raise BufferError('Buffer devolvió un post de otro canal; reconciliación detenida.')
                status = post['status']
                state = {'sent':'sent','scheduled':'scheduled','sending':'queued'}.get(status,'error')
                message = None if state != 'error' else 'Buffer informa error, borrador o aprobación pendiente. Revisa ese post; no se recreará.'
                if post.get('schedulingType') != 'automatic':
                    state, message = 'error', 'Buffer requiere publicación por notificación; activa autopublicación.'
                import re
                raw_message = (post.get('error') or {}).get('message', '').lower()
                recoverable = (status == 'error' and post.get('schedulingType') == 'automatic' and
                               bool(re.search(r'temporar|timed out|timeout|rate limit|try again|unavailable', raw_message)) and
                               not re.search(r'invalid|permission|auth|disconnect|format|too long|unsupported|expired', raw_message))
                db.update_post(clip['sha256'], p['platform'], state=state, scheduled_at=post.get('dueAt'),
                               intent='', last_error=message, retryable=2 if p['retryable']==2 else int(recoverable))

    def _schedule_clip(self, db, c, posts, missing, channels, counts, remote):
        db.update_clip(c['sha256'], preparation_attempts=c['preparation_attempts']+1,
                       last_attempt_at=now().isoformat())
        video = Path(c['path'])
        if not video.exists() or file_hash(video) != c['sha256']:
            raise ValueError('El archivo no coincide con el hash registrado.')
        captions = Captions(**json.loads(c['captions_json'])) if c['captions_json'] else read_captions(video)
        url = c['public_url'] or public_url(self.storage, video)
        inputs = {p:post_input(p, channels[p]['id'], captions, url, self.config.thumbnail_offset_ms) for p in missing}
        if self.expected_plan:
            if (c['sha256'] != self.expected_plan['sha256'] or asdict(captions) != self.expected_plan['planned_captions'] or
                url != self.expected_plan['planned_url'] or
                {p:channels[p]['id'] for p in PLATFORMS} != self.expected_plan['planned_channels']):
                raise ValueError('La vista previa cambió; vuelve a ejecutar PROBAR_PUBLICACION para confirmar.')
        # Validate all platform metadata before the first remote side effect.
        if not c['captions_json']:
            db.update_clip(c['sha256'], captions_json=json.dumps(asdict(captions), ensure_ascii=False))
        if not c['public_url']:
            url = self.storage.upload(video)
            db.update_clip(c['sha256'], public_url=url, remote_key=self.storage.key(video), last_error=None)
        else:
            self.storage.verify_public_url(url)
        db.update_clip(c['sha256'], preparation_attempts=0, next_retry_at=None, last_error=None)
        self.emit(c['filename'])
        anchor = next((p['scheduled_at'] for p in posts.values() if p['post_id'] and p['scheduled_at']), None)
        for platform in missing:
            p = posts[platform]
            payload = inputs[platform]
            payload['assets'][0]['video']['url'] = url
            # Only repair a proven partial clip, using the existing Buffer-assigned date.
            if anchor and any(post['post_id'] for post in posts.values()):
                if instant(anchor) <= now():
                    raise BufferError('El turno del clip parcial ya pasó. Corrige sus posts existentes en Buffer.')
                if any(post['channelId']==channels[platform]['id'] and post.get('dueAt') and
                       abs((instant(post['dueAt'])-instant(anchor)).total_seconds())<1 for post in remote):
                    raise BufferError('El turno de reparación ya está ocupado en Buffer; no se solaparán clips.')
                payload.update(mode='customScheduled', dueAt=anchor)
            attempt = p['attempts'] + 1
            db.update_post(c['sha256'], platform, intent='creating', channel_id=channels[platform]['id'],
                           attempts=attempt, last_attempt_at=now().isoformat(), state='uploaded')
            db.update_clip(c['sha256'], attempts=db.connection.execute('SELECT attempts FROM clips WHERE sha256=?', (c['sha256'],)).fetchone()[0]+1, last_attempt_at=now().isoformat())
            try:
                created = self.buffer.create_post(payload)
            except BufferError as error:
                wait = max(error.retry_after, min(86400, 60 * 2 ** (attempt-1)))
                db.update_post(c['sha256'], platform, state='error', intent='uncertain' if error.uncertain else '',
                               retryable=int(error.retryable and not error.uncertain),
                               next_retry_at=(now()+timedelta(seconds=wait)).isoformat(), last_error=str(error))
                self.emit(f'  {platform}: error; se conservan los posts de las otras plataformas.')
                # Continue independent platform creation only for a confirmed rejection.
                if error.uncertain:
                    return
                continue
            db.record_post(c['sha256'], platform, created['id'], scheduled_at=created.get('dueAt'))
            db.update_post(c['sha256'], platform, intent='', retryable=0, next_retry_at=None)
            counts[platform] += 1
            remote.append(created)
            if created.get('schedulingType') != 'automatic' or created.get('status') != 'scheduled':
                db.update_post(c['sha256'], platform, state='error', last_error='Buffer no confirmó programación automática.')
                raise BufferError('Buffer no confirmó autopublicación; revisa los posts creados. No se recrearán.')
            self.emit(f'  {platform:10} ✓ {created.get("dueAt") or "fecha pendiente"}')

    def _align(self, db, c, posts, channels, remote):
        scheduled = [p for p in posts.values() if p['state']=='scheduled' and p['scheduled_at']]
        if len(scheduled) != 3:
            return
        target = min(instant(p['scheduled_at']) for p in scheduled)
        if (max(instant(p['scheduled_at']) for p in scheduled)-target).total_seconds() <= 300:
            return
        if target <= now():
            raise BufferError('Desalineación comprobada pero el turno ya pasó; corrige las colas en Buffer.')
        due_at = target.isoformat()
        for platform, p in posts.items():
            if abs((instant(p['scheduled_at'])-target).total_seconds()) <= 300:
                continue
            if any(r['id'] != p['post_id'] and r['channelId']==channels[platform]['id'] and r.get('dueAt') and
                   abs((instant(r['dueAt'])-target).total_seconds())<1 for r in remote):
                raise BufferError('No se puede corregir la desalineación: el turno está ocupado.')
            corrected = self.buffer.reschedule(p['post_id'], due_at)
            if corrected['id'] != p['post_id'] or corrected.get('status') != 'scheduled' or not corrected.get('dueAt'):
                raise BufferError('Buffer no confirmó la corrección. Se conservan los IDs para reconciliar.')
            db.update_post(c['sha256'], platform, scheduled_at=corrected['dueAt'])
            for index, post in enumerate(remote):
                if post['id'] == p['post_id']:
                    remote[index] = corrected
            self.emit(f'  {platform}: fecha corregida al turno que Buffer asignó al mismo clip.')

    def _retry_publishing(self, db, remote):
        for clip in db.clips():
            for p in db.posts(clip['sha256']):
                if not (p['post_id'] and p['state'] == 'error' and p['retryable']):
                    continue
                if p['attempts'] >= self.config.max_attempts:
                    continue
                if p['next_retry_at'] and instant(p['next_retry_at']) > now():
                    continue
                if sum(r['channelId'] == p['channel_id'] for r in remote) >= self.config.capacity:
                    continue
                attempt = p['attempts'] + 1
                db.update_post(clip['sha256'], p['platform'], attempts=attempt,
                               last_attempt_at=now().isoformat(),
                               next_retry_at=(now()+timedelta(seconds=min(86400,60*2**attempt))).isoformat())
                try:
                    result = self.buffer.retry_post(p['post_id'])
                except BufferError as error:
                    db.update_post(clip['sha256'], p['platform'], last_error=str(error), retryable=int(error.retryable))
                    if error.uncertain:
                        # Existing ID permits safe reconciliation; do not edit again in this run.
                        raise
                    continue
                if result.get('status') != 'scheduled' or result.get('schedulingType') != 'automatic':
                    raise BufferError('Buffer no confirmó reprogramación automática del post existente.')
                db.update_post(clip['sha256'], p['platform'], state='scheduled', scheduled_at=result.get('dueAt'),
                               last_error=None, retryable=0)
                remote[:] = [r for r in remote if r['id'] != p['post_id']]
                remote.append(result)
                self.emit(f'{clip["filename"]}: reintentado {p["platform"]} conservando el mismo ID.')
