"""Markdown -> HTML sanitizado para as respostas da IA.

O texto da IA é guardado cru no banco. Na exibição ele é convertido com a
biblioteca ``markdown`` e passa pelo ``nh3`` com uma lista fechada de tags e
atributos: <script>, atributos on*, style e URLs javascript: são removidos;
links ganham rel="noopener noreferrer".
"""
import markdown
import nh3

TAGS_PERMITIDAS = {
    'p', 'br', 'strong', 'b', 'em', 'i', 'code', 'pre', 'blockquote',
    'ul', 'ol', 'li', 'h3', 'h4', 'h5', 'h6', 'hr', 'a',
}
ATRIBUTOS_PERMITIDOS = {'a': {'href', 'title'}}
ESQUEMAS_PERMITIDOS = {'http', 'https', 'mailto'}


def renderizar(texto):
    html = markdown.markdown(texto or '', extensions=['sane_lists', 'nl2br'])
    return nh3.clean(
        html,
        tags=TAGS_PERMITIDAS,
        clean_content_tags={'script', 'style'},  # some a tag E o conteúdo
        attributes=ATRIBUTOS_PERMITIDOS,
        url_schemes=ESQUEMAS_PERMITIDOS,
        link_rel='noopener noreferrer',
    )
