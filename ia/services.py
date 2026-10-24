"""Única porta de entrada para a IA no sistema.

Assistente, bot do Telegram e análise de pedidos chamam ``chamar_ia``; nenhum
outro módulo fala com o SDK do provedor. ``chamar_ia`` confere a
configuração, a chave, a habilitação e a cota do usuário, chama o provedor
com timeout e grava SEMPRE uma ``RequisicaoIA`` (auditoria).
"""
import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from .excecoes import MENSAGEM_FALHA, CotaExcedida, ErroIA, ErroProvedorIA, IADesativada
from .models import ConfiguracaoIA, PerfilIAUsuario, RequisicaoIA
from .provedores import obter_provedor

__all__ = [
    'ErroIA', 'IADesativada', 'CotaExcedida', 'ErroProvedorIA', 'RespostaIA',
    'chamar_ia', 'consumo_do_mes', 'cota_do_usuario', 'usuario_habilitado', 'perfil_ia',
    'testar_conexao', 'chave_configurada', 'ia_disponivel', 'inicio_do_mes', 'ORIGENS_COM_COTA',
]

logger = logging.getLogger(__name__)

Origem = RequisicaoIA.Origem

# Só o uso interativo conta na cota do usuário e respeita a habilitação dele.
# A análise de pedido é do sistema (apoio à administradora) e o teste é do admin.
ORIGENS_COM_COTA = (Origem.ASSISTENTE, Origem.BOT)


@dataclass(frozen=True)
class RespostaIA:
    texto: str
    tokens_entrada: int
    tokens_saida: int
    sucesso: bool
    erro: str
    requisicao_id: int | None


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def chave_configurada():
    """Há credencial no ambiente? (nunca expõe o valor)."""
    return bool(settings.GEMINI_API_KEY) or settings.GEMINI_USAR_VERTEX


def ia_disponivel(config=None):
    """IA ligada na configuração e com credencial."""
    return chave_configurada() and (config or ConfiguracaoIA.obter()).ativo


def inicio_do_mes():
    """Primeiro instante do mês corrente no fuso do site."""
    agora = timezone.localtime()
    return agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def consumo_do_mes(usuario):
    """Tokens gastos pelo usuário no mês corrente (só as origens com cota)."""
    total = (
        RequisicaoIA.objects
        .filter(usuario=usuario, origem__in=ORIGENS_COM_COTA, criado_em__gte=inicio_do_mes())
        .aggregate(total=Sum('tokens_total'))['total']
    )
    return total or 0


# "Não informado" é diferente de None (= usuário sem perfil, já consultado).
_NAO_INFORMADO = object()


def perfil_ia(usuario):
    """PerfilIAUsuario do usuário, ou None se ele nunca foi configurado."""
    return PerfilIAUsuario.objects.filter(usuario=usuario).first()


def cota_do_usuario(usuario, config=None, perfil=_NAO_INFORMADO):
    """Cota mensal efetiva: a do perfil do usuário ou, se vazia, a padrão."""
    if perfil is _NAO_INFORMADO:
        perfil = perfil_ia(usuario)
    if perfil is not None and perfil.cota_mensal_tokens is not None:
        return perfil.cota_mensal_tokens
    return (config or ConfiguracaoIA.obter()).cota_mensal_padrao_tokens


def usuario_habilitado(usuario, perfil=_NAO_INFORMADO):
    if perfil is _NAO_INFORMADO:
        perfil = perfil_ia(usuario)
    return perfil is None or perfil.habilitado


# ---------------------------------------------------------------------------
# Chamada
# ---------------------------------------------------------------------------

def formatar_milhar(numero):
    """50000 -> '50.000' (separador brasileiro)."""
    return f'{numero:,}'.replace(',', '.')


def _truncar(texto, limite):
    texto = texto or ''
    return texto if len(texto) <= limite else texto[:limite - 1] + '…'


def _sem_segredo(texto):
    """Garante que a chave nunca vá parar na auditoria, mesmo dentro de uma mensagem de erro."""
    chave = settings.GEMINI_API_KEY
    return texto.replace(chave, '***') if chave else texto


def _texto_do_prompt(mensagens):
    rotulos = {'usuario': 'Usuário', 'assistente': 'Assistente'}
    return '\n\n'.join(f"{rotulos.get(m['papel'], m['papel'])}: {m['conteudo']}" for m in mensagens)


