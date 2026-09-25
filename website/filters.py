import django_filters

from .models import Reserva


class ReservaFilter(django_filters.FilterSet):
    """Filtros de "Minhas Reservas" (cliente vê só as próprias)."""

    data_inicio = django_filters.DateFromToRangeFilter(
        label='Entrada entre',
        widget=django_filters.widgets.RangeWidget(attrs={'type': 'date'}),
    )

    class Meta:
        model = Reserva
        fields = {'status': ['exact']}


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
