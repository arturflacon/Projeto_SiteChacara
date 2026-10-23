import django_filters
from django import forms

from .models import RequisicaoIA


class RequisicaoIAFilter(django_filters.FilterSet):
    """Filtros da tela de Requisições da IA (admin)."""

    usuario = django_filters.CharFilter(
        field_name='usuario__username', lookup_expr='icontains', label='Usuário contém',
    )
    origem = django_filters.ChoiceFilter(
        choices=RequisicaoIA.Origem.choices, lookup_expr='exact', label='Origem', empty_label='Todas',
    )
    sucesso = django_filters.ChoiceFilter(
        choices=[('true', 'Sucesso'), ('false', 'Erro')], method='filtrar_sucesso',
        label='Resultado', empty_label='Todos',
    )
    # "criado_em" é DateTimeField: date__gte/date__lte comparam só o dia, assim
    # o filtro "até" inclui as chamadas feitas ao longo do último dia.
    criado_em__gte = django_filters.DateFilter(
        field_name='criado_em', lookup_expr='date__gte', label='A partir de',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    criado_em__lte = django_filters.DateFilter(
        field_name='criado_em', lookup_expr='date__lte', label='Até',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )

    class Meta:
        model = RequisicaoIA
        fields = []

    def filtrar_sucesso(self, queryset, name, value):
        return queryset.filter(sucesso=(value == 'true'))
