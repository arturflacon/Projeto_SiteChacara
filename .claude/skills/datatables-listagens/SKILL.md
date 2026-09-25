---
name: datatables-listagens
description: Use sempre que for criar ou editar um template de listagem neste projeto Django — ListView, template *_list.html ou qualquer <table> que mostre registros de um queryset — para que toda lista use o DataTables do mesmo jeito: em português, com o tema do Bootstrap 5, busca e ordenação por coluna, sem paginação duplicada e com moeda e data brasileiras ordenando certo via data-sort.
---

## Antes de mexer em qualquer template

Confira se a base já está instalada. Se faltar algo, instale primeiro, uma única vez:

1. No `base.html`, depois do Bootstrap 5:
   - CSS no `<head>`: `https://cdn.datatables.net/2.1.8/css/dataTables.bootstrap5.min.css`
   - JS antes de `</body>`, nesta ordem: jQuery 3.7.1
     (`https://code.jquery.com/jquery-3.7.1.min.js`), depois
     `https://cdn.datatables.net/2.1.8/js/dataTables.min.js` e
     `https://cdn.datatables.net/2.1.8/js/dataTables.bootstrap5.min.js`.
   - Se o projeto já carrega jQuery (por causa de Bootbox, jQuery Mask...), não
     carregue de novo: jQuery aparece uma única vez, antes de tudo que depende dele.
2. `static/js/datatables-init.js` existe com exatamente este conteúdo e está incluído
   no `base.html` com `{% static %}`, depois dos scripts do DataTables:

   ```javascript
   // Transforma toda <table class="table-datatable"> do projeto em DataTable,
   // sempre com a mesma configuração — é isso que deixa todas as listas iguais.
   $(document).ready(function () {
     $('table.table-datatable').each(function () {
       $(this).DataTable({
         paging: false,      // o Django já pagina a queryset no servidor
         info: false,        // redundante com a paginação do Django
         lengthChange: false,
         order: [],          // mantém a ordem da view até o usuário clicar
         language: { url: 'https://cdn.datatables.net/plug-ins/2.1.8/i18n/pt-BR.json' }
       });
     });
   });
   ```

## Padrão de toda tabela de listagem

1. A tabela é sempre
   `<table class="table table-striped table-hover align-middle table-datatable">`
   com `<thead class="table-light">`. Não invente outras classes nem estilos por tabela.
2. Nunca chame `.DataTable(...)` dentro de um template. A única inicialização é a do
   `datatables-init.js`.
3. Nunca ligue a paginação do DataTables. O bloco `{% if is_paginated %}` do Django
   continua como está, logo depois da tabela.
4. Coluna de data: exibe no padrão brasileiro e ordena pelo `data-sort` em ISO.
   - `DateField`: `<td data-sort="{{ obj.campo|date:'Y-m-d' }}">{{ obj.campo|date:"d/m/Y" }}</td>`
   - `DateTimeField`: `<td data-sort="{{ obj.campo|date:'Y-m-d H:i' }}">{{ obj.campo|date:"d/m/Y H:i" }}</td>`
5. Coluna de moeda:
   `<td data-sort="{{ obj.valor|stringformat:'.2f' }}">R$ {{ obj.valor|floatformat:"2g" }}</td>`.
   Outros números exibidos com vírgula decimal (quantidade, percentual) também levam
   `data-sort` com `stringformat`.
6. Dentro de `data-sort="..."`, o argumento do filtro usa aspas simples (`'Y-m-d'`)
   para não fechar o atributo HTML.
7. Coluna de ações (Editar, Excluir, Ver) e qualquer coluna sem valor para ordenar:
   `<th data-orderable="false" data-searchable="false">Ações</th>`.
8. Lista vazia: nunca use `{% empty %}` com uma linha `<td colspan="...">` dentro do
   `<tbody>` de uma `table-datatable`. Isso quebra o DataTables. Deixe o `<tbody>`
   vazio; o DataTables mostra "Nenhum registro encontrado" em português.
9. Todo `<tr>` do `<tbody>` tem exatamente uma `<td>` por `<th>` do cabeçalho, sem
   `colspan` nem `rowspan`, e o `<thead>` tem uma única linha.
10. Cabeçalhos em português, com o nome que o usuário entende ("Cadastrado em", não
    "data_cadastro").
