# Clips Social Bot — Buffer

Proyecto nuevo para Windows 10/11 y Python 3.11+. Publica YouTube, Instagram y
TikTok exclusivamente mediante la API GraphQL de Buffer, usando Cloudflare R2
para los vídeos. Sin bots anteriores, OAuth propio, APIs directas de redes ni Docker.

El desarrollo de las siete fases está implementado y probado con mocks. **Aún
faltan pruebas reales con tu cuenta Buffer/R2 y la instalación en Windows**.
Mantén `DRY_RUN=true` hasta completar las pruebas iniciales. Consulta
[el estado y las limitaciones](docs/ESTADO_IMPLEMENTACION.md).

## 1. Instalación en Windows

1. Instala Python 3.11 o superior incluyendo el launcher `py`.
2. Descarga el proyecto a una carpeta permanente, por ejemplo `C:\ClipsSocialBot`.
3. Haz doble clic en `CONFIGURAR.bat`. Crea `.venv`, instala con
   `.venv\Scripts\python.exe -m pip`, crea carpetas y copia `.env.example` a `.env`
   **solo si no existe**. No utiliza `pip.exe`, para evitar el bloqueo de Device Guard.
4. Edita `.env` localmente. Nunca pegues sus valores en el chat ni los subas a Git.
5. Opcionalmente verifica la instalación:
   `.venv\Scripts\python.exe -m pytest -q`.

Si Windows bloquea Python o el Programador de tareas por una política corporativa,
solicita permiso al administrador para esas herramientas. El proyecto no cambia
Device Guard ni la política de ejecución de PowerShell.

## 2. Configurar Buffer

Conecta previamente un canal YouTube, uno Instagram y uno TikTok a tu cuenta.
Cada canal debe tener autopublicación activa, sin bloqueos, desconexiones ni cola
pausada. TikTok configurado para recordatorios produce un error explícito: no
hay fallback a notification publishing.

Configura **en Buffer** las tres colas con `10:00` y `22:00` todos los días,
sin pausas y con la misma zona horaria. El bot lee y valida esos calendarios;
no calcula un calendario propio. Comprueba también que las publicaciones ya
programadas tengan los mismos turnos en las tres redes. Antes de una carga
masiva conviene no modificar manualmente las colas durante la ejecución.

