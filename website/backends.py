from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class BackendComPerfil(ModelBackend):
    """Igual ao ModelBackend, mas carrega o usuário já com os perfis.

    Toda página com usuário logado consulta ``user.cliente`` e
    ``user.administrador`` (navbar, permissões). Com o select_related, os dois
    vêm no mesmo SELECT da sessão: 2 consultas a menos por requisição.
    """

    def get_user(self, user_id):
        User = get_user_model()
        try:
            user = User._default_manager.select_related('cliente', 'administrador').get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
