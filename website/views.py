from braces.views import GroupRequiredMixin
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView,
    TemplateView, UpdateView,
)
from django.views.generic.detail import SingleObjectMixin
from django_filters.views import FilterView

from .filters import (
    MinhasReservasFilter, ReservaAdminFilter,
    ReservaConfirmadaFilter, ReservaPendenteFilter,
)
from .forms import (
    ClienteForm, DecisaoReservaForm, ReservaAdminForm,
    ReservaClienteForm, SignupForm,
)
from .models import Administrador, Chacara, Cliente, HistoricoReserva, Reserva


GRUPO_ADMIN = 'Administradores'


def eh_admin(user):
    """Mesma regra do AdminRequiredMixin: grupo, superuser ou perfil Administrador."""
    return (
        user.is_superuser
        or hasattr(user, 'administrador')
        or user.groups.filter(name=GRUPO_ADMIN).exists()
    )


# ---------------------------------------------------------------------------
# Movimento: histórico de status e recusa automática
# ---------------------------------------------------------------------------

def registrar_historico(reserva, status_anterior, usuario, observacao=''):
    """Grava em HistoricoReserva a mudança de status que acabou de acontecer."""
    return HistoricoReserva.objects.create(
        reserva=reserva,
        status_anterior=status_anterior,
        status_novo=reserva.status,
        alterado_por=usuario,
        observacao=observacao,
    )


def recusar_pendentes_sobrepostas(reserva, usuario):
    """Recusa os pedidos PENDENTES da mesma chácara que conflitam com uma
    reserva recém-confirmada. Devolve quantos foram recusados."""
    agora = timezone.now()
    # select_related: o save() de cada reserva lê chacara.preco_diaria;
    # sem isto seria 1 consulta extra à chácara por pedido recusado.
    pendentes = reserva.sobrepostas(Reserva.STATUS_PENDENTE).select_related('chacara')
    total = 0
    for pedido in pendentes:
        pedido.status = Reserva.STATUS_RECUSADA
        pedido.data_decisao = agora
        pedido.save(update_fields=['status', 'data_decisao'])
        registrar_historico(
            pedido, Reserva.STATUS_PENDENTE, usuario,
            'Recusado automaticamente: período confirmado para outro pedido.',
        )
        total += 1
    return total


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class AdminRequiredMixin(GroupRequiredMixin):
    """Acesso restrito ao grupo 'Administradores' (django-braces).

    Além dos membros do grupo, superusers e usuários com perfil
    ``Administrador`` mantêm acesso — isso preserva o comportamento
    esperado mesmo para perfis criados fora do fluxo padrão.
    """

    group_required = GRUPO_ADMIN
    raise_exception = False  # sem permissão -> redireciona ao login

    def check_membership(self, groups):
        u = self.request.user
        if u.is_superuser or hasattr(u, 'administrador'):
            return True
        return super().check_membership(groups)


# ---------------------------------------------------------------------------
# Páginas públicas
# ---------------------------------------------------------------------------

class IndexView(TemplateView):
    template_name = 'website/index.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['chacara'] = Chacara.objects.first()
        return ctx


class SobreView(TemplateView):
    template_name = 'website/sobre.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['chacara'] = Chacara.objects.first()
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
        mostrar_cliente = self.request.user.is_authenticated and eh_admin(self.request.user)
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
        return get_object_or_404(Chacara)


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
            return redirect('pedidos_pendentes' if eh_admin(request.user) else 'index')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        chacara = Chacara.objects.first()
        if not chacara:
            form.add_error(None, 'Nenhuma chácara cadastrada no sistema.')
            return self.form_invalid(form)
        # Preenche o que o cliente não informa ANTES de salvar.
        form.instance.cliente = self.request.user.cliente
        form.instance.chacara = chacara
        form.instance.status = Reserva.STATUS_PENDENTE
        with transaction.atomic():
            response = super().form_valid(form)
            # Depois do super(), self.object é a reserva já salva.
            registrar_historico(self.object, '', self.request.user, 'Pedido criado pelo cliente.')
        return response


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
        if eh_admin(u):
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


