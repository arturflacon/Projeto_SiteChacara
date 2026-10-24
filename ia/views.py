from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView, UpdateView
from django_filters.views import FilterView

from website.views import AdminRequiredMixin

from . import services
from .filters import RequisicaoIAFilter
from .forms import ConfiguracaoIAForm, PerfilIAUsuarioForm
from .models import ConfiguracaoIA, PerfilIAUsuario, RequisicaoIA


class RequisicoesListView(AdminRequiredMixin, FilterView):
    """Auditoria: toda chamada à IA, com filtros e paginação."""
    model = RequisicaoIA
    template_name = 'ia/requisicao_list.html'
    context_object_name = 'requisicoes'
    filterset_class = RequisicaoIAFilter
    paginate_by = 20
    ordering = ['-criado_em']

    def get_queryset(self):
        # select_related('usuario'): a tabela mostra o login; sem isto seria
        # 1 consulta ao User por linha.
        return super().get_queryset().select_related('usuario')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Resumo sobre o resultado do filtro (todas as páginas), numa consulta só.
        totais = self.object_list.order_by().aggregate(
            chamadas=Count('id'),
            erros=Count('id', filter=Q(sucesso=False)),
            entrada=Coalesce(Sum('tokens_entrada'), 0),
            saida=Coalesce(Sum('tokens_saida'), 0),
            total=Coalesce(Sum('tokens_total'), 0),
        )
        custo = (Decimal(totais['entrada']) * Decimal(str(settings.GEMINI_PRECO_ENTRADA_USD))
                 + Decimal(totais['saida']) * Decimal(str(settings.GEMINI_PRECO_SAIDA_USD)))
        totais['custo_usd'] = custo
        totais['custo_brl'] = custo * Decimal(str(settings.GEMINI_COTACAO_BRL))
        ctx['totais'] = totais
        return ctx


class RequisicaoDetailView(AdminRequiredMixin, DetailView):
    model = RequisicaoIA
    template_name = 'ia/requisicao_detail.html'
    context_object_name = 'requisicao'

    def get_queryset(self):
        return RequisicaoIA.objects.select_related('usuario')


class ConfiguracaoIAUpdateView(AdminRequiredMixin, SuccessMessageMixin, UpdateView):
    """Edita o singleton. A chave da API não é editável aqui (vem do ambiente)."""
    model = ConfiguracaoIA
    form_class = ConfiguracaoIAForm
    template_name = 'ia/configuracao_form.html'
    success_url = reverse_lazy('ia:configuracao')
    success_message = 'Configuração da IA salva (modelo %(modelo)s).'

    def get_object(self, queryset=None):
        return ConfiguracaoIA.obter()

    def form_valid(self, form):
        form.instance.atualizado_por = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['chave_configurada'] = services.chave_configurada()  # só sim/não, nunca o valor
        return ctx


class TestarConexaoView(AdminRequiredMixin, View):
    """Botão "Testar conexão": chamada mínima ao provedor, resultado em messages."""
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        try:
            resposta = services.testar_conexao(request.user)
        except services.ErroIA as erro:
            messages.error(request, f'Teste não realizado: {erro}')
        else:
            requisicao = RequisicaoIA.objects.get(pk=resposta.requisicao_id)
            if resposta.sucesso:
                messages.success(
                    request,
                    f'Conexão OK: o modelo {requisicao.modelo} respondeu em {requisicao.duracao_ms} ms '
                    f'({requisicao.tokens_total} tokens).')
            else:
                messages.error(
                    request, f'Falha na conexão com o provedor. Detalhes na requisição #{requisicao.pk}.')
        return redirect('ia:configuracao')


class UsuariosIAListView(AdminRequiredMixin, ListView):
    """IA por usuário: habilitação, cota efetiva e consumo do mês.

    Uma única consulta com annotate (consumo do mês, habilitado e cota), em
    vez de consumo_do_mes() e cota_do_usuario() por linha. Sem paginação no
    servidor: a tabela usa DataTables (busca/ordenação no navegador).
    """
    model = User
    template_name = 'ia/usuarios_ia.html'
    context_object_name = 'usuarios'

    @cached_property
    def config(self):
        return ConfiguracaoIA.obter()

    def get_queryset(self):
        config = self.config
        do_mes = Q(
            requisicoes_ia__criado_em__gte=services.inicio_do_mes(),
            requisicoes_ia__origem__in=services.ORIGENS_COM_COTA,
        )
        return (
            User.objects
            .select_related('cliente', 'administrador')
            .annotate(
                consumo_mes=Coalesce(Sum('requisicoes_ia__tokens_total', filter=do_mes), 0),
                ia_habilitada=Coalesce('perfil_ia__habilitado', Value(True)),
                cota_efetiva=Coalesce('perfil_ia__cota_mensal_tokens', Value(config.cota_mensal_padrao_tokens)),
                cota_propria=Coalesce('perfil_ia__cota_mensal_tokens', Value(0)),
            )
            .order_by('username')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['config'] = self.config
        return ctx


class PerfilIAUsuarioUpdateView(AdminRequiredMixin, SuccessMessageMixin, UpdateView):
    """Edita habilitação e cota de um usuário (cria o perfil na primeira vez)."""
    model = PerfilIAUsuario
    form_class = PerfilIAUsuarioForm
    template_name = 'ia/perfil_ia_form.html'
    success_url = reverse_lazy('ia:usuarios')

    def get_object(self, queryset=None):
        usuario = get_object_or_404(User, pk=self.kwargs['usuario_id'])
        perfil, _ = PerfilIAUsuario.objects.get_or_create(usuario=usuario)
        return perfil

    def get_success_message(self, cleaned_data):
        return f'Uso da IA de {self.object.usuario.username} atualizado.'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['config'] = ConfiguracaoIA.obter()
        ctx['consumo'] = services.consumo_do_mes(self.object.usuario)
        return ctx


class MeuConsumoView(LoginRequiredMixin, TemplateView):
    """Consumo de IA do próprio usuário: só os dados dele."""
    template_name = 'ia/meu_consumo.html'
    ULTIMAS = 10

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuario = self.request.user
        config = ConfiguracaoIA.obter()
        perfil = services.perfil_ia(usuario)  # uma consulta, usada para cota e habilitação
        consumo = services.consumo_do_mes(usuario)
        cota = services.cota_do_usuario(usuario, config, perfil)
        ctx.update(
            consumo=consumo,
            cota=cota,
            restante=max(cota - consumo, 0),
            percentual=min(100, round(consumo * 100 / cota)) if cota else 100,
            habilitado=services.usuario_habilitado(usuario, perfil),
            ia_disponivel=services.ia_disponivel(config),
            ultimas=(
                RequisicaoIA.objects
                .filter(usuario=usuario, origem__in=services.ORIGENS_COM_COTA)
                .order_by('-criado_em')[:self.ULTIMAS]
            ),
        )
        return ctx
