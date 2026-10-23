import json
import time
from decimal import Decimal

from braces.views import GroupRequiredMixin
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView,
    TemplateView, UpdateView,
)
from django.views.generic.detail import SingleObjectMixin
from django_filters.views import FilterView

from . import ia
from . import services
from .filters import (
    MinhasReservasFilter, ReservaAdminFilter,
    ReservaConfirmadaFilter, ReservaPendenteFilter, UsoIAFilter,
)
from .forms import (
    ClienteForm, DecisaoReservaForm, ReservaAdminForm,
    ReservaClienteForm, SignupForm,
)
from .models import Administrador, Chacara, Cliente, Reserva, UsoIA
from .services import ErroRegraNegocio, usuario_eh_admin


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class AdminRequiredMixin(GroupRequiredMixin):
    """Acesso restrito à administração (django-braces).

    A regra de quem é admin (grupo 'Administradores', superuser ou perfil
    ``Administrador``) fica em ``services.usuario_eh_admin``, a mesma usada
    pelo bot do Telegram.
    """

    group_required = services.GRUPO_ADMIN
    raise_exception = False  # sem permissão -> redireciona ao login

    def check_membership(self, groups):
        return usuario_eh_admin(self.request.user)


# ---------------------------------------------------------------------------
# Páginas públicas
# ---------------------------------------------------------------------------

class IndexView(TemplateView):
    template_name = 'website/index.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['chacara'] = services.chacara_principal()
        return ctx


class SobreView(TemplateView):
    template_name = 'website/sobre.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['chacara'] = services.chacara_principal()
        return ctx


