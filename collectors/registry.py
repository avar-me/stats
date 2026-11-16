"""Source registry.

Each class is a separate module. The runner only knows this list: to attach a
source later, add the module and set enabled: true. Existing modules stay put.
"""

from collectors.apple import AppleSource
from collectors.cloudflare import CloudflareSource
from collectors.google_play import GooglePlaySource
from collectors.telegram_bots import TelegramBotsSource
from collectors.telegram_channels import TelegramChannelsSource
from collectors.telegram_stickers import TelegramStickersSource

SOURCES = [
    TelegramChannelsSource,
    TelegramStickersSource,
    CloudflareSource,
    AppleSource,
    GooglePlaySource,
    TelegramBotsSource,
]
