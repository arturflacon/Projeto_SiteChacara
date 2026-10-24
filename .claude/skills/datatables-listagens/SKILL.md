---
name: datatables-listagens
description: Use ao criar ou editar uma tabela que mostra TODOS os registros de uma vez, sem paginação nem filtro no servidor (ex.: "IA por usuário") — para usar o DataTables já carregado no modelo.html, em português e com o tema do Bootstrap 5. Não use em listas paginadas pelo Django.
---

## Quando usar (e quando NÃO usar)

- **Use** em tabelas cuja view entrega todos os registros de uma vez (sem
  `paginate_by` e sem `FilterSet`), em que buscar/ordenar no navegador faz
  sentido. Exemplo no projeto: **IA → IA por usuário** (`ia/templates/ia/usuarios_ia.html`).
- **Não use** em listas paginadas ou filtradas no servidor (Minhas Reservas,
  Pedidos Pendentes, Todas as Reservas, Disponibilidade, Requisições da IA):
  lá o DataTables buscaria e ordenaria só a página atual, enganando o
  usuário. Essas listas seguem as skills `django-paginacao` e `django-filter-listagens`.

## A base (já existe — não recrie)

- `website/templates/website/modelo.html` carrega, do cdnjs e com versão fixa:
  CSS `datatables.net-bs5/2.1.8/dataTables.bootstrap5.min.css` no `<head>` e,
  no fim do `<body>`, jQuery 3.7.1 → `datatables.net/2.1.8/dataTables.min.js`
  → `datatables.net-bs5/2.1.8/dataTables.bootstrap5.min.js` → Bootstrap → `static/js/site.js`.
- `static/js/site.js` inicializa toda `<table class="table-datatable">` com a
  mesma configuração: 10 por página, busca, ordenação, tradução pt-BR inline.
- Não carregue o DataTables de novo num template nem chame `.DataTable(...)`
  fora do `site.js`.

## Padrão da tabela

1. `<table class="table table-striped table-hover align-middle table-datatable">`
   com `<thead class="table-light">` de uma única linha.
2. A view **não** pagina (`paginate_by` ausente) e não inclui `_paginacao.html`.
   Se a quantidade de linhas puder crescer muito (milhares), não é caso de
   DataTables: pagine no servidor.
3. A view entrega tudo que a tabela mostra numa consulta só
   (`annotate`/`select_related`) — nada de query por linha.
4. Data: exibe no padrão brasileiro e ordena pelo ISO:
   `<td data-order="{{ obj.campo|date:'Y-m-d' }}">{{ obj.campo|date:"d/m/Y" }}</td>`.
5. Número com separador brasileiro (moeda, tokens): `data-order` com o valor puro
   (`{{ obj.valor|stringformat:'d' }}` ou `'.2f'`).
6. Coluna de ações: `<th data-orderable="false" data-searchable="false">Ações</th>`.
7. Lista vazia: deixe o `<tbody>` vazio (sem `{% empty %}` com `colspan`) — o
   DataTables mostra "Nenhum registro encontrado". Toda linha tem exatamente
   uma `<td>` por `<th>`, sem `colspan`/`rowspan`.
8. Cabeçalhos em português, com o nome que o usuário entende.

## Testes

- A página tem `table-datatable` e a view não pagina (`is_paginated` ausente/False).
- As listas paginadas continuam **sem** `table-datatable`
  (`website.tests.PluginsJQueryTest`).
- Conferência no navegador: aparece a caixa "Buscar:", a paginação do
  DataTables em português e a ordenação por coluna funciona.
