"""Provedor Google Gemini (SDK google-genai).

ÚNICO arquivo do projeto que importa o SDK — o teste
``ia.tests.SdkIsoladoTest`` falha se ele aparecer em outro lugar. Todo o
resto do sistema chama ``ia.services.chamar_ia``.

A chave vem só do ambiente (``settings.GEMINI_API_KEY``); nunca do banco.
"""
from functools import lru_cache

from django.conf import settings
from google import genai
from google.genai import errors, types

from ..excecoes import MENSAGEM_FALHA, ErroProvedorIA
from .base import ResultadoProvedor

PAPEIS = {'usuario': 'user', 'assistente': 'model'}


@lru_cache(maxsize=4)
def _cliente(api_key, usar_vertex, projeto, local):
    """Um genai.Client por credencial, reaproveitado entre as chamadas."""
    if usar_vertex:
        # Identidade de serviço do App Engine (Vertex AI), sem API Key.
        # No google-genai 2.x o parâmetro é "enterprise" ("vertexai" é o nome antigo).
        return genai.Client(enterprise=True, project=projeto, location=local)
    return genai.Client(api_key=api_key)


def _config_raciocinio(modelo):
    """Raciocínio (thinking) no mínimo: respostas diretas e menos tokens de saída.

    Gemini 2.x usa orçamento (0 desliga); os 3.x usam níveis — o menor é
    MINIMAL, exceto nos modelos Pro, que começam em LOW.
    """
    if modelo.startswith('gemini-2'):
        return types.ThinkingConfig(thinking_budget=0)
    if '-pro' in modelo:
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def _inteiro(valor):
    return valor if isinstance(valor, int) else 0


def gerar(*, modelo, mensagens, instrucoes_sistema=None, temperatura=None,
          max_tokens=None, timeout_segundos=20, formato_json=False):
    """Envia a conversa ao Gemini e devolve um ResultadoProvedor.

    mensagens: [{'papel': 'usuario'|'assistente', 'conteudo': '...'}, ...]
    Qualquer falha vira ErroProvedorIA (o detalhe técnico vai para a auditoria).
    """
    conteudos = [
        types.Content(role=PAPEIS[m['papel']], parts=[types.Part(text=m['conteudo'])])
        for m in mensagens
    ]
    config = types.GenerateContentConfig(
        system_instruction=instrucoes_sistema or None,
        temperature=float(temperatura) if temperatura is not None else None,
        max_output_tokens=max_tokens,
        response_mime_type='application/json' if formato_json else None,
        thinking_config=_config_raciocinio(modelo),
        # O timeout do HttpOptions é em MILISSEGUNDOS.
        http_options=types.HttpOptions(timeout=int(timeout_segundos * 1000)),
    )
    try:
        resposta = _cliente(
            settings.GEMINI_API_KEY, settings.GEMINI_USAR_VERTEX,
            settings.GOOGLE_CLOUD_PROJECT, settings.GOOGLE_CLOUD_LOCATION,
        ).models.generate_content(model=modelo, contents=conteudos, config=config)
    except errors.APIError as erro:
        amigavel = ('A IA está recebendo muitas solicitações agora. Tente novamente em instantes.'
                    if erro.code == 429 else MENSAGEM_FALHA)
        raise ErroProvedorIA(f'Gemini HTTP {erro.code} {erro.status}: {erro.message}', amigavel) from erro
    except Exception as erro:  # timeout, rede, DNS...
        nome = type(erro).__name__
        amigavel = ('A IA demorou demais para responder. Tente novamente.'
                    if 'Timeout' in nome else MENSAGEM_FALHA)
        raise ErroProvedorIA(f'Falha de comunicação com o Gemini ({nome}): {erro}', amigavel) from erro

    uso = getattr(resposta, 'usage_metadata', None)
    entrada = _inteiro(getattr(uso, 'prompt_token_count', None))
    # Tokens de raciocínio (thoughts) são cobrados como saída.
    saida = (_inteiro(getattr(uso, 'candidates_token_count', None))
             + _inteiro(getattr(uso, 'thoughts_token_count', None)))
    total = _inteiro(getattr(uso, 'total_token_count', None)) or entrada + saida
    return ResultadoProvedor(
        texto=(resposta.text or '').strip(),
        tokens_entrada=entrada, tokens_saida=saida, tokens_total=total,
    )
