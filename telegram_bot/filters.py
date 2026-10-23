import django_filters
from django import forms

from .models import MensagemTelegram


class MensagemTelegramFilter(django_filters.FilterSet):
    """Filtros do log do bot (admin)."""

    direcao = django_filters.ChoiceFilter(
        choices=MensagemTelegram.DIRECAO_CHOICES, label='Direção', empty_label='Todas')
    tipo = django_filters.ChoiceFilter(
        choices=MensagemTelegram.TIPO_CHOICES, label='Tipo', empty_label='Todos')
    usuario = django_filters.CharFilter(
        field_name='usuario__username', lookup_expr='icontains', label='Usuário contém')
    criado_em__gte = django_filters.DateFilter(
        field_name='criado_em', lookup_expr='date__gte', label='A partir de',
        widget=forms.DateInput(attrs={'type': 'date'}))
    criado_em__lte = django_filters.DateFilter(
        field_name='criado_em', lookup_expr='date__lte', label='Até',
        widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = MensagemTelegram
        fields = []
