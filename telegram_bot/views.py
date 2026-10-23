import hmac
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from django_filters.views import FilterView

from website.views import AdminRequiredMixin

from . import api, bot
from .filters import MensagemTelegramFilter
from .models import CodigoVinculacao, MensagemTelegram, VinculoTelegram

logger = logging.getLogger(__name__)


# csrf_exempt é NECESSÁRIO aqui: o Telegram não envia token CSRF (não é um
# navegador com sessão). A proteção desta rota é o segredo: o Telegram manda
# TELEGRAM_WEBHOOK_SECRET no cabeçalho X-Telegram-Bot-Api-Secret-Token e
# qualquer requisição sem ele (ou com outro valor) recebe 403.
@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(View):
    """Recebe os updates do Telegram (só POST)."""
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        segredo = settings.TELEGRAM_WEBHOOK_SECRET
        if not segredo or not settings.TELEGRAM_BOT_TOKEN:
            return HttpResponse('Bot não configurado.', status=503)
        recebido = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        # compare_digest: tempo constante, não revela quantos caracteres bateram.
        if not hmac.compare_digest(recebido.encode(), segredo.encode()):
            return HttpResponseForbidden('Segredo inválido.')
        try:
            update = json.loads(request.body)
            if not isinstance(update, dict):
                raise ValueError('update não é um objeto JSON')
            bot.processar_update(update)
        except Exception as erro:
            # Responde 200 mesmo assim: com erro o Telegram reenviaria o mesmo
            # update sem parar. O traceback não traz o token: api._post relança
            # as falhas do requests "from None", só com a mensagem sanitizada.
            logger.exception('Erro ao processar update do Telegram: %s', api.sanitizar(repr(erro)))
        return JsonResponse({'ok': True})


class ConectarTelegramView(LoginRequiredMixin, TemplateView):
    """Status do vínculo + código de uso único para vincular a conta ao bot."""
    template_name = 'telegram_bot/conectar.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuario = self.request.user
        codigo = (CodigoVinculacao.objects
                  .filter(usuario=usuario, usado_em__isnull=True).order_by('-criado_em').first())
        if codigo and not codigo.valido:
            codigo = None
        bot_usuario = settings.TELEGRAM_BOT_USERNAME
        ctx.update(
            vinculo=VinculoTelegram.objects.filter(usuario=usuario).first(),
            codigo=codigo,
            bot_usuario=bot_usuario,
            deep_link=f'https://t.me/{bot_usuario}?start={codigo.codigo}' if codigo and bot_usuario else '',
            bot_configurado=bool(settings.TELEGRAM_BOT_TOKEN),
            validade_minutos=settings.TELEGRAM_CODIGO_VALIDADE_MINUTOS,
        )
        return ctx


class GerarCodigoView(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        CodigoVinculacao.gerar_para(request.user)
        messages.success(
            request, f'Código gerado. Ele vale por {settings.TELEGRAM_CODIGO_VALIDADE_MINUTOS} minutos e uma única vez.')
        return redirect('telegram_bot:conectar')


class DesvincularView(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        apagados, _ = VinculoTelegram.objects.filter(usuario=request.user).delete()
        if apagados:
            messages.success(request, 'Sua conta foi desvinculada do Telegram.')
        else:
            messages.info(request, 'Sua conta não estava vinculada ao Telegram.')
        return redirect('telegram_bot:conectar')


class MensagensTelegramListView(AdminRequiredMixin, FilterView):
    """Log de entradas e saídas do bot (admin)."""
    model = MensagemTelegram
    template_name = 'telegram_bot/mensagem_list.html'
    context_object_name = 'mensagens_bot'
    filterset_class = MensagemTelegramFilter
    paginate_by = 30
    ordering = ['-criado_em', '-id']

    def get_queryset(self):
        # select_related('usuario'): a tabela mostra o login; sem isto seria 1 consulta por linha.
        return super().get_queryset().select_related('usuario')
