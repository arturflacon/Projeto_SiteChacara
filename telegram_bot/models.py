import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils import timezone


class VinculoTelegram(models.Model):
    """Liga uma conversa privada do Telegram a um usuário do site."""

    usuario = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='vinculo_telegram',
        verbose_name='Usuário', help_text='Usuário do site dono desta conversa.'
    )
    chat_id = models.BigIntegerField(
        unique=True,
        verbose_name='Chat', help_text='Identificador da conversa privada no Telegram.'
    )
    telegram_user_id = models.BigIntegerField(
        verbose_name='Usuário no Telegram', help_text='Identificador da conta do Telegram que fez o vínculo.'
    )
    username = models.CharField(
        max_length=64, blank=True,
        verbose_name='@ no Telegram', help_text='Nome de usuário do Telegram (pode estar vazio).'
    )
    vinculado_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Vinculado em', help_text='Data e hora do vínculo.'
    )

    class Meta:
        verbose_name = 'Vínculo com o Telegram'
        verbose_name_plural = 'Vínculos com o Telegram'

    def __str__(self):
        return f"{self.usuario.username} ↔ Telegram {self.username or self.telegram_user_id}"


class CodigoVinculacao(models.Model):
    """Código de uso único, gerado no site, para vincular a conta ao bot."""

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='codigos_telegram',
        verbose_name='Usuário', help_text='Quem gerou o código no site.'
    )
    codigo = models.CharField(
        max_length=64, unique=True,
        verbose_name='Código', help_text='Gerado com secrets; vale uma vez e por pouco tempo.'
    )
    criado_em = models.DateTimeField(
        default=timezone.now,
        verbose_name='Criado em', help_text='Data e hora em que o código foi gerado.'
    )
    expira_em = models.DateTimeField(
        verbose_name='Expira em', help_text='Depois disso o código é recusado.'
    )
    usado_em = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Usado em', help_text='Preenchido quando o código é consumido (uso único).'
    )

    class Meta:
        verbose_name = 'Código de vinculação'
        verbose_name_plural = 'Códigos de vinculação'
        ordering = ['-criado_em']

    def __str__(self):
        return f"Código de {self.usuario.username} ({'usado' if self.usado_em else 'em aberto'})"

    @property
    def valido(self):
        return self.usado_em is None and self.expira_em > timezone.now()

    @classmethod
    def gerar_para(cls, usuario):
        """Novo código para o usuário; os anteriores ainda não usados deixam de valer."""
        cls.objects.filter(usuario=usuario, usado_em__isnull=True).delete()
        agora = timezone.now()
        return cls.objects.create(
            usuario=usuario,
            # token_urlsafe usa só A-Z a-z 0-9 _ - (aceitos no link t.me/...?start=)
            codigo=secrets.token_urlsafe(12),
            criado_em=agora,
            expira_em=agora + timedelta(minutes=settings.TELEGRAM_CODIGO_VALIDADE_MINUTOS),
        )


class MensagemTelegram(models.Model):
    """Log de toda mensagem que entra no bot ou sai dele."""

    ENTRADA = 'ENTRADA'
    SAIDA = 'SAIDA'
    DIRECAO_CHOICES = [(ENTRADA, 'Entrada'), (SAIDA, 'Saída')]

    MENSAGEM = 'MENSAGEM'
    COMANDO = 'COMANDO'
    CALLBACK = 'CALLBACK'
    TIPO_CHOICES = [(MENSAGEM, 'Mensagem'), (COMANDO, 'Comando'), (CALLBACK, 'Botão (callback)')]

    LIMITE_TEXTO = 1000

    direcao = models.CharField(
        max_length=10, choices=DIRECAO_CHOICES,
        verbose_name='Direção', help_text='Entrada (do Telegram) ou saída (do bot).'
    )
    update_id = models.BigIntegerField(
        null=True, blank=True,
        verbose_name='Update', help_text='update_id do Telegram (só nas entradas; repetido é ignorado).'
    )
    chat_id = models.BigIntegerField(
        null=True, blank=True, verbose_name='Chat', help_text='Conversa do Telegram.'
    )
    telegram_user_id = models.BigIntegerField(
        null=True, blank=True, verbose_name='Remetente', help_text='Conta do Telegram que enviou (entradas).'
    )
    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='mensagens_telegram',
        verbose_name='Usuário', help_text='Usuário do site vinculado (vazio se não vinculado).'
    )
    tipo = models.CharField(
        max_length=10, choices=TIPO_CHOICES,
        verbose_name='Tipo', help_text='Mensagem de texto, comando (/...) ou clique em botão.'
    )
    texto = models.TextField(
        blank=True, verbose_name='Texto', help_text=f'Conteúdo (truncado em {LIMITE_TEXTO} caracteres).'
    )
    aviso_limite = models.BooleanField(
        default=False,
        verbose_name='Aviso de limite', help_text='Saída que avisou o remetente de que passou do limite.'
    )
    criado_em = models.DateTimeField(
        default=timezone.now, verbose_name='Data', help_text='Data e hora do registro.'
    )

    class Meta:
        verbose_name = 'Mensagem do Telegram'
        verbose_name_plural = 'Mensagens do Telegram'
        ordering = ['-criado_em', '-id']
        indexes = [
            models.Index(fields=['telegram_user_id', 'criado_em'], name='tg_msg_remetente_data'),
            models.Index(fields=['chat_id', 'criado_em'], name='tg_msg_chat_data'),
        ]
        constraints = [
            # O Telegram reenvia o mesmo update se não receber 200: a segunda
            # cópia bate nesta restrição e é descartada.
            models.UniqueConstraint(fields=['update_id'], condition=Q(direcao='ENTRADA'),
                                    name='tg_update_id_unico_na_entrada'),
        ]

    def __str__(self):
        return f"{self.get_direcao_display()} {self.get_tipo_display()} — {self.texto[:40]}"


class TentativaVinculoInvalida(models.Model):
    """Código de vínculo errado/expirado/usado. Serve para limitar tentativas por remetente."""

    telegram_user_id = models.BigIntegerField(
        verbose_name='Remetente', help_text='Conta do Telegram que tentou.'
    )
    criado_em = models.DateTimeField(
        default=timezone.now, verbose_name='Data', help_text='Data e hora da tentativa.'
    )

    class Meta:
        verbose_name = 'Tentativa de vínculo inválida'
        verbose_name_plural = 'Tentativas de vínculo inválidas'
        indexes = [models.Index(fields=['telegram_user_id', 'criado_em'], name='tg_tentativa_remetente_data')]

    def __str__(self):
        return f"{self.telegram_user_id} em {self.criado_em:%d/%m/%Y %H:%M}"
