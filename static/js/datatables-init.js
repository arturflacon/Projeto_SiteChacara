// Transforma toda <table class="table-datatable"> do projeto em DataTable,
// sempre com a mesma configuração — é isso que deixa todas as listas iguais.
// Carregado só nas páginas que usam DataTables (website/datatables-js.html).
$(document).ready(function () {
  $('table.table-datatable').each(function () {
    $(this).DataTable({
      paging: false,      // o Django já pagina a queryset no servidor
      info: false,        // redundante com a paginação do Django
      lengthChange: false,
      order: [],          // mantém a ordem da view até o usuário clicar
      // Tradução pt-BR inline (sem buscar arquivo de idioma em outro site)
      language: {
        search: 'Buscar nesta página:',
        zeroRecords: 'Nenhum registro encontrado',
        emptyTable: 'Nenhum registro encontrado',
        loadingRecords: 'Carregando...',
        processing: 'Processando...',
        aria: {
          orderable: 'Ordenar por esta coluna',
          orderableReverse: 'Inverter a ordem desta coluna'
        }
      }
    });
  });
});
