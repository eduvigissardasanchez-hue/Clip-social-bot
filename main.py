import argparse
from pathlib import Path
from contextlib import nullcontext
import os
import sys
from app.config import Config
from app.local_workflow import inspect_local
from app.database import Database
from app.captions import read_captions
from app.models import PLATFORMS, final_state
from app.buffer_client import BufferClient, BufferError
from app.channels import discover, check_schedules
from app.locking import process_lock


def show_status(root, emit=print):
    path = root / 'data' / 'bot.db'
    if not path.exists():
        emit('Sin clips registrados. Ejecuta ESCANEAR_CLIPS o PROGRAMAR_TODO primero.')
        return
    db = Database(path, readonly=True)
    totals = dict(sent=0, scheduled=0, local=0, error=0)
    try:
        emit(f'{"Clip":30} YouTube     Instagram   TikTok')
        for clip in db.clips():
            rows = db.posts(clip['sha256'])
            posts = {p['platform']: p['state'] for p in rows}
            emit(f'{clip["filename"]:30} ' + ' '.join(f'{posts[p]:11}' for p in PLATFORMS))
            state = final_state([posts[p] for p in PLATFORMS])
            totals[state if state in totals else 'local'] += 1
            for p in rows:
                if p['last_error']:
                    emit(f'  {p["platform"]}: {p["last_error"]}')
        emit(f'Publicados: {totals["sent"]}\nProgramados en Buffer: {totals["scheduled"]}\nEn cola local: {totals["local"]}\nErrores: {totals["error"]}')
    finally:
        db.close()


def run(argv=None):
    parser = argparse.ArgumentParser(description='Clips Social Bot — Buffer')
    parser.add_argument('command', choices=['scan', 'status', 'buffer', 'storage', 'schedule', 'maintain',
                                           'test-publication', 'resolve-uncertain', 'retry-errors'])
    parser.add_argument('--hash', dest='digest')
    parser.add_argument('--platform', choices=PLATFORMS)
    args = parser.parse_args(argv)
    config = Config.load()
    from app.logging_utils import output
    emit = output(config)
    emit('CLIPS SOCIAL BOT\n================')
    try:
        if args.command == 'status':
            show_status(config.root, emit)
        elif args.command == 'scan':
            with nullcontext() if config.dry_run else process_lock(config.root / 'data' / 'bot.lock'):
                clips = inspect_local(config.root, config.dry_run)
            emit(f'Clips únicos encontrados: {len(clips)}')
            for clip in clips:
                caption = read_captions(Path(clip.path))
                emit(f'{clip.position:3}. {clip.filename} — título: {caption.youtube_title}')
            emit('DRY_RUN: sin cambios.' if config.dry_run else 'Cola local registrada en SQLite.')
        elif args.command == 'buffer':
            org, channels = discover(BufferClient(config.buffer_api_key), config, emit)
            check_schedules(channels)
            emit('Clave válida, organización y tres canales automáticos identificados. No se publicó nada.')
        elif args.command == 'storage':
            from app.storage import R2Storage
            emit(R2Storage(config).diagnose(config.dry_run))
        elif args.command in ('resolve-uncertain','retry-errors'):
            if not args.digest or not args.platform:
                raise ValueError('Indica --hash SHA256 y --platform youtube|instagram|tiktok.')
            if config.dry_run:
                emit('DRY_RUN: no se cambiarán los registros para reintentar.')
                return 0
            with process_lock(config.root / 'data' / 'bot.lock'):
                db = Database(config.root / 'data' / 'bot.db')
                try:
                    matches = [dict(p) for p in db.posts(args.digest) if p['platform']==args.platform]
                    if not matches:
                        raise ValueError('No se encuentra ese clip/plataforma.')
                    post = matches[0]
                    if args.command == 'resolve-uncertain':
                        if post['post_id'] or post['intent'] not in ('creating','uncertain'):
                            raise ValueError('Este registro no tiene una creación incierta sin ID.')
                        emit('Revisa Buffer manualmente. Este cambio autoriza crear un post NUEVO en el siguiente mantenimiento.')
                        if input('Solo si confirmas que NO existe el post, escribe AUSENTE: ').strip() != 'AUSENTE':
                            emit('Cancelado.');return 0
                        db.update_post(args.digest,args.platform,intent='',state='uploaded',retryable=1,
                                       next_retry_at=None,attempts=0,last_error=None)
                    else:
                        if post['state'] != 'error':
                            raise ValueError('Solo se puede autorizar reintento de registros en error.')
                        emit('Corrige primero el problema en Buffer o el sidecar. Se conservará el ID existente si lo hay.')
                        if input('Escribe REINTENTAR para autorizar: ').strip() != 'REINTENTAR':
                            emit('Cancelado.');return 0
                        if post['intent'] in ('creating','uncertain'):
                            raise ValueError('Usa resolve-uncertain para resultados inciertos.')
                        # Explicit user authorizes one retry of a known publishing error.
                        db.update_post(args.digest,args.platform,retryable=2,attempts=0,next_retry_at=None,last_error=None)
                        db.update_clip(args.digest,preparation_attempts=0,next_retry_at=None,last_error=None,
                                       **({'captions_json':None} if not post['post_id'] else {}))
                    emit('Registro actualizado; ejecuta MANTENER_COLA para continuar.')
                finally:
                    db.close()
        else:
            from app.storage import R2Storage
            from app.workflow import Workflow
            workflow = Workflow(config, BufferClient(config.buffer_api_key), R2Storage(config), emit)
            if args.command == 'test-publication':
                candidates = workflow.preview(only_one=True)
                if not candidates:
                    emit('No hay clips nuevos para probar.');return 0
                if config.dry_run:
                    emit('DRY_RUN: vista previa terminada, sin cambios.');return 0
                if input('Para subir y programar SOLO este clip en las tres redes, escribe PROGRAMAR: ').strip() != 'PROGRAMAR':
                    emit('Cancelado.');return 0
                workflow.run(only_hash=candidates[0]['sha256'],limit=1,expected_plan=candidates[0])
            else:
                workflow.run()
        return 0
    except (BufferError, ValueError) as error:
        emit(f'ERROR: {error}')
        return 1
    except Exception:
        # Never emit SDK tracebacks, signed URLs or raw server responses.
        emit('ERROR: operación fallida. Comprueba configuración, archivos y conexión. Se conserva SQLite para continuar.')
        return 1


if __name__ == '__main__':
    # pythonw.exe is used by Task Scheduler and may have no console streams.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    try:
        sys.exit(run())
    except (ValueError, OSError):
        print('ERROR: no se pudo cargar la configuración .env.', file=sys.stderr)
        sys.exit(1)
