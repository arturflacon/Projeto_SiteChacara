"""Chamadas HTTP à API de bots do Telegram (requests, sempre com timeout).

O token entra na URL (https://api.telegram.org/bot<TOKEN>/<método>): por
isso toda mensagem de erro passa por ``sanitizar`` antes de virar exceção
ou log — as exceções do requests trazem a URL completa.
"""
import requests
from django.conf import settings

URL = 'https://api.telegram.org/bot{token}/{metodo}'
LIMITE_TEXTO = 4096          # sendMessage / editMessageText
LIMITE_TEXTO_CALLBACK = 200  # answerCallbackQuery
ATUALIZACOES = ['message', 'callback_query']


class ErroTelegram(Exception):
    """Falha ao falar com a API do Telegram (mensagem já sem o token)."""


def sanitizar(texto):
    texto = str(texto)
    token = settings.TELEGRAM_BOT_TOKEN
    return texto.replace(token, '<TOKEN>') if token else texto


def _post(metodo, dados):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise ErroTelegram('TELEGRAM_BOT_TOKEN não configurado.')
    try:
        resposta = requests.post(
            URL.format(token=token, metodo=metodo), json=dados, timeout=settings.TELEGRAM_TIMEOUT_SEGUNDOS)
        corpo = resposta.json()
    except (requests.RequestException, ValueError) as erro:
        # "from None": a exceção original (com a URL e o token) não vai junto para o traceback.
        raise ErroTelegram(f'Falha ao chamar {metodo}: {sanitizar(erro)}') from None
    if not corpo.get('ok'):
        raise ErroTelegram(sanitizar(f"{metodo} recusado: {corpo.get('error_code')} {corpo.get('description')}"))
    return corpo.get('result')


def _cortar(texto, limite):
    return texto if len(texto) <= limite else texto[:limite - 1] + '…'


def teclado_inline(botoes):
    """[[('Aprovar', 'apr:12'), ('Recusar', 'rec:12')]] -> reply_markup do Telegram."""
    return {'inline_keyboard': [[{'text': texto, 'callback_data': dado} for texto, dado in linha]
                                for linha in botoes]}


def enviar_mensagem(chat_id, texto, teclado=None):
    dados = {'chat_id': chat_id, 'text': _cortar(texto, LIMITE_TEXTO), 'disable_web_page_preview': True}
    if teclado:
        dados['reply_markup'] = teclado
    return _post('sendMessage', dados)


def editar_mensagem(chat_id, message_id, texto, teclado=None):
    dados = {'chat_id': chat_id, 'message_id': message_id, 'text': _cortar(texto, LIMITE_TEXTO)}
    dados['reply_markup'] = teclado or {'inline_keyboard': []}  # sem teclado: os botões somem
    return _post('editMessageText', dados)


def responder_callback(callback_id, texto='', alerta=False):
    return _post('answerCallbackQuery', {
        'callback_query_id': callback_id, 'text': _cortar(texto, LIMITE_TEXTO_CALLBACK), 'show_alert': alerta,
    })


def configurar_webhook(url, segredo):
    return _post('setWebhook', {'url': url, 'secret_token': segredo, 'allowed_updates': ATUALIZACOES})


def info_webhook():
    return _post('getWebhookInfo', {})


def remover_webhook(descartar_pendentes=False):
    return _post('deleteWebhook', {'drop_pending_updates': descartar_pendentes})
