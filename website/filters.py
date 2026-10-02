import django_filters
from django import forms

from .models import Reserva


def _campo_data(lookup_expr, label):
    """DateFilter sobre data_inicio com o seletor de data do navegador."""
    return django_filters.DateFilter(
        field_name='data_inicio', lookup_expr=lookup_expr, label=label,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )


class ReservaAdminFilter(django_filters.FilterSet):
    """Filtros de "Todas as Reservas" (admin).

    Lookups usados: icontains (nome do cliente), exact (status),
    gte / lte (intervalo da data de chegada).
    """

    cliente__nome = django_filters.CharFilter(
        field_name='cliente__nome', lookup_expr='icontains', label='Nome do cliente',
    )
    status = django_filters.ChoiceFilter(
        choices=Reserva.STATUS_CHOICES, lookup_expr='exact', label='Status', empty_label='Todos',
    )
    data_inicio__gte = _campo_data('gte', 'Chegada a partir de')
    data_inicio__lte = _campo_data('lte', 'Chegada até')

    class Meta:
        model = Reserva
        fields = []


class MinhasReservasFilter(django_filters.FilterSet):
    """Filtros de "Minhas Reservas". A view já restringe ao cliente logado,
    então o filtro é aplicado só sobre as reservas dele."""

    status = django_filters.ChoiceFilter(
        choices=Reserva.STATUS_CHOICES, lookup_expr='exact', label='Status', empty_label='Todos',
    )
    data_inicio__gte = _campo_data('gte', 'Chegada a partir de')
    data_inicio__lte = _campo_data('lte', 'Chegada até')

    class Meta:
        model = Reserva
        fields = []


class ReservaPendenteFilter(django_filters.FilterSet):
    """Filtros de "Pedidos Pendentes" (admin). O status já é fixo em PENDENTE."""

    cliente = django_filters.CharFilter(
        field_name='cliente__nome', lookup_expr='icontains', label='Cliente contém',
    )
    data_inicio = django_filters.DateFromToRangeFilter(
        label='Entrada entre',
        widget=django_filters.widgets.RangeWidget(attrs={'type': 'date'}),
    )
    data_pedido = django_filters.DateFromToRangeFilter(
        label='Pedido feito entre',
        widget=django_filters.widgets.RangeWidget(attrs={'type': 'date'}),
    )

    class Meta:
        model = Reserva
        fields = {}


class ReservaConfirmadaFilter(django_filters.FilterSet):
    """Filtros da página pública de disponibilidade.

    Sem busca por cliente: a página é aberta a visitantes e não pode
    revelar quem reservou.
    """

    data_inicio = django_filters.DateFromToRangeFilter(
        label='Entrada entre',
        widget=django_filters.widgets.RangeWidget(attrs={'type': 'date'}),
    )

    class Meta:
        model = Reserva
        fields = {}
