from .ia import ia_habilitada
from .services import usuario_eh_admin


def perfil(request):
    """``eh_admin`` para os templates (menu Admin, botões da administração).

    Usa a mesma regra do AdminRequiredMixin, calculada uma vez por requisição.
    """
    return {'eh_admin': usuario_eh_admin(getattr(request, 'user', None))}


def chatbot(request):
    """Dados do widget do assistente, presente em todas as páginas (modelo.html)."""
    sessao = getattr(request, 'session', None)
    return {
        'ia_habilitada': ia_habilitada(),
        'chat_historico': sessao.get('chat_ia', []) if sessao is not None else [],
    }
