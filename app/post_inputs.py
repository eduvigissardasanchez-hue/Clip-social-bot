from .captions import Captions


def post_input(platform, channel_id, captions: Captions, url, thumbnail_offset_ms=2000):
    video = {'url': url}
    if platform in ('instagram', 'tiktok'):
        video['metadata'] = {'thumbnailOffset': thumbnail_offset_ms}
    texts = {'youtube': captions.youtube_description, 'instagram': captions.instagram_caption,
             'tiktok': captions.tiktok_caption}
    text = texts[platform]
    size = len(text.encode('utf-16-le')) // 2
    if platform == 'instagram':
        size += text.count('\n')
    limits = {'youtube': 5000, 'instagram': 2196, 'tiktok': 2200}
    if size > limits[platform]:
        raise ValueError(f'{platform}: descripción demasiado larga; corrige el sidecar.')
    if not captions.youtube_title.strip() or len(captions.youtube_title.encode('utf-16-le')) // 2 > 100:
        raise ValueError('El título de YouTube debe tener entre 1 y 100 unidades UTF-16.')
    metadata = {
        'youtube': {'title': captions.youtube_title, 'categoryId': '20', 'madeForKids': False,
                    'privacy': 'public', 'isAiGenerated': captions.ai_generated},
        'instagram': {'type': 'reel', 'shouldShareToFeed': True, 'isAiGenerated': captions.ai_generated},
        'tiktok': {'isAiGenerated': captions.ai_generated},
    }
    return {'channelId': channel_id, 'text': text, 'schedulingType': 'automatic', 'mode': 'addToQueue',
            'assets': [{'video': video}], 'metadata': {platform: metadata[platform]}}
