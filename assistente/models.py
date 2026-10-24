from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from ia.models import RequisicaoIA


class MensagemAssistente(models.Model):
    """Uma mensagem da conversa de um usuário com o assistente.

    O conteúdo é guardado como veio (a resposta da IA em Markdown cru); a
    conversão para HTML sanitizado acontece só na exibição (markdown_seguro).
    """

    USUARIO = 'usuario'
    ASSISTENTE = 'assistente'
    PAPEL_CHOICES = [(USUARIO, 'Usuário'), (ASSISTENTE, 'Assistente')]

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='mensagens_assistente',
        verbose_name='Usuário', help_text='Dono da conversa.'
    )
    papel = models.CharField(
        max_length=20, choices=PAPEL_CHOICES,
        verbose_name='Papel', help_text='Quem escreveu: o usuário ou o assistente.'
    )
    conteudo = models.TextField(
        verbose_name='Conteúdo', help_text='Texto da mensagem (Markdown cru, no caso do assistente).'
    )
    criado_em = models.DateTimeField(
        default=timezone.now,
        verbose_name='Enviada em', help_text='Data e hora da mensagem.'
    )
    requisicao = models.ForeignKey(
        RequisicaoIA, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name='Requisição à IA', help_text='Chamada auditada que gerou esta troca.'
    )

    class Meta:
        verbose_name = 'Mensagem do assistente'
        verbose_name_plural = 'Mensagens do assistente'
        ordering = ['criado_em', 'id']
        indexes = [models.Index(fields=['usuario', 'criado_em'], name='assist_msg_usuario_data')]

    def __str__(self):
        return f"{self.get_papel_display()} ({self.usuario.username}): {self.conteudo[:50]}"

    def como_mensagem_ia(self):
        """Formato aceito por ia.services.chamar_ia."""
        return {'papel': self.papel, 'conteudo': self.conteudo}