Crea una API key personal en [Buffer Settings → API](https://publish.buffer.com/settings/api).
Guárdala en `BUFFER_API_KEY` dentro de `.env` y ejecuta `PROBAR_BUFFER.bat`.
El diagnóstico valida la clave, lista organizaciones/canales y comprueba
conexión, autopublicación y calendarios, **sin publicar**.

Si hay varias organizaciones, el comando las muestra y exige
`BUFFER_ORGANIZATION_ID`. Si hay varios canales de una plataforma, exige su
`BUFFER_YOUTUBE_CHANNEL_ID`, `BUFFER_INSTAGRAM_CHANNEL_ID` o
`BUFFER_TIKTOK_CHANNEL_ID`. No se elige un canal arbitrariamente.
Con una única organización y un canal por plataforma, deja esos IDs vacíos.
No necesitas credenciales propias de YouTube, Instagram ni TikTok.

## 3. Configurar Cloudflare R2

Crea un bucket dedicado a los medios del bot. Genera credenciales compatibles
con S3, limitadas al bucket y con permisos de lectura, escritura y borrado.
Activa acceso público mediante un dominio HTTPS estable. Usa un dominio propio
para uso continuado; el endpoint S3 privado no es una URL pública de vídeo.

Completa en `.env`:

| Variable | Valor |
| --- | --- |
| `BUFFER_API_KEY` | Clave personal Buffer |
| `R2_ACCOUNT_ID` | Identificador de cuenta Cloudflare |
| `R2_ACCESS_KEY_ID` | Access key S3 de R2 |
| `R2_SECRET_ACCESS_KEY` | Secret key S3 de R2 |
| `R2_BUCKET` | Nombre del bucket |
| `R2_PUBLIC_BASE_URL` | Base HTTPS pública, sin query, contraseña ni firma temporal |
| `DRY_RUN` | `true` inicialmente; `false` para operar de verdad |
| `BUFFER_CHANNEL_CAPACITY` | `10` para Free; rango admitido 1–10 |
| `THUMBNAIL_OFFSET_MS` | `2000` por defecto, para Instagram y TikTok |
| `MAX_ATTEMPTS` | `5`, máximo de intentos antes de revisión manual |
| `R2_MAX_STORAGE_BYTES` | `8000000000`: tope preventivo de 8 GB decimales en este bucket |
| `R2_MAX_CLASS_A_OPERATIONS` | `100000`: solicitudes del bot en una ventana conservadora de 32 días |
| `R2_MAX_CLASS_B_OPERATIONS` | `1000000`: solicitudes del bot en esa ventana |

Los MP4 deben seguir accesibles hasta que las tres publicaciones estén `sent`.
No configures reglas de expiración que borren objetos `clips/` pendientes.
No uses URLs firmadas, páginas de vista previa, redirecciones ni autenticación
para el dominio público. El bot realiza un GET público y verifica que el
archivo sea accesible y tenga tipo MP4.

Ejecuta `PROBAR_STORAGE.bat`. Con `DRY_RUN=true` solo verifica acceso al bucket;
para comprobar subida/HTTPS/borrado, cambia a `DRY_RUN=false` y vuelve a ejecutarlo.
La prueba utiliza un pequeño TXT temporal bajo `diagnostics/`, comprueba su
contenido público y lo elimina incluso tras un resultado de subida incierto.
No utiliza ni borra tus clips. Después puedes volver a activar dry run.

### Protección del consumo R2 y alcance

La cuota gratuita de Cloudflare Standard incluye 10 GB-mes, 1 millón de operaciones
A y 10 millones B. El bot **no representa un límite de facturación de la cuenta**.
Sus protecciones, activas por defecto incluso sin añadir variables al .env antiguo,
son más conservadoras:

- Antes de cada subida nueva lista **todo el bucket**, con todas sus páginas,
  suma sus objetos y comprueba que el archivo no superará 8 GB ocupados.
  Incluye objetos ajenos al bot dentro de ese bucket. Si no puede medirlo o
  hay subidas multipart incompletas, no sube. No borra objetos desconocidos.
- Envía los objetos explícitamente como `STANDARD`; evita Infrequent Access,
  que no tiene cuota gratuita y cobra también recuperación. Bloquea subidas
  si encuentra objetos de otra clase.
- Usa subidas PUT únicas (máximo conservador de 5 GB por archivo) y no crea
  multipart pendientes. Las solicitudes SDK no se reintentan internamente;
  los fallos temporales se reanudan con el backoff controlado del bot.
- Cuenta antes de cada solicitud del bot, incluso si termina fallando, y
  persiste el consumo en `data/r2_usage.db`. Detiene solicitudes A/B al llegar
  a sus topes preventivos. Cuenta los GET públicos de diagnóstico también.
  Los borrados son gratuitos según Cloudflare y se permiten al agotar topes.
- Cuando falta espacio, muestra `AVISO`, registra el motivo en SQLite/logs,
  conserva el clip local y no crea posts. El mantenimiento volverá a medir
  después de limpiar los medios de clips publicados; el límite no se amplía.
  `VER_ESTADO` muestra estos avisos. No borres `data/r2_usage.db`.

**Lo que no puede controlar:** otros buckets/aplicaciones, uso previo a instalar
esta versión, escrituras externas concurrentes y GET que hagan Buffer u otros
visitantes de la URL pública. Los contadores son locales, no los de facturación
de Cloudflare. Mantén un bucket y credenciales dedicados al bot, no compartas el
acceso público y revisa el consumo total en el panel R2. No garantiza coste cero.
La cuota de almacenamiento se calcula promediando los picos diarios del periodo:
permanecer por debajo de 8 GB en un bucket dedicado deja margen, pero borrar
objetos no elimina consumo ya facturado ni el de otros servicios.

Fuentes consultadas el 9 de octubre de 2026:
[precios R2](https://developers.cloudflare.com/r2/pricing/) y
[compatibilidad S3](https://developers.cloudflare.com/r2/api/s3/api/).

### Actualizar una descarga anterior

Descarga el ZIP actual de GitHub y copia los archivos de programa sobre tu carpeta
actual. **Conserva `.env`, `data/`, tus vídeos/sidecars en `pendientes/`, `publicados/`, `errores/` y logs**;
no borres bases de datos ni sustituyas tu `.env` por la plantilla. Ejecuta
`CONFIGURAR.bat` otra vez: respetará el `.env` existente. Los límites anteriores
se aplican automáticamente aunque tu `.env` aún no tenga sus tres variables.
Copia también `pendientes/_default.json` si quieres la descripción compartida y
no tienes ya una versión personalizada; no sobrescribas tu descripción sin revisarla.

## 4. Preparar clips y descripciones

Pon MP4 en `pendientes`, preferiblemente:

```text
001_clip.mp4
001_clip.json
002_otro_clip.mp4
002_otro_clip.txt
```

Se procesan alfabéticamente, sin distinguir mayúsculas. El SHA-256 del contenido
es la identidad: dos nombres con el mismo contenido no crean dos clips, y un
archivo nuevo con el mismo nombre pero otro contenido es un clip distinto.
No renombres ni cambies archivos ya registrados; se comprueba el hash antes de
subir y archivar. Las copias duplicadas omitidas por el scanner permanecen locales.

Para `clip.mp4` se prefiere `clip.json`:

```json
{
  "caption": "Texto general",
  "youtube_title": "Título del vídeo",
  "youtube_description": "Descripción opcional",
  "instagram_caption": "Texto para Instagram",
  "tiktok_caption": "Texto para TikTok",
  "ai_generated": false
}
```

Si no hay JSON, se lee `clip.txt` como caption general. Si tampoco hay TXT,
se usa **`pendientes/_default.json`**, compartido por todos los clips que no tengan
sidecar propio. Incluye tu descripción general y omite `youtube_title` para que
cada clip conserve un título generado de su nombre. El ajuste local
`title_from_filename: true` usa el nombre exacto del MP4 sin extensión como título
YouTube (conserva prefijos y guiones bajos), y lo añade como primera línea de los
captions Instagram/TikTok: Buffer no expone un título de vídeo separado en esas
dos plataformas. La descripción común de YouTube permanece sin esa primera línea.
Esta opción es del bot, no un campo que se envíe a Buffer. El archivo distribuido contiene
la descripción de redes de Honnoe y se puede editar localmente. No hace falta
copiarlo ni renombrarlo para cada vídeo. No se mueve a `publicados` al limpiar clips.

La prioridad es: `clip.json` → `clip.txt` → `_default.json` → nombre del archivo.
Un JSON o TXT específico sustituye por completo la descripción compartida.
Sin ninguna descripción se usa el nombre quitando prefijos numéricos y guiones bajos. El título de YouTube sale de
`youtube_title` o del nombre del clip; el TXT general no sustituye ese título.
No se usa IA externa ni se añade `#shorts` automáticamente.

YouTube usa Gaming (`categoryId="20"`), `madeForKids=false` y `privacy=public`.
Instagram usa Reel con `shouldShareToFeed=true`. TikTok solo usa la metadata
publicada por Buffer, sin ajustes de privacidad inventados.

`ESCANEAR_CLIPS.bat` permite validar sidecars y orden. En dry run no guarda nada;
con `DRY_RUN=false` registra los clips en SQLite. Las descripciones quedan
congeladas al preparar la primera publicación para que una carga parcial pueda
continuar con el mismo contenido.

## 5. Dry run y primera publicación

Con `DRY_RUN=true`, `PROGRAMAR_TODO.bat` calcula orden/hashes, valida captions,
consulta Buffer, comprueba capacidad/coherencia y acceso de lectura al bucket,
y muestra URLs previstas y acciones. **No sube, crea, edita, borra o mueve medios,
ni modifica SQLite o logs.** Una URL prevista para un clip todavía no subido no
puede validarse públicamente; la prueba real de R2 cubre esa parte.

Para una prueba real:

1. Completa `PROBAR_BUFFER` y la prueba real de `PROBAR_STORAGE`.
2. Introduce al menos un MP4 y su sidecar.
3. Pon `DRY_RUN=false` y ejecuta `PROBAR_PUBLICACION.bat`.
4. Revisa archivo, hash, canales, textos, metadata, URL pública prevista y acciones.
5. Escribe `PROGRAMAR` para confirmar. Solo se programa **un clip nuevo** en las
   tres redes. Cualquier otra respuesta cancela sin subir ni crear publicaciones.
6. Comprueba las fechas y formato en Buffer antes de la carga masiva.

Si el contenido, URL o canales cambian tras la vista previa, no se publica el
plan cambiado. Los posts existentes y las creaciones inciertas se excluyen de
esta prueba; para continuarlos usa el mantenimiento.

## 6. Programación masiva

Con las pruebas anteriores completadas y `DRY_RUN=false`, ejecuta
`PROGRAMAR_TODO.bat` una vez. El bot registra todos los clips, sube cada contenido
una sola vez y reutiliza su URL en las tres redes. Usa `schedulingType=automatic`
y `mode=addToQueue`: Buffer asigna los siguientes huecos de su calendario.

La capacidad conjunta es el mínimo espacio libre de las tres colas, contando
posts programados y en envío. Con 40 clips y tres colas vacías Free programa
10 clips completos y conserva 30 en SQLite. Ejecutarlo de nuevo no recrea
posts que ya tengan ID. Si hay un fallo parcial, solo se intenta la plataforma
pendiente y no se adelanta el siguiente clip hasta resolverla.

Si las fechas del mismo clip difieren más de cinco minutos, se corrigen usando
una fecha que Buffer ya asignó a ese clip, mediante `customScheduled`. También
puede usarse para completar un turno pendiente de un clip parcial. No se
inventa un calendario y no se pisa un turno ocupado. Una cola ajena al bot
con distinta longitud/fechas exige revisión en Buffer antes de seguir.

## 7. Mantenimiento automático en Windows

Ejecuta `INSTALAR_TAREA_WINDOWS.bat` desde la carpeta definitiva. El instalador
usa Python y `schtasks.exe` con una definición XML; no ejecuta scripts PowerShell
ni cambia su política de ejecución. Registra y verifica la
tarea `ClipsSocialBotBuffer` para ejecutarse diariamente a las **03:15**, antes
del primer turno, y un minuto después de iniciar sesión. Activa `StartWhenAvailable` para recuperar
una ejecución perdida. La tarea usa `.venv\Scripts\pythonw.exe`, sin ventana
permanente, y conserva los resultados en `logs\bot.log`.

La comprobación interpreta los valores predeterminados que Windows puede omitir
al exportar la tarea. Si encuentra un ajuste incompatible, muestra el nombre del
campo y su valor. `StartWhenAvailable` debe estar activado explícitamente.

La tarea usa tu sesión interactiva y no guarda contraseñas. Si Windows está
apagado, suspendido o sin tu sesión, el mantenimiento se realizará cuando
vuelvas e inicies sesión. Los posts ya programados los publica Buffer aunque
tu PC esté apagado; el relleno de la cola local requiere este PC disponible.
No cambies la carpeta tras instalarla: si la mueves, desinstala y reinstala.

`MANTENER_COLA.bat` también permite ejecutar el mantenimiento manualmente.
Consulta posts existentes, reconcilia estados, detecta huecos y rellena las
colas. Los IDs activos se consultan en lotes de hasta 30 y los posts se paginan;
no se consulta historial completo salvo una creación incierta. Los errores
recuperables usan backoff persistente y un límite de intentos.

Solo cuando las tres redes están `sent`, se elimina el MP4 de R2 y se mueve el
vídeo y sus sidecars a `publicados`. Si alguna está en error, se conserva el
medio remoto. La limpieza se puede reanudar sin recrear posts. Una colisión en
`publicados` detiene el archivado para evitar sobrescrituras.

Para desinstalar la tarea, ejecuta en el Símbolo del sistema bajo el mismo usuario:

```bat
schtasks /Delete /TN "ClipsSocialBotBuffer" /F
```

También puedes eliminarla desde el Programador de tareas de Windows. Esto no
borra clips, SQLite, R2 ni publicaciones en Buffer.

## Estado, logs y recuperación

`VER_ESTADO.bat` muestra estados por plataforma y los totales publicados,
programados, locales y en error. Es una lectura de SQLite, no una sincronización:
ejecuta mantenimiento primero para refrescar estados. `logs\bot.log` tiene
rotación y oculta los tres secretos; no incluye headers ni respuestas crudas.

Conserva `data/bot.db` y haz copias de seguridad antes de migrar o borrar datos.
Sin esa base se pierde la referencia de los IDs y no se puede garantizar que no
se dupliquen publicaciones. No cambies IDs o estados manualmente.

- **Error de validación:** corrige el sidecar/configuración o el post en Buffer.
  No se reintenta indefinidamente. Después puedes autorizar un reintento:
  `.venv\Scripts\python.exe main.py retry-errors --hash SHA256 --platform instagram`.
  Exige escribir `REINTENTAR`, conserva el ID si existe y solo reprograma ese
  mismo post. Para clips sin ID permite releer el sidecar corregido.
- **Fallo temporal de publicación:** cuando Buffer informa claramente de un
  fallo temporal, el mantenimiento reprograma el **mismo ID**, con intentos
  limitados. Errores no reconocidos requieren revisión manual.
- **Timeout al crear:** el resultado queda marcado incierto. Se busca un post
  del mismo canal con el mismo asset público para recuperarlo. Nunca se
  vuelve a crear automáticamente si no se puede confirmar el resultado.
  Si tras revisar Buffer confirmas que el post NO existe, ejecuta
  `.venv\Scripts\python.exe main.py resolve-uncertain --hash SHA256 --platform youtube`.
  Exige escribir `AUSENTE` antes de autorizar otra creación.
- **Clip parcial cuyo turno ya pasó:** ajusta sus posts existentes en Buffer a
  un turno futuro coherente y vuelve a ejecutar mantenimiento. No se crean
  duplicados ni se publica silenciosamente en otro turno.
- **Clave incorrecta o permisos:** completa las variables localmente y prueba
  de nuevo el diagnóstico. No compartas `.env` ni capturas con secretos.

No existe una transacción atómica entre tres canales, R2 y SQLite. El bot guarda
la intención antes de crear y prioriza evitar duplicados frente a repetir una
mutación de resultado incierto. Dos ejecuciones locales simultáneas se bloquean.
Las modificaciones manuales en Buffer durante un lote pueden requerir revisión.

## Desarrollo y documentación oficial

```bat
.venv\Scripts\python.exe -m pytest -q
```

En Linux usa `.venv/bin/python`. Los tests simulan Buffer y R2, incluyendo
capacidad Free, rellenado, fallos parciales, resultados inciertos, limpieza y dry run.
Las operaciones GraphQL y metadata se validan además contra una copia del
esquema derivada de la [referencia oficial](https://developers.buffer.com/reference.md)
consultada el 9 de octubre de 2026. No es una introspección autenticada ni una
prueba de que tu cuenta tenga los permisos o formatos necesarios.

Fuentes: [autenticación](https://developers.buffer.com/guides/authentication.md),
[programación](https://developers.buffer.com/guides/posts-and-scheduling.md),
[vídeos](https://developers.buffer.com/examples/create-video-post.md),
[medios públicos](https://developers.buffer.com/guides/hosting-media.md),
[errores](https://developers.buffer.com/guides/error-handling.md) y
[límites](https://developers.buffer.com/guides/api-limits.md).