class MinhaReservaDeleteView(LoginRequiredMixin, DeleteView):
    """Cliente cancela o próprio pedido enquanto está PENDENTE.

    O registro NÃO é apagado: o status vira CANCELADA e a mudança fica no
    histórico.
    """
    model = Reserva
    template_name = 'website/reserva_confirm_cancel.html'
    success_url = reverse_lazy('minhas_reservas')
    extra_context = {'titulo': 'Cancelar Meu Pedido'}

    def get_queryset(self):
        # select_related('chacara'): o template mostra chacara.nome e o
        # save() lê chacara.preco_diaria.
        return Reserva.objects.select_related('chacara').filter(
            cliente__usuario=self.request.user, status=Reserva.STATUS_PENDENTE)

    def form_valid(self, form):
        # Django 4+: o DeleteView chama form_valid() no POST. Sobrescrevemos
        # para cancelar em vez de excluir.
        reserva = self.object
        with transaction.atomic():
            anterior = reserva.status
            reserva.status = Reserva.STATUS_CANCELADA
            reserva.save(update_fields=['status'])
            registrar_historico(reserva, anterior, self.request.user, 'Cancelado pelo cliente.')
        messages.success(self.request, 'Pedido cancelado.')
        return redirect(self.get_success_url())


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
        reserva = self.object
        usuario = self.request.user
        with transaction.atomic():
            # Trava a chácara: duas aprovações simultâneas para a mesma
            # chácara passam por aqui uma de cada vez (no PostgreSQL).
            Chacara.objects.select_for_update().get(pk=reserva.chacara_id)
            reserva.refresh_from_db()
            if reserva.status != Reserva.STATUS_PENDENTE:
                messages.error(self.request, f'O pedido #{reserva.pk} não está mais pendente.')
                return redirect(self.get_success_url())

            # 1. Revalida: o clean() do model não roda no save().
            if reserva.sobrepostas(Reserva.STATUS_CONFIRMADA).exists():
                messages.error(
                    self.request,
                    f'Não foi possível aprovar o pedido de {reserva.cliente.nome}: '
                    'já existe uma reserva confirmada nesse período.',
                )
                return redirect(self.get_success_url())

            # 2. Confirma.
            anterior = reserva.status
            reserva.status = Reserva.STATUS_CONFIRMADA
            reserva.data_decisao = timezone.now()
            reserva.save()

            # 3. Registra no histórico (outra classe do models).
            registrar_historico(reserva, anterior, usuario, form.cleaned_data['observacao'])

            # 4. Recusa os outros pedidos pendentes que conflitam.
            recusados = recusar_pendentes_sobrepostas(reserva, usuario)

        texto = f'Pedido de {reserva.cliente.nome} aprovado.'
        if recusados:
            texto += f' {recusados} pedido(s) pendente(s) no mesmo período foram recusados automaticamente.'
        messages.success(self.request, texto)
        return redirect(self.get_success_url())


class RecusarReservaView(DecisaoReservaView):
    extra_context = {'titulo': 'Recusar Pedido', 'botao': 'Confirmar Recusa', 'aprovar': False}

    def form_valid(self, form):
        reserva = self.object
        with transaction.atomic():
            anterior = reserva.status
            reserva.status = Reserva.STATUS_RECUSADA
            reserva.data_decisao = timezone.now()
            reserva.save(update_fields=['status', 'data_decisao'])
            registrar_historico(reserva, anterior, self.request.user, form.cleaned_data['observacao'])
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
                registrar_historico(
                    self.object, anterior, self.request.user,
                    'Status alterado na edição da reserva.',
                )
                if novo == Reserva.STATUS_CONFIRMADA:
                    recusar_pendentes_sobrepostas(self.object, self.request.user)
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
        grupo, _ = Group.objects.get_or_create(name=GRUPO_ADMIN)
        self.object.usuario.groups.add(grupo)
        return response
