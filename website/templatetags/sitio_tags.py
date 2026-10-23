"""Tags e filtros personalizados do Sítio de Lurdes.

Uso nos templates: {% load sitio_tags %}
"""
import re

from django import template

register = template.Library()


@register.filter
def pertence(user, nome_grupo):
    """True se o usuário está no grupo. Ex.: user|pertence:"Administradores".

    Os nomes dos grupos ficam guardados no próprio objeto user, para que
    vários usos na mesma página façam uma única consulta ao banco.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if not hasattr(user, '_grupos_cache'):
        user._grupos_cache = set(user.groups.values_list('name', flat=True))
    return nome_grupo in user._grupos_cache


@register.filter
def telefone(valor):
    """Formata só dígitos como telefone: 46999998888 -> (46) 99999-8888."""
    digitos = re.sub(r'\D', '', str(valor or ''))
    if len(digitos) == 11:
        return f'({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}'
    if len(digitos) == 10:
        return f'({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}'
    return valor
