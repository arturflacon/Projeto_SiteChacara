// Assistente virtual do Sítio de Lurdes (tela /assistente/).
// Envio por fetch (POST) com o cabeçalho X-CSRFToken — a view não usa csrf_exempt.
// Segurança: a pergunta do usuário entra na página com textContent; só o HTML
// da resposta, que o servidor já converteu de Markdown e sanitizou com nh3,
// entra com innerHTML.
(function () {
  'use strict';

  var form = document.getElementById('chat-form');
  if (!form) return;

  var lista = document.getElementById('chat-mensagens');
  var campo = document.getElementById('chat-pergunta');
  var digitando = document.getElementById('chat-digitando');
  var contador = document.getElementById('chat-contador');
  var sugestoes = document.getElementById('chat-sugestoes');
  var botao = form.querySelector('button[type=submit]');
  var limpar = document.getElementById('chat-limpar');
  var enviando = false;

  function csrfToken() {
    return form.querySelector('input[name=csrfmiddlewaretoken]').value;
  }

  function rolarParaOFim() {
    lista.scrollTop = lista.scrollHeight;
  }

  function adicionarBalao(classe) {
    var div = document.createElement('div');
    div.className = 'chat-balao ' + classe;
    lista.appendChild(div);
    return div;
  }

  function balaoUsuario(texto) {
    adicionarBalao('chat-user').textContent = texto;
    rolarParaOFim();
  }

  function balaoAssistente(htmlSanitizado) {
    adicionarBalao('chat-model').innerHTML = htmlSanitizado;
    rolarParaOFim();
  }

  function balaoErro(texto) {
    adicionarBalao('chat-erro').textContent = texto;
    rolarParaOFim();
  }

  function atualizarContador() {
    if (contador) contador.textContent = campo.value.length;
  }

  function enviar(texto) {
    texto = (texto || '').trim();
    if (!texto || enviando || campo.disabled) return;
    enviando = true;
    if (sugestoes) sugestoes.remove();
    balaoUsuario(texto);
    campo.value = '';
    atualizarContador();
    botao.disabled = true;
    digitando.hidden = false;

    fetch(form.dataset.url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ pergunta: texto })
    })
      .then(function (resposta) {
        return resposta.json()
          .catch(function () { return { erro: 'Sua sessão pode ter expirado. Recarregue a página.' }; })
          .then(function (dados) { return { ok: resposta.ok, dados: dados }; });
      })
      .then(function (resultado) {
        if (resultado.ok && resultado.dados.resposta_html) {
          balaoAssistente(resultado.dados.resposta_html);
          if (limpar) limpar.disabled = false;  // agora há conversa para apagar
        } else {
          balaoErro(resultado.dados.erro || 'Não foi possível falar com o assistente agora.');
        }
      })
      .catch(function () {
        balaoErro('Não foi possível falar com o assistente agora. Verifique sua conexão.');
      })
      .finally(function () {
        enviando = false;
        digitando.hidden = true;
        botao.disabled = false;
        campo.focus();
        rolarParaOFim();
      });
  }

  form.addEventListener('submit', function (evento) {
    evento.preventDefault();
    enviar(campo.value);
  });

  // Enter envia; Shift+Enter quebra a linha.
  campo.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter' && !evento.shiftKey) {
      evento.preventDefault();
      enviar(campo.value);
    }
  });
  campo.addEventListener('input', atualizarContador);

  if (sugestoes) {
    sugestoes.addEventListener('click', function (evento) {
      if (evento.target.tagName === 'BUTTON') enviar(evento.target.textContent);
    });
  }

  rolarParaOFim();
})();
