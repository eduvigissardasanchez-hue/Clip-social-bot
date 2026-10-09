"""Buffer GraphQL: official contract recorded in docs/BUFFER_SCHEMA.md."""
import time
import requests

POST_FIELDS = '''id channelId status dueAt schedulingType
assets { source } error { message }'''
ACCOUNT = 'query { account { id organizations { id name } } }'
CHANNELS = '''query Channels($organizationId: OrganizationId!) {
  channels(input: {organizationId: $organizationId}) {
    id name displayName service timezone isDisconnected isLocked isQueuePaused
    postingSchedule { day paused times }
    metadata {
      __typename
      ... on InstagramMetadata { defaultToReminders }
      ... on TiktokMetadata { defaultToReminders }
      ... on YoutubeMetadata { defaultToReminders }
    }
  }
}'''
POSTS = '''query Posts($input: PostsInput!, $after: String) {
  posts(input: $input, first: 100, after: $after) {
    edges { node { ''' + POST_FIELDS + ''' } }
    pageInfo { hasNextPage endCursor }
  }
}'''
CREATE = '''mutation Create($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { ''' + POST_FIELDS + ''' } }
    ... on MutationError { message }
  }
}'''
EDIT = '''mutation Edit($input: EditPostInput!) {
  editPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { ''' + POST_FIELDS + ''' } }
    ... on MutationError { message }
  }
}'''


class BufferError(RuntimeError):
    def __init__(self, message, *, retryable=False, uncertain=False, retry_after=0, code=''):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain
        self.retry_after = retry_after
        self.code = code


class BufferClient:
    endpoint = 'https://api.buffer.com'

    def __init__(self, api_key, session=None, sleep=time.sleep):
        if not api_key:
            raise BufferError('Configura BUFFER_API_KEY en .env; no la compartas en el chat.')
        self._api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep

    def execute(self, document, variables=None, *, mutation=False):
        for attempt in range(3):
            try:
                return self._request(document, variables, mutation)
            except BufferError as error:
                # Creation may have reached Buffer. Never blindly repeat it.
                if mutation or not error.retryable or attempt == 2:
                    raise
                delay = max(2 ** attempt, error.retry_after)
                if delay > 30:
                    raise
                self.sleep(delay)

    def _request(self, document, variables, mutation):
        try:
            response = self.session.post(self.endpoint,
                headers={'Authorization': f'Bearer {self._api_key}', 'Content-Type': 'application/json'},
                json={'query': document, 'variables': variables or {}}, timeout=45)
        except requests.RequestException:
            raise BufferError('Error de conexión con Buffer', retryable=True, uncertain=mutation) from None
        if response.status_code != 200:
            status = response.status_code
            try:
                wait = max(0, int(response.headers.get('Retry-After', '0')))
            except (TypeError, ValueError):
                wait = 0
            raise BufferError(f'Buffer devolvió HTTP {status}', retryable=status in (408, 429) or status >= 500,
                              uncertain=mutation and (status == 408 or status >= 500), retry_after=wait, code=str(status))
        try:
            body = response.json()
        except ValueError:
            raise BufferError('Respuesta Buffer ilegible', retryable=True, uncertain=mutation) from None
        if not isinstance(body, dict):
            raise BufferError('Respuesta GraphQL inválida', uncertain=mutation)
        if body.get('errors'):
            codes = {e.get('extensions', {}).get('code', '') for e in body['errors'] if isinstance(e, dict)}
            transient = bool(codes) and codes <= {'UNEXPECTED', 'RATE_LIMIT_EXCEEDED'}
            raise BufferError('Buffer devolvió errores GraphQL; operación no confirmada',
                              retryable=transient, uncertain=mutation and codes != {'RATE_LIMIT_EXCEEDED'},
                              code=next(iter(sorted(codes)), ''))
        if not isinstance(body.get('data'), dict):
            raise BufferError('Buffer no devolvió datos GraphQL válidos', uncertain=mutation)
        self._check_errors(body['data'])
        return body['data']

    @classmethod
    def _check_errors(cls, value):
        if isinstance(value, dict):
            kind = value.get('__typename', '')
            if kind == 'MutationError' or kind.endswith('Error'):
                transient = kind in ('UnexpectedError', 'LimitReachedError', 'RestProxyError')
                uncertain = kind in ('UnexpectedError', 'RestProxyError')
                raise BufferError(f'Buffer rechazó la operación ({kind})', retryable=transient,
                                  uncertain=uncertain, code=kind)
            for child in value.values():
                cls._check_errors(child)
        elif isinstance(value, list):
            for child in value:
                cls._check_errors(child)

    def account(self):
        return self.execute(ACCOUNT)['account']

    def channels(self, organization_id):
        return self.execute(CHANNELS, {'organizationId': organization_id})['channels']

    def posts(self, organization_id, channel_ids, statuses=None):
        filter_value = {'channelIds': channel_ids}
        if statuses:
            filter_value['status'] = statuses
        after, seen, result = None, set(), []
        while True:
            connection = self.execute(POSTS, {'input': {'organizationId': organization_id,
                                      'filter': filter_value}, 'after': after})['posts']
            result.extend(edge['node'] for edge in connection['edges'])
            info = connection['pageInfo']
            if not info['hasNextPage']:
                return result
            after = info['endCursor']
            if not after or after in seen:
                raise BufferError('Paginación Buffer incompleta; no se calculará capacidad')
            seen.add(after)

    def posts_by_ids(self, ids):
        result = []
        ids = list(dict.fromkeys(ids))
        for start in range(0, len(ids), 30):
            batch = ids[start:start + 30]
            variables = {f'id{i}': value for i, value in enumerate(batch)}
            declarations = ', '.join(f'$id{i}: PostId!' for i in range(len(batch)))
            fields = '\n'.join(f'p{i}: post(input: {{id: $id{i}}}) {{ {POST_FIELDS} }}' for i in range(len(batch)))
            data = self.execute(f'query Reconcile({declarations}) {{ {fields} }}', variables)
            if len(data) != len(batch) or any(not value for value in data.values()):
                raise BufferError('No se pudieron reconciliar todos los IDs; no se borrarán medios')
            result.extend(data.values())
        return result

    def create_post(self, input_value):
        payload = self.execute(CREATE, {'input': input_value}, mutation=True)['createPost']
        if payload.get('__typename') != 'PostActionSuccess' or not payload.get('post', {}).get('id'):
            raise BufferError('Buffer no confirmó el ID de creación', uncertain=True)
        return payload['post']

    def reschedule(self, post_id, due_at):
        payload = self.execute(EDIT, {'input': {'id': post_id, 'mode': 'customScheduled',
                              'dueAt': due_at, 'schedulingType': 'automatic'}}, mutation=True)['editPost']
        if payload.get('__typename') != 'PostActionSuccess' or not payload.get('post', {}).get('id'):
            raise BufferError('Buffer no confirmó la corrección de fecha', uncertain=True)
        return payload['post']

    def retry_post(self, post_id):
        payload = self.execute(EDIT, {'input': {'id': post_id, 'mode': 'addToQueue',
                              'schedulingType': 'automatic'}}, mutation=True)['editPost']
        if payload.get('__typename') != 'PostActionSuccess' or payload.get('post', {}).get('id') != post_id:
            raise BufferError('Buffer no confirmó el reintento del mismo post', uncertain=True)
        return payload['post']
