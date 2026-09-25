from braces.views import GroupRequiredMixin
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView,
    TemplateView, UpdateView,
)
from django_filters.views import FilterView

from .filters import ReservaConfirmadaFilter, ReservaFilter, ReservaPendenteFilter
from .forms import ReservaClienteForm, SignupForm
from .models import Administrador, Chacara, Cliente, Reserva


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class AdminRequiredMixin(GroupRequiredMixin):
    """Acesso restrito ao grupo 'Administradores' (django-braces).

    Além dos membros do grupo, superusers e usuários com perfil
    ``Administrador`` mantêm acesso — isso preserva o comportamento
    esperado mesmo para perfis criados fora do fluxo padrão.
    """

    group_required = 'Administradores'
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
        return (
            super().get_queryset()
            .filter(status=Reserva.STATUS_CONFIRMADA)
            .select_related('cliente')
        )


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

class SignupView(FormView):
    template_name = 'website/registro.html'
    form_class = SignupForm
    success_url = reverse_lazy('index')
    extra_context = {'titulo': 'Cadastro de Cliente', 'botao': 'Criar conta'}

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Área do cliente (autenticado)
# ---------------------------------------------------------------------------

class ReservaCreate(LoginRequiredMixin, CreateView):
    model = Reserva
    form_class = ReservaClienteForm
    template_name = 'website/reserva_form.html'
    success_url = reverse_lazy('minhas_reservas')
    extra_context = {'titulo': 'Fazer Pedido de Reserva', 'botao': 'Enviar Pedido'}

    def form_valid(self, form):
        reserva = form.save(commit=False)
        reserva.cliente = get_object_or_404(Cliente, usuario=self.request.user)
        chacara = Chacara.objects.first()
        if not chacara:
            form.add_error(None, 'Nenhuma chácara cadastrada no sistema.')
            return self.form_invalid(form)
        reserva.chacara = chacara
        reserva.status = Reserva.STATUS_PENDENTE
        reserva.save()
        return redirect(self.success_url)


class MinhasReservasListView(LoginRequiredMixin, FilterView):
    model = Reserva
    template_name = 'website/reserva_list.html'
    context_object_name = 'reservas'
    filterset_class = ReservaFilter
    paginate_by = 10
    ordering = ['-data_pedido']

    def get_queryset(self):
        # Usuário sem perfil de cliente cai numa lista vazia.
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
        qs = super().get_queryset()
        u = self.request.user
        if u.is_superuser or hasattr(u, 'administrador'):
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
        return Reserva.objects.select_related('cliente', 'chacara').filter(
            cliente__usuario=self.request.user)


class MinhaReservaUpdateView(LoginRequiredMixin, UpdateView):
    """Cliente edita o próprio pedido enquanto está PENDENTE."""
    model = Reserva
    form_class = ReservaClienteForm
    template_name = 'website/reserva_form.html'
    success_url = reverse_lazy('minhas_reservas')
    extra_context = {'titulo': 'Editar Meu Pedido', 'botao': 'Salvar Alterações'}

    def get_queryset(self):
        return Reserva.objects.filter(
            cliente__usuario=self.request.user, status=Reserva.STATUS_PENDENTE)


class MinhaReservaDeleteView(LoginRequiredMixin, DeleteView):
    """Cliente cancela (exclui) o próprio pedido enquanto está PENDENTE."""
    model = Reserva
    template_name = 'website/reserva_confirm_cancel.html'
    success_url = reverse_lazy('minhas_reservas')
    extra_context = {'titulo': 'Cancelar Meu Pedido'}

    def get_queryset(self):
        return Reserva.objects.filter(
            cliente__usuario=self.request.user, status=Reserva.STATUS_PENDENTE)


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
        return (
            super().get_queryset()
            .filter(status=Reserva.STATUS_PENDENTE)
            .select_related('cliente', 'chacara')
        )


class AprovarReservaView(AdminRequiredMixin, View):
    def post(self, _request, pk):
        reserva = get_object_or_404(Reserva, pk=pk)
        reserva.status = Reserva.STATUS_CONFIRMADA
        reserva.data_decisao = timezone.now()
        reserva.save()
        return redirect('pedidos_pendentes')


class RecusarReservaView(AdminRequiredMixin, View):
    def post(self, _request, pk):
        reserva = get_object_or_404(Reserva, pk=pk)
        reserva.status = Reserva.STATUS_RECUSADA
        reserva.data_decisao = timezone.now()
        reserva.save()
        return redirect('pedidos_pendentes')


class ReservaUpdateView(AdminRequiredMixin, UpdateView):
    model = Reserva
    fields = ['chacara', 'data_inicio', 'data_fim', 'observacoes', 'status']
    template_name = 'website/reserva_form.html'
    success_url = reverse_lazy('pedidos_pendentes')
    extra_context = {'titulo': 'Editar Reserva', 'botao': 'Salvar Alterações'}


class ReservaDeleteView(AdminRequiredMixin, DeleteView):
    model = Reserva
    template_name = 'website/reserva_confirm_delete.html'
    success_url = reverse_lazy('pedidos_pendentes')
    extra_context = {'titulo': 'Excluir Reserva'}


# ---------------------------------------------------------------------------
# Edição da chácara (apenas admin — sem criar/excluir pela UI)
# ---------------------------------------------------------------------------

class ChacaraUpdate(AdminRequiredMixin, UpdateView):
    model = Chacara
    fields = [
        'nome', 'descricao', 'preco_diaria',
        'tem_estacionamento', 'tem_piscina', 'tem_churrasqueira',
        'num_quartos', 'num_banheiros',
    ]
    template_name = 'website/chacara_form.html'
    success_url = reverse_lazy('chacara_unica')
    extra_context = {'titulo': 'Editar Chácara', 'botao': 'Salvar Alterações'}


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class ClienteUpdate(LoginRequiredMixin, UpdateView):
    model = Cliente
    fields = ['nome', 'telefone']
    template_name = 'website/cliente_form.html'
    success_url = reverse_lazy('index')
    extra_context = {'titulo': 'Editar Cliente', 'botao': 'Salvar Alterações'}

    def get_queryset(self):
        # Cada usuário só pode editar o próprio cadastro de cliente.
        return Cliente.objects.filter(usuario=self.request.user)


class AdministradorCreate(AdminRequiredMixin, CreateView):
    model = Administrador
    fields = ['nome', 'usuario']
    template_name = 'website/administrador_form.html'
    success_url = reverse_lazy('index')
    extra_context = {'titulo': 'Cadastro de Administrador', 'botao': 'Cadastrar Administrador'}

    def form_valid(self, form):
        response = super().form_valid(form)
        grupo, _ = Group.objects.get_or_create(name='Administradores')
        self.object.usuario.groups.add(grupo)
        return response
