from .services import usuario_eh_admin


def perfil(request):
    """``eh_admin`` para os templates (menu Admin, botões da administração).

    Usa a mesma regra do AdminRequiredMixin, calculada uma vez por requisição.
    """
    return {'eh_admin': usuario_eh_admin(getattr(request, 'user', None))}
