from .ia import ia_habilitada


def chatbot(request):
    """Dados do widget do assistente, presente em todas as páginas (modelo.html)."""
    sessao = getattr(request, 'session', None)
    return {
        'ia_habilitada': ia_habilitada(),
        'chat_historico': sessao.get('chat_ia', []) if sessao is not None else [],
    }
