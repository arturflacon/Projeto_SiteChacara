"""Tags e filtros personalizados do Sítio de Lurdes.

Uso nos templates: {% load sitio_tags %}
"""
import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def url_replace(request, **kwargs):
    """Devolve a query string atual trocando/inserindo os parâmetros informados.

    Ex.: <a href="?{% url_replace request page=2 %}"> mantém os filtros da
    busca (status, datas, nome...) e só troca a página.
    """
    query = request.GET.copy()
    for chave, valor in kwargs.items():
        query[chave] = valor
    # urlencode() já codifica tudo em %XX; só "=" e "&" ficam literais,
    # então é seguro marcar como safe (evita o "&amp;" na URL).
    return mark_safe(query.urlencode())


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
