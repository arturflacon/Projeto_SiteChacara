"""Exceções da IA. Ficam num módulo próprio para que os provedores possam
levantá-las sem importar ``ia.services`` (que importa os provedores)."""


MENSAGEM_FALHA = 'Não foi possível obter uma resposta da IA agora. Tente novamente em instantes.'


class ErroIA(Exception):
    """Base de todos os erros da IA. ``str(erro)`` é a mensagem amigável."""


class IADesativada(ErroIA):
    """IA desligada na configuração, sem chave no ambiente ou desabilitada para o usuário."""


class CotaExcedida(ErroIA):
    """O usuário já gastou a cota mensal de tokens."""


class ErroProvedorIA(ErroIA):
    """Falha do provedor (HTTP, timeout, resposta inválida).

    ``detalhe`` é o texto técnico gravado na auditoria; a mensagem amigável
    é a que vai para o usuário.
    """

    def __init__(self, detalhe, mensagem_amigavel=MENSAGEM_FALHA):
        super().__init__(mensagem_amigavel)
        self.detalhe = detalhe
