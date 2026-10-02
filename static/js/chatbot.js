// Assistente virtual do Sítio de Lurdes (Gemini).
// Segurança: todo texto (do usuário ou da IA) entra na página com .text(),
// nunca com .html() — assim nenhum HTML vindo do modelo é interpretado.
$(function () {
  var $painel = $('#chatbot');
  if (!$painel.length) return;

  var urlMensagem = $painel.data('url-mensagem');
  var urlLimpar = $painel.data('url-limpar');
  var habilitado = $painel.data('habilitado') === 1;
  var $lista = $('#chatbot-mensagens');
  var $sugestoes = $('#chatbot-sugestoes');
  var $form = $('#chatbot-form');
  var $campo = $('#chatbot-texto');
  var $digitando = $('#chatbot-digitando');
  var $botoes = $form.find('button');
  var enviando = false;

  function csrfToken() {
    var achado = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (achado) return decodeURIComponent(achado[1]);
    return $form.find('input[name=csrfmiddlewaretoken]').val() || '';
  }

  function rolarParaOFim() {
    $lista.scrollTop($lista[0].scrollHeight);
  }

  // papel: "user", "model" ou "erro"
  function adicionarBalao(papel, texto) {
    $('<div>').addClass('chat-balao chat-' + papel).text(texto).appendTo($lista);
    rolarParaOFim();
  }

  // Histórico que já estava na sessão (renderizado pelo json_script do modelo.html)
  var historico = JSON.parse(document.getElementById('chat-historico').textContent || '[]');
  historico.forEach(function (item) {
    adicionarBalao(item.role === 'user' ? 'user' : 'model', item.text);
  });
  if (historico.length) $sugestoes.hide();

  function enviar(texto) {
    texto = $.trim(texto);
    if (!texto || enviando || !habilitado) return;
    enviando = true;
    $sugestoes.hide();
    adicionarBalao('user', texto);
    $campo.val('');
    $botoes.prop('disabled', true);
    $digitando.prop('hidden', false);
    rolarParaOFim();

    $.ajax({
      url: urlMensagem,
      method: 'POST',
      data: { mensagem: texto },
      dataType: 'json',
      headers: { 'X-CSRFToken': csrfToken() }
    }).done(function (dados) {
      adicionarBalao('model', dados.resposta);
    }).fail(function (xhr) {
      var erro = xhr.responseJSON && xhr.responseJSON.erro;
      adicionarBalao('erro', erro || 'Não foi possível falar com o assistente agora.');
    }).always(function () {
      enviando = false;
      $digitando.prop('hidden', true);
      $botoes.prop('disabled', false);
      $campo.trigger('focus');
    });
  }

  $form.on('submit', function (e) {
    e.preventDefault();
    enviar($campo.val());
  });

  // Enter envia; Shift+Enter quebra a linha.
  $campo.on('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      $form.trigger('submit');
    }
  });

  $sugestoes.on('click', 'button', function () {
    enviar($(this).text());
  });

  $('#chatbot-limpar').on('click', function () {
    $.ajax({
      url: urlLimpar,
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken() }
    }).always(function () {
      $lista.find('.chat-user, .chat-erro').remove();
      $lista.find('.chat-model').slice(1).remove();  // mantém só a boas-vindas
      $sugestoes.show();
    });
  });

  $painel.on('shown.bs.offcanvas', function () {
    rolarParaOFim();
    $campo.trigger('focus');
  });
});