class CalendarioReservasView(FilterView):
    model = Reserva
    template_name = 'website/calendario_reservas.html'
    context_object_name = 'reservas'
    filterset_class = ReservaConfirmadaFilter
    paginate_by = 10
    ordering = ['data_inicio']

    def get_queryset(self):
        # select_related('cliente'): para o admin a tabela mostra nome e
        # telefone do cliente; sem isto seria 1 consulta ao Cliente por linha.
        return (
            super().get_queryset()
            .filter(status=Reserva.STATUS_CONFIRMADA)
            .select_related('cliente')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mostrar_cliente = usuario_eh_admin(self.request.user)
        # Eventos do FullCalendar: todas as confirmadas a partir de hoje, sem
        # paginação. O "end" do FullCalendar é exclusivo, igual à regra do
        # sistema (o dia de saída fica livre para uma nova entrada).
        # select_related('cliente'): o título do evento usa o nome do cliente
        # (só para admin); sem isto seria 1 consulta por evento.
        futuras = (
            Reserva.objects
            .filter(status=Reserva.STATUS_CONFIRMADA, data_fim__gte=timezone.localdate())
            .select_related('cliente')
            .order_by('data_inicio')
        )
        ctx['eventos'] = [
            {
                'title': f'Reservado — {r.cliente.nome}' if mostrar_cliente else 'Reservado',
                'start': r.data_inicio.isoformat(),
                'end': r.data_fim.isoformat(),
                'allDay': True,
            }
            for r in futuras
        ]
        return ctx


class ChacaraUnicaView(DetailView):
    """Exibe sempre a única chácara do sistema."""
    model = Chacara
    template_name = 'website/chacara_detail.html'
    context_object_name = 'chacara'

    def get_object(self, queryset=None):
        chacara = services.chacara_principal()
        if chacara is None:
            raise Http404('Nenhuma chácara cadastrada.')
        return chacara


# ---------------------------------------------------------------------------
# Cadastro / auth
# ---------------------------------------------------------------------------

class SignupView(SuccessMessageMixin, FormView):
    template_name = 'website/registro.html'
    form_class = SignupForm
    success_url = reverse_lazy('index')
    success_message = 'Conta criada com sucesso! Você já pode fazer seu pedido de reserva.'
    extra_context = {'titulo': 'Cadastro de Cliente', 'botao': 'Criar conta'}

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Área do cliente (autenticado)
# ---------------------------------------------------------------------------

class ReservaCreate(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Reserva
    form_class = ReservaClienteForm
    template_name = 'website/reserva_form.html'
    success_url = reverse_lazy('minhas_reservas')
    success_message = 'Pedido enviado! Aguarde a confirmação da administradora.'
    extra_context = {'titulo': 'Fazer Pedido de Reserva', 'botao': 'Enviar Pedido'}

    def dispatch(self, request, *args, **kwargs):
        # Só quem tem perfil de Cliente faz pedidos (o admin aprova/recusa).
        if request.user.is_authenticated and not hasattr(request.user, 'cliente'):
            messages.warning(
                request,
                'Apenas clientes fazem pedidos de reserva. '
                'Administradores gerenciam os pedidos recebidos.',
            )
            return redirect('pedidos_pendentes' if usuario_eh_admin(request.user) else 'index')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            self.object = services.criar_pedido_reserva(
                cliente=self.request.user.cliente,
                data_inicio=form.cleaned_data['data_inicio'],
                data_fim=form.cleaned_data['data_fim'],
                observacoes=form.cleaned_data['observacoes'],
            )
        except ErroRegraNegocio as erro:
            form.add_error(None, str(erro))
            return self.form_invalid(form)
        messages.success(self.request, self.get_success_message(form.cleaned_data))
        # O pedido já está salvo. Se a IA falhar ou estiver desligada,
        # analisar_pedido só devolve None e o fluxo segue.
        ia.analisar_pedido(self.object, usuario=self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class MinhasReservasListView(LoginRequiredMixin, FilterView):
    model = Reserva
    template_name = 'website/reserva_list.html'
    context_object_name = 'reservas'
    filterset_class = MinhasReservasFilter
    paginate_by = 10
    ordering = ['-data_pedido']

    def get_queryset(self):
        # Restrição de dono: o FilterView aplica o filtro em cima DESTE
        # queryset, então o cliente só filtra entre as próprias reservas.
        # Usuário sem perfil de cliente cai numa lista vazia.
        # select_related('chacara'): a tabela mostra chacara.nome; sem isto
        # seria 1 consulta à Chácara por linha.
        return (
            super().get_queryset()
            .filter(cliente__usuario=self.request.user)
            .select_related('chacara')
        )


class ReservaDetailView(LoginRequiredMixin, DetailView):
    model = Reserva
    template_name = 'website/reserva_detail.html'
    context_object_name = 'reserva'

    def get_queryset(self):
        """
        Cliente vê apenas suas próprias reservas.
        Admin/superuser vê qualquer reserva.
        """
        # select_related: a página mostra cliente e chácara (2 consultas a
        # menos). prefetch_related: o histórico e quem alterou cada linha
        # vêm em 2 consultas, em vez de 1 por linha do histórico.
        qs = (
            Reserva.objects
            .select_related('cliente', 'chacara')
            .prefetch_related('historico__alterado_por')
        )
        u = self.request.user
        if usuario_eh_admin(u):
            return qs
        if hasattr(u, 'cliente'):
            return qs.filter(cliente=u.cliente)
        return qs.none()


class MinhaReservaDetailView(LoginRequiredMixin, DetailView):
    """Detalhe de uma reserva restrito ao próprio cliente dono."""
    model = Reserva
    template_name = 'website/reserva_detail.html'
    context_object_name = 'reserva'

    def get_queryset(self):
        # Mesmo motivo do ReservaDetailView: cliente/chácara num JOIN e
        # histórico + usuários em 2 consultas fixas.
        return (
            Reserva.objects
            .select_related('cliente', 'chacara')
            .prefetch_related('historico__alterado_por')
            .filter(cliente__usuario=self.request.user)
        )


class MinhaReservaUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """Cliente edita o próprio pedido enquanto está PENDENTE."""
    model = Reserva
    form_class = ReservaClienteForm
    template_name = 'website/reserva_form.html'
    success_url = reverse_lazy('minhas_reservas')
    success_message = 'Pedido editado com sucesso.'
    extra_context = {'titulo': 'Editar Meu Pedido', 'botao': 'Salvar Alterações'}

    def get_queryset(self):
        return Reserva.objects.filter(
            cliente__usuario=self.request.user, status=Reserva.STATUS_PENDENTE)

    def form_valid(self, form):
        response = super().form_valid(form)
        # As observações podem ter mudado: refaz a análise. Se não der para
        # refazer, apaga a antiga para a admin não ver uma análise desatualizada.
        if ia.analisar_pedido(self.object, usuario=self.request.user) is None and self.object.analise_ia:
            self.object.analise_ia = None
            self.object.analise_ia_em = None
            self.object.save(update_fields=['analise_ia', 'analise_ia_em'])
        return response


class MinhaReservaDeleteView(LoginRequiredMixin, SuccessMessageMixin, DeleteView):
    """Cliente cancela o próprio pedido enquanto está PENDENTE.

    O registro NÃO é apagado: o status vira CANCELADA e a mudança fica no
    histórico (services.cancelar_pedido_cliente).
    """
    model = Reserva
    template_name = 'website/reserva_confirm_cancel.html'
    success_url = reverse_lazy('minhas_reservas')
    success_message = 'Pedido de %(inicio)s a %(fim)s cancelado.'
    extra_context = {'titulo': 'Cancelar Meu Pedido'}

    def get_queryset(self):
        # select_related('chacara'): o template mostra chacara.nome.
        return Reserva.objects.select_related('chacara').filter(
            cliente__usuario=self.request.user, status=Reserva.STATUS_PENDENTE)

    def get_success_message(self, cleaned_data):
        return self.success_message % {
            'inicio': f'{self.object.data_inicio:%d/%m/%Y}',
            'fim': f'{self.object.data_fim:%d/%m/%Y}',
        }

    def form_valid(self, form):
        # Django 4+: o DeleteView chama form_valid() no POST. Sobrescrevemos
        # para cancelar em vez de excluir.
        try:
            services.cancelar_pedido_cliente(self.object.pk, self.request.user)
        except ErroRegraNegocio as erro:
            messages.error(self.request, str(erro))
        else:
            messages.success(self.request, self.get_success_message({}))
        return HttpResponseRedirect(self.get_success_url())


# ---------------------------------------------------------------------------
# Área administrativa (Administrador)
# ---------------------------------------------------------------------------

class PedidosPendentesListView(AdminRequiredMixin, FilterView):
    model = Reserva
    template_name = 'website/pedidos_pendentes.html'
    context_object_name = 'reservas'
    filterset_class = ReservaPendenteFilter
    paginate_by = 10
    ordering = ['data_pedido']

    def get_queryset(self):
        # select_related: a tabela mostra cliente.nome/telefone; sem isto
        # seria 1 consulta ao Cliente por linha.
        return (
            super().get_queryset()
            .filter(status=Reserva.STATUS_PENDENTE)
            .select_related('cliente', 'chacara')
        )


class TodasReservasListView(AdminRequiredMixin, FilterView):
    """Todas as reservas, de qualquer status, com filtros para o admin."""
    model = Reserva
    template_name = 'website/reservas_admin_list.html'
    context_object_name = 'reservas'
    filterset_class = ReservaAdminFilter
    paginate_by = 10
    ordering = ['-data_inicio']

    def get_queryset(self):
        # select_related: a tabela mostra nome e telefone do cliente; sem
        # isto seriam até 10 consultas extras ao Cliente por página.
        return super().get_queryset().select_related('cliente', 'chacara')


class DecisaoReservaView(AdminRequiredMixin, SingleObjectMixin, FormView):
    """Base de aprovar/recusar: GET mostra a confirmação com observação
    opcional; POST (inclusive dos botões de "Pedidos Pendentes") decide."""
    model = Reserva
    form_class = DecisaoReservaForm
    template_name = 'website/reserva_decisao.html'
    context_object_name = 'reserva'
    success_url = reverse_lazy('pedidos_pendentes')

    def get_queryset(self):
        # Só pedidos pendentes podem ser decididos. select_related: a página
        # de confirmação mostra cliente e chácara.
        return Reserva.objects.select_related('cliente', 'chacara').filter(
            status=Reserva.STATUS_PENDENTE)

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)


class AprovarReservaView(DecisaoReservaView):
    extra_context = {'titulo': 'Aprovar Pedido', 'botao': 'Confirmar Aprovação', 'aprovar': True}

    def form_valid(self, form):
        try:
            reserva, recusados = services.aprovar_reserva(
                self.object.pk, self.request.user, form.cleaned_data['observacao'])
        except ErroRegraNegocio as erro:
            messages.error(self.request, str(erro))
            return redirect(self.get_success_url())
        texto = f'Pedido de {reserva.cliente.nome} aprovado.'
        if recusados:
            texto += f' {recusados} pedido(s) pendente(s) no mesmo período foram recusados automaticamente.'
        messages.success(self.request, texto)
        return redirect(self.get_success_url())


class RecusarReservaView(DecisaoReservaView):
    extra_context = {'titulo': 'Recusar Pedido', 'botao': 'Confirmar Recusa', 'aprovar': False}

    def form_valid(self, form):
        try:
            reserva = services.recusar_reserva(
                self.object.pk, self.request.user, form.cleaned_data['observacao'])
        except ErroRegraNegocio as erro:
            messages.error(self.request, str(erro))
        else:
            messages.success(self.request, f'Pedido de {reserva.cliente.nome} recusado.')
        return redirect(self.get_success_url())


class ReservaUpdateView(AdminRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Reserva
    form_class = ReservaAdminForm
    template_name = 'website/reserva_form.html'
    success_message = 'Reserva atualizada.'
    extra_context = {'titulo': 'Editar Reserva', 'botao': 'Salvar Alterações'}

    def get_success_url(self):
        return reverse('reserva_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['cancelar_url'] = reverse('reserva_detail', args=[self.object.pk])
        return ctx

    def form_valid(self, form):
        anterior = form.initial['status']
        novo = form.cleaned_data['status']
        mudou = anterior != novo
        with transaction.atomic():
            if mudou:
                form.instance.data_decisao = timezone.now()
            response = super().form_valid(form)
            if mudou:
                services.registrar_historico(
                    self.object, anterior, self.request.user,
                    'Status alterado na edição da reserva.',
                )
                if novo == Reserva.STATUS_CONFIRMADA:
                    services.recusar_pendentes_sobrepostas(self.object, self.request.user)
        return response


class ReservaDeleteView(AdminRequiredMixin, SuccessMessageMixin, DeleteView):
    model = Reserva
    template_name = 'website/reserva_confirm_delete.html'
    success_url = reverse_lazy('reservas_todas')
    success_message = 'Reserva excluída.'
    extra_context = {'titulo': 'Excluir Reserva'}

    def get_queryset(self):
        # select_related: a confirmação mostra cliente e chácara.
        return Reserva.objects.select_related('cliente', 'chacara')


# ---------------------------------------------------------------------------
# Edição da chácara (apenas admin — sem criar/excluir pela UI)
# ---------------------------------------------------------------------------

class ChacaraUpdate(AdminRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Chacara
    fields = [
        'nome', 'descricao', 'preco_diaria',
        'tem_estacionamento', 'tem_piscina', 'tem_churrasqueira',
        'num_quartos', 'num_banheiros',
    ]
    template_name = 'website/chacara_form.html'
    success_url = reverse_lazy('chacara_unica')
    success_message = 'Informações da chácara atualizadas.'
    extra_context = {'titulo': 'Editar Chácara', 'botao': 'Salvar Alterações'}


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class ClienteUpdate(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'website/cliente_form.html'
    success_url = reverse_lazy('index')
    success_message = 'Seus dados foram salvos.'
    extra_context = {'titulo': 'Editar Cliente', 'botao': 'Salvar Alterações'}

    def get_queryset(self):
        # Cada usuário só pode editar o próprio cadastro de cliente.
        return Cliente.objects.filter(usuario=self.request.user)


class AdministradorCreate(AdminRequiredMixin, SuccessMessageMixin, CreateView):
    model = Administrador
    fields = ['nome', 'usuario']
    template_name = 'website/administrador_form.html'
    success_url = reverse_lazy('index')
    success_message = 'Administrador %(nome)s cadastrado com sucesso.'
    extra_context = {'titulo': 'Cadastro de Administrador', 'botao': 'Cadastrar Administrador'}

    def form_valid(self, form):
        response = super().form_valid(form)
        services.garantir_grupo_admin(self.object.usuario)
        return response


# ---------------------------------------------------------------------------
# IA generativa (Gemini)
# ---------------------------------------------------------------------------

class ChatbotMensagemView(View):
    """Modo A: recebe a pergunta, chama o assistente e devolve JSON.

    Público (visitante também usa), com CSRF obrigatório e limite de
    mensagens por hora para conter o custo.
    """
    http_method_names = ['post']
    LIMITE_POR_HORA = 15

    def _mensagem(self, request):
        if request.content_type == 'application/json':
            try:
                dados = json.loads(request.body or b'{}')
            except ValueError:
                return ''
            valor = dados.get('mensagem', '') if isinstance(dados, dict) else ''
            return valor if isinstance(valor, str) else ''
        return request.POST.get('mensagem', '')

    def _dentro_do_limite(self, request):
        """Rate limit simples por sessão: guarda os horários dos envios da última hora."""
        agora = time.time()
        envios = [t for t in request.session.get('chat_ia_envios', []) if agora - t < 3600]
        if len(envios) >= self.LIMITE_POR_HORA:
            request.session['chat_ia_envios'] = envios
            return False
        request.session['chat_ia_envios'] = envios + [agora]
        return True

    def post(self, request, *args, **kwargs):
        mensagem = self._mensagem(request).strip()
        if not mensagem:
            return JsonResponse({'erro': 'Escreva sua pergunta.'}, status=400)
        if len(mensagem) > ia.MAX_CARACTERES_MENSAGEM:
            return JsonResponse(
                {'erro': f'A mensagem pode ter no máximo {ia.MAX_CARACTERES_MENSAGEM} caracteres.'},
                status=400,
            )
        if not ia.ia_habilitada():
            return JsonResponse({'erro': 'Assistente indisponível no momento.'}, status=503)
        if not self._dentro_do_limite(request):
            return JsonResponse(
                {'erro': 'Você atingiu o limite de mensagens por hora. Tente novamente mais tarde '
                         'ou consulte a página de Disponibilidade.'},
                status=429,
            )

        historico = request.session.get('chat_ia', [])[-ia.MAX_MENSAGENS_HISTORICO:]
        resposta = ia.responder_chat(historico, mensagem, usuario=request.user)
        if resposta is None:
            return JsonResponse(
                {'erro': 'Não consegui responder agora. Tente novamente em instantes.'}, status=503)

        historico += [{'role': 'user', 'text': mensagem}, {'role': 'model', 'text': resposta}]
        # Guarda só as últimas 10 trocas: é o que será reenviado no próximo turno.
        request.session['chat_ia'] = historico[-ia.MAX_MENSAGENS_HISTORICO:]
        return JsonResponse({'resposta': resposta})


class ChatbotLimparView(View):
    """Botão "Nova conversa": apaga o histórico da sessão."""
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        request.session.pop('chat_ia', None)
        return JsonResponse({'ok': True})


class ReanalisarPedidoView(AdminRequiredMixin, View):
    """Modo B sob demanda: a admin pede uma nova análise do pedido."""
    http_method_names = ['post']

    def post(self, request, pk):
        reserva = get_object_or_404(Reserva.objects.select_related('chacara'), pk=pk)
        if not ia.ia_habilitada():
            messages.warning(request, 'A IA está desativada: configure a GEMINI_API_KEY.')
        elif ia.analisar_pedido(reserva, usuario=request.user):
            messages.success(request, 'Análise da IA atualizada.')
        else:
            messages.error(request, 'Não foi possível gerar a análise agora. Tente novamente mais tarde.')
        return redirect('reserva_detail', pk=reserva.pk)


class UsoIAListView(AdminRequiredMixin, FilterView):
    """Métricas de tokens e custo de cada chamada ao Gemini."""
    model = UsoIA
    template_name = 'website/uso_ia_list.html'
    context_object_name = 'usos'
    filterset_class = UsoIAFilter
    paginate_by = 20
    ordering = ['-data']

    def get_queryset(self):
        # select_related: a tabela mostra o usuário e o nº da reserva; sem
        # isto seriam até 2 consultas extras por linha.
        return super().get_queryset().select_related('usuario', 'reserva')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Resumo sobre o resultado do filtro (todas as páginas, não só a atual).
        filtrado = self.object_list.order_by()
        cotacao = Decimal(str(settings.GEMINI_COTACAO_BRL))
        totais = filtrado.aggregate(
            chamadas=Count('id'),
            entrada=Sum('tokens_entrada'),
            saida=Sum('tokens_saida'),
            custo=Sum('custo_usd'),
        )
        totais['custo'] = totais['custo'] or Decimal('0')
        totais['custo_brl'] = totais['custo'] * cotacao
        por_tipo = {
            linha['tipo']: linha
            for linha in filtrado.values('tipo').annotate(chamadas=Count('id'), custo_medio=Avg('custo_usd'))
        }
        for linha in por_tipo.values():
            linha['custo_medio_brl'] = Decimal(linha['custo_medio']) * cotacao
        ctx.update(
            totais=totais,
            media_chat=por_tipo.get(UsoIA.CHAT),
            media_analise=por_tipo.get(UsoIA.ANALISE),
            preco_entrada_milhao=settings.GEMINI_PRECO_ENTRADA_USD * 1_000_000,
            preco_saida_milhao=settings.GEMINI_PRECO_SAIDA_USD * 1_000_000,
            cotacao=settings.GEMINI_COTACAO_BRL,
            modelo_ia=settings.GEMINI_MODEL,
        )
        return ctx
