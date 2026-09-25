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
