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


@register.filter
def estrelas(nota):
    """Classes dos 5 ícones de estrela para uma nota de 0 a 5 (com meia estrela).

    Ex.: 4.3 -> 4 cheias + 1 meia; uso:
    {% for icone in nota|estrelas %}<i class="bi {{ icone }}"></i>{% endfor %}
    """
    try:
        meias = round(float(nota or 0) * 2)
    except (TypeError, ValueError):
        meias = 0
    icones = []
    for posicao in range(1, 6):
        if meias >= posicao * 2:
            icones.append('bi-star-fill')
        elif meias == posicao * 2 - 1:
            icones.append('bi-star-half')
        else:
            icones.append('bi-star')
    return icones