def _verificar_acesso(config, usuario, origem):
    if origem != Origem.TESTE and not config.ativo:
        raise IADesativada('O assistente de IA está desativado no momento.')
    if not chave_configurada():
        raise IADesativada('A IA não está configurada no servidor (falta a chave da API).')
    if usuario is None or origem not in ORIGENS_COM_COTA:
        return
    perfil = perfil_ia(usuario)
    if not usuario_habilitado(usuario, perfil):
        raise IADesativada('O uso da IA está desabilitado para a sua conta. Fale com a administradora.')
    cota = cota_do_usuario(usuario, config, perfil)
    if consumo_do_mes(usuario) >= cota:
        raise CotaExcedida(
            f'Você atingiu a sua cota mensal de {formatar_milhar(cota)} tokens de IA. '
            'Ela é renovada no dia 1º do próximo mês.')


def chamar_ia(usuario, mensagens, origem, instrucoes_sistema=None, *,
              formato_json=False, timeout_segundos=None):
    """Envia a conversa ao provedor configurado e devolve uma RespostaIA.

    usuario: User (ou None para chamadas do sistema).
    mensagens: [{'papel': 'usuario'|'assistente', 'conteudo': '...'}], em ordem.
    origem: RequisicaoIA.Origem.

    Levanta IADesativada ou CotaExcedida ANTES de chamar o provedor (nada é
    gravado, pois nada foi enviado). Falha do provedor não levanta exceção:
    fica auditada e volta como RespostaIA(sucesso=False, erro=<mensagem amigável>).
    """
    if not mensagens or mensagens[-1].get('papel') != 'usuario':
        raise ValueError('A última mensagem enviada à IA deve ser do usuário.')
    if usuario is not None and not getattr(usuario, 'is_authenticated', False):
        usuario = None

    config = ConfiguracaoIA.obter()
    _verificar_acesso(config, usuario, origem)

    provedor = obter_provedor(config.provedor)
    inicio = time.monotonic()
    resultado, erro_tecnico, erro_amigavel = None, '', ''
    try:
        resultado = provedor.gerar(
            modelo=config.modelo,
            mensagens=mensagens,
            instrucoes_sistema=instrucoes_sistema,
            temperatura=config.temperatura,
            max_tokens=config.max_tokens_resposta,
            timeout_segundos=timeout_segundos or config.timeout_segundos,
            formato_json=formato_json,
        )
    except ErroProvedorIA as erro:
        erro_tecnico, erro_amigavel = erro.detalhe, str(erro)
    except Exception as erro:  # bug no provedor: registra e segue sem derrubar a página
        logger.exception('Erro inesperado no provedor de IA.')
        erro_tecnico, erro_amigavel = f'{type(erro).__name__}: {erro}', MENSAGEM_FALHA
    duracao_ms = int((time.monotonic() - inicio) * 1000)

    if resultado is not None and not resultado.texto:
        erro_tecnico, erro_amigavel = 'O provedor devolveu uma resposta vazia.', MENSAGEM_FALHA
    sucesso = not erro_tecnico

    requisicao = RequisicaoIA.objects.create(
        usuario=usuario,
        origem=origem,
        modelo=config.modelo,
        prompt=_truncar(_texto_do_prompt(mensagens), RequisicaoIA.LIMITE_PROMPT),
        resposta=_truncar(resultado.texto if resultado else '', RequisicaoIA.LIMITE_RESPOSTA),
        tokens_entrada=resultado.tokens_entrada if resultado else 0,
        tokens_saida=resultado.tokens_saida if resultado else 0,
        tokens_total=resultado.tokens_total if resultado else 0,
        duracao_ms=duracao_ms,
        sucesso=sucesso,
        erro=_truncar(_sem_segredo(erro_tecnico), RequisicaoIA.LIMITE_ERRO),
    )
    if not sucesso:
        logger.warning('Chamada à IA #%s falhou: %s', requisicao.pk, requisicao.erro)
    return RespostaIA(
        texto=resultado.texto if sucesso else '',
        tokens_entrada=requisicao.tokens_entrada,
        tokens_saida=requisicao.tokens_saida,
        sucesso=sucesso,
        erro=erro_amigavel,
        requisicao_id=requisicao.pk,
    )


def testar_conexao(usuario):
    """Chamada mínima (origem TESTE) para conferir chave, modelo e rede.

    Ignora o interruptor "ativo" e a cota: serve justamente para testar antes de ligar.
    """
    return chamar_ia(
        usuario,
        [{'papel': 'usuario', 'conteudo': 'Teste de conexão. Responda apenas: OK'}],
        Origem.TESTE,
        instrucoes_sistema='Responda apenas com a palavra OK.',
    )
