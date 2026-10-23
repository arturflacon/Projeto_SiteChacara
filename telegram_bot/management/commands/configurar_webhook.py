from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from telegram_bot import api


class Command(BaseCommand):
    help = ('Registra no Telegram a URL do webhook com o segredo do ambiente '
            '(TELEGRAM_WEBHOOK_SECRET) e allowed_updates=["message", "callback_query"].')

    def add_arguments(self, parser):
        parser.add_argument('--url', required=True,
                            help='URL pública HTTPS, ex.: https://<projeto>.appspot.com/telegram/webhook/')

    def handle(self, *args, url, **options):
        if not url.startswith('https://'):
            raise CommandError('O Telegram só aceita webhook em HTTPS.')
        if not url.rstrip('/').endswith('/telegram/webhook'):
            raise CommandError('A URL deve terminar em /telegram/webhook/.')
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError('Defina TELEGRAM_BOT_TOKEN e TELEGRAM_WEBHOOK_SECRET no ambiente (.env).')
        try:
            api.configurar_webhook(url, settings.TELEGRAM_WEBHOOK_SECRET)
        except api.ErroTelegram as erro:
            raise CommandError(str(erro)) from None
        self.stdout.write(self.style.SUCCESS(f'Webhook configurado para {url} (segredo enviado, não exibido).'))
