from django.core.management.base import BaseCommand, CommandError

from telegram_bot import api


class Command(BaseCommand):
    help = 'Remove o webhook do bot no Telegram.'

    def add_arguments(self, parser):
        parser.add_argument('--descartar-pendentes', action='store_true',
                            help='Descarta também as atualizações ainda não entregues.')

    def handle(self, *args, descartar_pendentes=False, **options):
        try:
            api.remover_webhook(descartar_pendentes)
        except api.ErroTelegram as erro:
            raise CommandError(str(erro)) from None
        self.stdout.write(self.style.SUCCESS('Webhook removido.'))
