// Calendário da página Disponibilidade (FullCalendar 6, carregado no template).
// Mostra só as reservas CONFIRMADAS: os eventos vêm da view via
// {{ eventos|json_script:"eventos-data" }}, sem dados digitados no JS.
$(function () {
  'use strict';

  var elemento = document.getElementById('calendario');
  var dados = document.getElementById('eventos-data');
  if (!elemento || !dados || !window.FullCalendar) return;

  var calendario = new FullCalendar.Calendar(elemento, {
    initialView: 'dayGridMonth',
    locale: 'pt-br',
    height: 'auto',
    headerToolbar: { left: 'prev,next today', center: 'title', right: '' },
    events: JSON.parse(dados.textContent)
  });
  calendario.render();
});
