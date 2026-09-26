---
name: django-paginacao
description: Use sempre que for criar ou editar uma listagem neste projeto Django — ListView, FilterView ou template de lista — para que toda lista seja paginada do mesmo jeito: paginate_by com ordering na view e um único paginacao.html incluído com {% include %}, que mantém os parâmetros de busca da URL ao trocar de página.
---

## Antes de mexer em qualquer listagem

Existe UM `paginacao.html` no app que guarda o template base
(`<app>/templates/<app>/paginacao.html`) com exatamente este conteúdo. Se não
existir, crie antes de tudo:

```html
{# Navegação entre páginas: mantém os filtros da URL (tudo, menos o "page") #}
{% if is_paginated %}
<nav aria-label="Páginas">
    <ul class="pagination">
        {% if page_obj.has_previous %}
        <li class="page-item">
            <a class="page-link" href="?{% for chave, valor in request.GET.items %}{% if chave != 'page' %}{{ chave }}={{ valor|urlencode }}&{% endif %}{% endfor %}page={{ page_obj.previous_page_number }}">Anterior</a>
        </li>
        {% endif %}
        <li class="page-item disabled"><span class="page-link">Página {{ page_obj.number }} de {{ page_obj.paginator.num_pages }}</span></li>
        {% if page_obj.has_next %}
        <li class="page-item">
            <a class="page-link" href="?{% for chave, valor in request.GET.items %}{% if chave != 'page' %}{{ chave }}={{ valor|urlencode }}&{% endif %}{% endfor %}page={{ page_obj.next_page_number }}">Próxima</a>
        </li>
        {% endif %}
    </ul>
</nav>
{% endif %}
```

## A view

1. Toda `ListView` e `FilterView` de registros tem `paginate_by` (padrão 10) e
   `ordering` (ex.: `ordering = ['nome']`, ou `['-cadastrado_em']` para os mais
   recentes primeiro). Sem ordering, a paginação fica inconsistente e o Django
   avisa `UnorderedObjectListWarning`.
2. Se a view tem `get_queryset`, ele parte de `super().get_queryset()`, que é o
   que aplica o `ordering`. Se precisar devolver uma consulta nova
   (`Modelo.objects...`), ela termina com `.order_by(...)`.
3. Listas pequenas e fixas (ex.: os estados do Brasil) podem ficar sem
   paginação, mas então não têm `paginate_by` nem o include.

## O template da lista

1. Logo depois da `</table>` (ou do fim da lista de cards):
   `{% include '<app>/paginacao.html' %}`.
2. Nunca copie o bloco de paginação para dentro de um template de lista. Toda
   mudança de visual ou de comportamento é feita no `paginacao.html`.
3. A lista continua percorrendo `object_list`, que já vem só com a página atual.

## Conferência antes de terminar

1. Com mais registros do que o `paginate_by`, aparecem "Página 1 de N" e o link
   "Próxima"; na última página, só "Anterior".
2. Se a URL tem parâmetros de busca, eles continuam na URL depois de trocar de página.
3. O terminal do `runserver` não mostra `UnorderedObjectListWarning`.
