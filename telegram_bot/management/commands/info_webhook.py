from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from telegram_bot import api


class Command(BaseCommand):
    help = 'Mostra o estado do webhook no Telegram (URL, pendentes e último erro). Nunca mostra o token.'

    def handle(self, *args, **options):
        try:
            info = api.info_webhook()
        except api.ErroTelegram as erro:
            raise CommandError(str(erro)) from None
        self.stdout.write(f"URL: {info.get('url') or '(nenhuma)'}")
        self.stdout.write(f"Atualizações pendentes: {info.get('pending_update_count', 0)}")
        self.stdout.write(f"Tipos assinados: {', '.join(info.get('allowed_updates') or ['(padrão)'])}")
        if info.get('last_error_message'):
            quando = datetime.fromtimestamp(info.get('last_error_date', 0), tz=timezone.utc)
            self.stdout.write(self.style.WARNING(
                f"Último erro ({quando:%d/%m/%Y %H:%M} UTC): {api.sanitizar(info['last_error_message'])}"))
        else:
            self.stdout.write(self.style.SUCCESS('Nenhum erro de entrega registrado.'))
