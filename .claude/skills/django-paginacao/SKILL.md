---
name: django-paginacao
description: Use sempre que for criar ou editar uma listagem neste projeto Django — ListView, FilterView ou template de lista — para que toda lista seja paginada do mesmo jeito: paginate_by com ordering na view e o partial único _paginacao.html, que usa a templatetag própria url_com_parametros para manter os filtros da URL ao trocar de página.
---

## A base (já existe — não recrie)

1. `website/templatetags/url_params.py`:
   - `{% url_com_parametros page=N %}` (`simple_tag(takes_context=True)`):
     copia o `request.GET`, troca/insere os parâmetros informados, remove os
     que vierem `None`/vazios e devolve a query string codificada começando
     com `?`. É ela que preserva os filtros.
   - `{% paginas_proximas page_obj as paginas %}`: números ao redor da
     página atual, com reticências (`page_obj.paginator.ELLIPSIS`).
2. `website/templates/website/_paginacao.html`: o ÚNICO bloco de paginação
   do projeto — "Página X de N · total", **Anterior**, números próximos e
   **Próxima**, no visual `pagination-sm` do Bootstrap.

Se precisar mudar o visual ou o comportamento da paginação, mude esses dois
arquivos e mais nada.

## A view

1. Toda `ListView` e `FilterView` de registros tem `paginate_by` (padrão 10)
   e `ordering` (ex.: `ordering = ['-data_pedido']`). Sem ordering a
   paginação fica inconsistente e o Django avisa `UnorderedObjectListWarning`.
2. Se a view tem `get_queryset`, ele parte de `super().get_queryset()` (que
   aplica o `ordering`). Se devolver uma consulta nova, ela termina com `.order_by(...)`.
3. O `get_queryset` traz o que a tabela mostra com `select_related` /
   `prefetch_related` / `annotate` (ver `docs/otimizacoes.md`).
4. Listas pequenas e fixas podem ficar sem paginação — aí sem `paginate_by`
   nem o include (e, se for tabela, use a skill `datatables-listagens`).

## O template da lista

1. Logo depois da `</table>` (ou do fim da lista de cards):
   `{% include 'website/_paginacao.html' %}`.
2. Nunca copie o bloco de paginação para dentro de um template de lista.
3. Nunca monte link de página à mão (`?page={{ ... }}`): use
   `{% url_com_parametros page=... %}`, senão os filtros se perdem.
4. A lista percorre `object_list` (ou o `context_object_name`), que já vem
   só com a página atual.
5. Tabela paginada no servidor **não** usa DataTables.

## Testes

```python
response = c.get(url, {'status': 'PENDENTE', 'cliente__nome': 'silva'})
self.assertContains(response, 'Página 1 de 2')
self.assertContains(response, 'href="?status=PENDENTE&amp;cliente__nome=silva&amp;page=2" rel="next">Próxima</a>')
```

(O `&` sai como `&amp;` no HTML por causa do autoescape — o navegador lê `&`.)

## Conferência antes de terminar

1. Com mais registros do que o `paginate_by`, aparecem os números, "Próxima"
   e "Página 1 de N"; na última página, "Próxima" fica desabilitado.
2. Com filtros na URL, trocar de página mantém todos eles.
3. O terminal do `runserver` não mostra `UnorderedObjectListWarning`.
