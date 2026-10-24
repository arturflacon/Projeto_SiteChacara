"""Filtro {{ texto|markdown_seguro }}: Markdown convertido e sanitizado (nh3).

Uso: {% load markdown_seguro %}
"""
from django import template
from django.utils.safestring import mark_safe

from ..formatacao import renderizar

register = template.Library()


@register.filter(name='markdown_seguro')
def markdown_seguro(texto):
    # mark_safe só DEPOIS da sanitização: o nh3 já removeu tudo que não é permitido.
    return mark_safe(renderizar(texto))
