import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from ia import services as ia_services
from ia.excecoes import CotaExcedida, IADesativada

from . import services
from .formatacao import renderizar


class ConversaView(LoginRequiredMixin, TemplateView):
    """Tela do assistente: histórico do próprio usuário + formulário AJAX."""
    template_name = 'assistente/conversa.html'
    ULTIMAS = 50  # o histórico completo fica no banco; a tela mostra as últimas

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ultimas = list(services.historico(self.request.user).reverse()[:self.ULTIMAS])
        ultimas.reverse()
        ctx.update(
            mensagens=ultimas,
            ia_disponivel=ia_services.ia_disponivel(),
            max_caracteres=services.MAX_CARACTERES_PERGUNTA,
            janela=services.JANELA_HISTORICO,
        )
        return ctx


class PerguntarView(LoginRequiredMixin, View):
    """POST AJAX (fetch com X-CSRFToken — sem csrf_exempt) que devolve JSON.

    A resposta vai como HTML já sanitizado (markdown + nh3); a pergunta não
    volta: o navegador já a mostrou com textContent.
    """
    http_method_names = ['post']
    raise_exception = True  # sem login: 403 (é uma API, não uma página)

    def _pergunta(self, request):
        if request.content_type == 'application/json':
            try:
                dados = json.loads(request.body or b'{}')
            except ValueError:
                return ''
            valor = dados.get('pergunta', '') if isinstance(dados, dict) else ''
            return valor if isinstance(valor, str) else ''
        return request.POST.get('pergunta', '')

    def post(self, request, *args, **kwargs):
        pergunta = self._pergunta(request).strip()
        if not pergunta:
            return JsonResponse({'erro': 'Escreva a sua pergunta.'}, status=400)
        if len(pergunta) > services.MAX_CARACTERES_PERGUNTA:
            return JsonResponse(
                {'erro': f'A pergunta pode ter no máximo {services.MAX_CARACTERES_PERGUNTA} caracteres.'},
                status=400)
        try:
            resposta = services.perguntar(request.user, pergunta)
        except CotaExcedida as erro:
            return JsonResponse({'erro': str(erro)}, status=429)
        except IADesativada as erro:
            return JsonResponse({'erro': str(erro)}, status=503)
        if not resposta.sucesso:
            return JsonResponse({'erro': resposta.erro}, status=502)
        return JsonResponse({'resposta_html': renderizar(resposta.texto)})


class LimparConversaView(LoginRequiredMixin, View):
    """Apaga o histórico do próprio usuário (confirmação com Bootbox na tela)."""
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        apagadas = services.limpar_conversa(request.user)
        if apagadas:
            messages.success(request, 'Conversa apagada. Pode começar uma nova!')
        else:
            messages.info(request, 'A conversa já estava vazia.')
        return redirect('assistente:conversa')
