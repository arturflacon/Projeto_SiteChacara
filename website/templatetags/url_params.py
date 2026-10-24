"""Tags de URL para listas paginadas e filtradas.

Uso nos templates: {% load url_params %}
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_com_parametros(context, **parametros):
    """Query string atual com alguns parâmetros trocados ou removidos.

    Copia o ``request.GET`` (todos os filtros da busca), substitui os
    parâmetros informados e remove os que vierem com ``None`` ou vazio.
    Devolve a query string já codificada, começando com ``?``:

        {% url_com_parametros page=page_obj.next_page_number %}
        -> ?status=PENDENTE&cliente__nome=silva&page=3

        {% url_com_parametros page=None %}   (remove a página, mantém os filtros)

    O resultado passa pelo autoescape do template (``&`` vira ``&amp;`` no
    HTML, que o navegador lê de volta como ``&``); os valores já saem
    percent-encoded pelo ``urlencode``.
    """
    query = context['request'].GET.copy()
    for chave, valor in parametros.items():
        if valor is None or valor == '':
            query.pop(chave, None)
        else:
            query[chave] = valor
    return '?' + query.urlencode()


@register.simple_tag
def paginas_proximas(page_obj, nos_lados=2, nas_pontas=1):
    """Números de página ao redor da atual, com reticências nos saltos.

    Ex.: página 7 de 20 -> 1, …, 5, 6, 7, 8, 9, …, 20. As reticências vêm
    como ``page_obj.paginator.ELLIPSIS``.
    """
    return list(page_obj.paginator.get_elided_page_range(
        page_obj.number, on_each_side=nos_lados, on_ends=nas_pontas))
