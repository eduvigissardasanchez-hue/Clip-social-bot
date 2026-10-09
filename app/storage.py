from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlsplit
import uuid
import boto3
import requests
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig
from .r2_budget import OperationBudget, R2BudgetExceeded


class StorageError(RuntimeError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class StorageProvider(ABC):
    @abstractmethod
    def upload(self, file: Path) -> str: ...
    @abstractmethod
    def delete(self, remote_key: str): ...
    @abstractmethod
    def exists(self, remote_key: str) -> bool: ...
    @abstractmethod
    def verify_public_url(self, url: str): ...


class R2Storage(StorageProvider):
    def __init__(self, config, client=None, http=None):
        config.validate_storage()
        self.bucket = config.r2_bucket
        self.base_url = config.r2_public_base_url
        self.max_bytes = min(config.r2_max_storage_bytes, 8_000_000_000)
        self.budget = OperationBudget(config.root/'data'/'r2_usage.db',
            min(config.r2_max_class_a_operations,100_000), min(config.r2_max_class_b_operations,1_000_000), config.dry_run)
        self.client = client or boto3.client('s3',
            endpoint_url=f'https://{config.r2_account_id}.r2.cloudflarestorage.com',
            aws_access_key_id=config.r2_access_key_id,
            aws_secret_access_key=config.r2_secret_access_key,
            region_name='auto', config=BotoConfig(retries={'total_max_attempts': 1},
                                                connect_timeout=15, read_timeout=60))
        self.http = http or requests.Session()

    def _call(self, operation, category, **kwargs):
        self.budget.reserve(category)
        return getattr(self.client, operation)(**kwargs)

    def check_space(self, added_bytes):
        if added_bytes < 0 or added_bytes > 5_000_000_000 or added_bytes > self.max_bytes:
            raise R2BudgetExceeded('El archivo supera el limite seguro de subida; permanece local.')
        # Single PUT avoids accumulating billable unfinished multipart uploads.
        unfinished = self._call('list_multipart_uploads', 'A', Bucket=self.bucket, MaxUploads=1)
        if not isinstance(unfinished, dict) or unfinished.get('Uploads') or unfinished.get('IsTruncated'):
            raise R2BudgetExceeded('R2 contiene subidas multipart pendientes o no puede comprobarlas; revisa el bucket.')
        total, token, seen = 0, None, set()
        while True:
            args = {'Bucket':self.bucket, 'MaxKeys':1000}
            if token:
                args['ContinuationToken'] = token
            page = self._call('list_objects_v2', 'A', **args)
            if not isinstance(page, dict):
                raise R2BudgetExceeded('No se puede medir el espacio R2; no se subiran videos.')
            for item in page.get('Contents', []):
                if item.get('StorageClass', 'STANDARD') != 'STANDARD':
                    raise R2BudgetExceeded('Hay objetos fuera de Standard en el bucket; esa clase no tiene cuota gratuita.')
                size = item.get('Size')
                if type(size) is not int or size < 0:
                    raise R2BudgetExceeded('R2 devolvio un tamano desconocido; subida bloqueada.')
                total += size
            if total + added_bytes > self.max_bytes:
                raise R2BudgetExceeded(f'Limite preventivo R2: {total/1e9:.2f} GB ocupados; '
                                      f'el archivo anadiria {added_bytes/1e9:.2f} GB y el tope es {self.max_bytes/1e9:.2f} GB. '
                                      'No se subira; espera a que se publiquen y limpien clips.')
            if not page.get('IsTruncated', False):
                return total
            token = page.get('NextContinuationToken')
            if not token or token in seen:
                raise R2BudgetExceeded('Medicion R2 incompleta; subida bloqueada.')
            seen.add(token)

    @staticmethod
    def key(file: Path):
        from .scanner import file_hash
        return f'clips/{file_hash(file)}.mp4'

    def upload(self, file: Path) -> str:
        key = self.key(file)
        if not self.exists(key):
            size = file.stat().st_size
            self.check_space(size)
            with file.open('rb') as stream:
                self._call('put_object', 'A', Bucket=self.bucket, Key=key, Body=stream,
                           ContentLength=size, ContentType='video/mp4', StorageClass='STANDARD')
        url = f'{self.base_url}/{key}'
        self.verify_public_url(url)
        return url

    def delete(self, remote_key):
        self.client.delete_object(Bucket=self.bucket, Key=remote_key)  # DeleteObject is free, including at the operation cap.

    def exists(self, remote_key):
        try:
            result = self._call('head_object', 'B', Bucket=self.bucket, Key=remote_key)
            if isinstance(result, dict) and result.get('StorageClass', 'STANDARD') != 'STANDARD':
                raise R2BudgetExceeded('El objeto R2 no es Standard; no se usara para publicar.')
            return True
        except ClientError as exc:
            if str(exc.response['Error']['Code']) in ('404', 'NoSuchKey', 'NotFound'):
                return False
            status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0)
            raise StorageError('No se pudo comprobar el objeto R2', retryable=status >= 500 or status == 429) from None

    def verify_public_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != urlsplit(self.base_url).netloc or parsed.query:
            raise ValueError('URL R2 inválida: se requiere HTTPS público estable')
        # Unauthenticated GET, no redirects; stream avoids downloading the whole video.
        self.budget.reserve('B')
        with self.http.get(url, headers={'Range': 'bytes=0-1023'},
                           timeout=30, stream=True, allow_redirects=False) as response:
            if response.status_code not in (200, 206):
                raise StorageError('El medio no es accesible públicamente mediante HTTPS',
                                   retryable=response.status_code >= 500 or response.status_code == 429)
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            if parsed.path.endswith('.mp4') and content_type not in ('video/mp4', 'application/octet-stream'):
                raise ValueError('La URL no devuelve un vídeo MP4')
            if not next(response.iter_content(1024), b''):
                raise ValueError('La URL pública devuelve un archivo vacío')

    def diagnose(self, dry_run=True):
        self._call('head_bucket', 'B', Bucket=self.bucket)
        if dry_run:
            return 'R2: bucket accesible; DRY_RUN impide la prueba de escritura y acceso público.'
        key = f'diagnostics/{uuid.uuid4().hex}.txt'
        payload = b'Clips Social Bot storage probe'
        self.check_space(len(payload))
        uploaded = False
        try:
            uploaded = True  # Cleanup also after an uncertain write result.
            self._call('put_object', 'A', Bucket=self.bucket, Key=key, Body=payload, ContentType='text/plain', StorageClass='STANDARD')
            url = f'{self.base_url}/{key}'
            self.verify_public_url(url)
            self.budget.reserve('B')
            with self.http.get(url, timeout=30, allow_redirects=False) as response:
                if response.status_code != 200 or response.content != payload:
                    raise ValueError('El contenido público R2 no coincide con la prueba')
        finally:
            if uploaded:
                self.delete(key)
        if self.exists(key):
            raise RuntimeError('R2 no confirmó la eliminación del archivo de prueba')
        return 'R2: subida, HTTPS público, contenido y borrado comprobados.'
