import logging
from logging.handlers import RotatingFileHandler


def output(config):
    logger = logging.getLogger('clips_social_bot')
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    if not config.dry_run:
        folder = config.root / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / 'bot.log', maxBytes=2_000_000,
                                      backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    else:
        logger.addHandler(logging.NullHandler())
    secrets = [config.buffer_api_key, config.r2_access_key_id, config.r2_secret_access_key]

    def emit(message):
        text = str(message)
        for secret in secrets:
            if secret:
                text = text.replace(secret, '[SECRETO OCULTO]')
        print(text)
        logger.info(text)
    return emit
