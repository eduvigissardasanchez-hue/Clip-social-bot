# Estado de implementación — 9 de octubre de 2026

## Implementado

1. Estructura, .env.example, configuración, SQLite y migraciones aditivas,
   scanner SHA-256, orden alfabético, captions JSON/TXT/fallback y estados.
2. Cliente Buffer GraphQL y diagnóstico de cuenta, organizaciones, canales,
   selección explícita ante ambigüedad, calendarios y autopublicación.
3. Abstracción StorageProvider, R2/S3 con boto3, URL HTTPS estable, acceso público,
   subida reutilizable por hash y diagnóstico temporal de subida/GET/borrado.
4. Prueba de un solo clip nuevo, con vista previa y confirmación PROGRAMAR.
5. Programación masiva y capacidad Free mínima de los tres canales, cola SQLite,
   intención persistida antes de mutar, recuperación de resultados inciertos.
6. Reconciliación de IDs y estados, reposición, retries limitados/backoff,
   conservación de medios ante errores y limpieza/archivado tras tres sent.
7. Instalador Windows mediante PowerShell ScheduledTasks: diario + inicio de
   sesión, StartWhenAvailable, pythonw, sin consola ni contraseñas guardadas.

## Evidencia y límites

- Documentación oficial accesible por HTTPS; api.buffer.com responde 401 sin clave.
- Contrato consultado: https://developers.buffer.com/reference.md y guías enlazadas
  en README. Extractos en BUFFER_SCHEMA.md y schema derivado para tests.
- Tests con mocks, sin API real; todos pasan (consulta pytest para el conteo actual).
- No hay credenciales reales ni .env incluidos. No se han creado posts ni subido
  medios reales. Las claves se introducen localmente en .env.
- Windows y su Programador de tareas no se han ejecutado en esta máquina Linux.
- No se puede garantizar un turno idéntico si alguien cambia las colas durante
  una carga. Las desalineaciones detectadas se corrigen solo a fechas asignadas
  por Buffer; conflictos/turnos vencidos exigen revisión.
- Buffer no documenta una clave de idempotencia de createPost en este esquema:
  las respuestas inciertas se recuperan por canal + asset o requieren revisión,
  sin repetir ciegamente. No borres SQLite.
- Diagnóstico storage en dry run solo prueba lectura del bucket; las URLs previstas
  aún no subidas no pueden comprobarse públicamente hasta la prueba real.

## Siguiente validación en tu PC

CONFIGURAR → completar .env → PROBAR_BUFFER → PROBAR_STORAGE (DRY_RUN=false) →
PROBAR_PUBLICACION (confirmación) → revisar Buffer → PROGRAMAR_TODO →
INSTALAR_TAREA_WINDOWS. No se ha ejecutado esta secuencia real por ti.
