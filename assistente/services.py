"""Regras do assistente virtual: janela de histórico, instruções e gravação.

A chamada à IA passa por ia.services.chamar_ia (auditoria, cota, habilitação).
"""
from django.db import transaction
from django.utils import timezone

from ia.models import RequisicaoIA
from ia.services import chamar_ia

from .contexto import montar_contexto
from .instrucoes import INSTRUCOES_SISTEMA
from .models import MensagemAssistente

# Para a IA vão só as 5 últimas mensagens da conversa (incluindo a pergunta
# atual): o histórico inteiro é reenviado a cada pergunta e o custo de
# entrada cresceria sem limite.
JANELA_HISTORICO = 5
MAX_CARACTERES_PERGUNTA = 500


def montar_instrucoes():
    """Regras fixas + contexto do site + dados atuais (sem dados de clientes)."""
    return f'{INSTRUCOES_SISTEMA}\n\n# CONTEXTO\n\n{montar_contexto()}'


def historico(usuario):
    return MensagemAssistente.objects.filter(usuario=usuario).order_by('criado_em', 'id')


def janela_de_mensagens(usuario, pergunta):
    """As JANELA_HISTORICO - 1 últimas mensagens guardadas + a pergunta atual."""
    anteriores = list(
        MensagemAssistente.objects
        .filter(usuario=usuario)
        .order_by('-criado_em', '-id')[:JANELA_HISTORICO - 1]
    )
    anteriores.reverse()
    return [m.como_mensagem_ia() for m in anteriores] + [
        {'papel': MensagemAssistente.USUARIO, 'conteudo': pergunta}
    ]


def perguntar(usuario, pergunta, origem=RequisicaoIA.Origem.ASSISTENTE, usar_historico=True):
    """Faz a pergunta à IA. Levanta IADesativada/CotaExcedida (de chamar_ia).

    Com sucesso e usar_historico=True, grava a pergunta e a resposta no
    histórico do usuário (as duas juntas, para a conversa sempre alternar
    usuário/assistente). Com falha do provedor nada é gravado no histórico
    (a falha fica só na auditoria). Devolve a RespostaIA.
    """
    perguntado_em = timezone.now()
    mensagens = (janela_de_mensagens(usuario, pergunta) if usar_historico
                 else [{'papel': MensagemAssistente.USUARIO, 'conteudo': pergunta}])
    resposta = chamar_ia(usuario, mensagens, origem, montar_instrucoes())
    if resposta.sucesso and usar_historico:
        with transaction.atomic():
            MensagemAssistente.objects.create(
                usuario=usuario, papel=MensagemAssistente.USUARIO, conteudo=pergunta,
                criado_em=perguntado_em, requisicao_id=resposta.requisicao_id)
            MensagemAssistente.objects.create(
                usuario=usuario, papel=MensagemAssistente.ASSISTENTE, conteudo=resposta.texto,
                requisicao_id=resposta.requisicao_id)
    return resposta


def limpar_conversa(usuario):
    """Apaga só as mensagens do próprio usuário. Devolve quantas foram apagadas."""
    apagadas, _ = MensagemAssistente.objects.filter(usuario=usuario).delete()
    return apagadas
