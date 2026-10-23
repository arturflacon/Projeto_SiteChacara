from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

MODELO_PADRAO = 'gemini-3.5-flash-lite'


class ConfiguracaoIA(models.Model):
    """Configuração única (singleton) da IA, editável em IA → Configuração.

    A chave da API NÃO fica aqui: vem só da variável de ambiente GEMINI_API_KEY.
    """

    PROVEDOR_GEMINI = 'GEMINI'
    PROVEDOR_CHOICES = [(PROVEDOR_GEMINI, 'Google Gemini')]

    ativo = models.BooleanField(
        default=True,
        verbose_name='IA ativa', help_text='Desligue para suspender o assistente, o bot e a análise de pedidos.'
    )
    provedor = models.CharField(
        max_length=20, choices=PROVEDOR_CHOICES, default=PROVEDOR_GEMINI,
        verbose_name='Provedor', help_text='Serviço de IA usado nas chamadas.'
    )
    modelo = models.CharField(
        max_length=100, default=MODELO_PADRAO,
        verbose_name='Modelo', help_text='Código do modelo no provedor, ex.: gemini-3.5-flash-lite.'
    )
    temperatura = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal('0.70'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('2'))],
        verbose_name='Temperatura', help_text='0 = respostas mais previsíveis; 2 = mais criativas.'
    )
    max_tokens_resposta = models.PositiveIntegerField(
        default=1024, validators=[MinValueValidator(16), MaxValueValidator(8192)],
        verbose_name='Máximo de tokens por resposta', help_text='Limite de tamanho de cada resposta (16 a 8192).'
    )
    timeout_segundos = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(120)],
        verbose_name='Tempo limite (segundos)', help_text='Depois disso a chamada é abandonada e registrada como erro.'
    )
    cota_mensal_padrao_tokens = models.PositiveIntegerField(
        default=50_000,
        verbose_name='Cota mensal padrão (tokens)',
        help_text='Tokens por usuário por mês no assistente e no bot, quando o usuário não tem cota própria.'
    )
    atualizado_em = models.DateTimeField(
        auto_now=True,
        verbose_name='Atualizado em', help_text='Data e hora da última alteração.'
    )
    atualizado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name='Atualizado por', help_text='Quem fez a última alteração.'
    )

    class Meta:
        verbose_name = 'Configuração da IA'
        verbose_name_plural = 'Configuração da IA'

    def __str__(self):
        return f"{self.get_provedor_display()} — {self.modelo} ({'ativa' if self.ativo else 'desativada'})"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton: sempre a mesma linha
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # A configuração não pode sumir; para desligar a IA use o campo "ativo".
        return 0, {}

    @classmethod
    def obter(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class PerfilIAUsuario(models.Model):
    """Habilitação e cota de IA de um usuário (sem perfil = habilitado, cota padrão)."""

    usuario = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='perfil_ia',
        verbose_name='Usuário', help_text='Usuário a quem esta configuração se aplica.'
    )
    habilitado = models.BooleanField(
        default=True,
        verbose_name='Pode usar a IA', help_text='Desmarque para bloquear o assistente e o /perguntar do bot.'
    )
    cota_mensal_tokens = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='Cota mensal (tokens)', help_text='Vazio = usa a cota padrão da configuração.'
    )

    class Meta:
        verbose_name = 'IA por usuário'
        verbose_name_plural = 'IA por usuário'

    def __str__(self):
        cota = 'cota padrão' if self.cota_mensal_tokens is None else f'{self.cota_mensal_tokens} tokens/mês'
        return f"{self.usuario.username} — {'habilitado' if self.habilitado else 'bloqueado'}, {cota}"


class RequisicaoIA(models.Model):
    """Auditoria de TODA chamada à IA, com sucesso ou com erro."""

    class Origem(models.TextChoices):
        ASSISTENTE = 'ASSISTENTE', 'Assistente do site'
        BOT = 'BOT', 'Bot do Telegram'
        ANALISE = 'ANALISE', 'Análise de pedido'
        TESTE = 'TESTE', 'Teste de conexão'

    LIMITE_PROMPT = 4000
    LIMITE_RESPOSTA = 10000
    LIMITE_ERRO = 1000

    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='requisicoes_ia',
        verbose_name='Usuário', help_text='Quem originou a chamada (vazio = sistema).'
    )
    origem = models.CharField(
        max_length=20, choices=Origem.choices,
        verbose_name='Origem', help_text='De onde veio a chamada.'
    )
    modelo = models.CharField(
        max_length=100, blank=True,
        verbose_name='Modelo', help_text='Modelo usado na chamada.'
    )
    prompt = models.TextField(
        blank=True,
        verbose_name='Prompt', help_text=f'Mensagens enviadas (até {LIMITE_PROMPT} caracteres; sem as instruções de sistema).'
    )
    resposta = models.TextField(
        blank=True,
        verbose_name='Resposta', help_text='Texto devolvido pelo modelo.'
    )
    tokens_entrada = models.PositiveIntegerField(
        default=0, verbose_name='Tokens de entrada', help_text='Instruções + histórico + mensagem.'
    )
    tokens_saida = models.PositiveIntegerField(
        default=0, verbose_name='Tokens de saída', help_text='Resposta + raciocínio do modelo.'
    )
    tokens_total = models.PositiveIntegerField(
        default=0, verbose_name='Tokens no total', help_text='É o que conta na cota mensal.'
    )
    duracao_ms = models.PositiveIntegerField(
        default=0, verbose_name='Duração (ms)', help_text='Tempo de resposta do provedor.'
    )
    sucesso = models.BooleanField(
        default=False, verbose_name='Sucesso', help_text='Falso quando o provedor falhou ou não respondeu.'
    )
    erro = models.TextField(
        blank=True, verbose_name='Erro', help_text='Detalhe técnico da falha (vazio em caso de sucesso).'
    )
    # default (e não auto_now_add) para a migration poder copiar a data dos registros antigos.
    criado_em = models.DateTimeField(
        default=timezone.now, editable=False,
        verbose_name='Data', help_text='Data e hora da chamada.'
    )

    class Meta:
        verbose_name = 'Requisição à IA'
        verbose_name_plural = 'Requisições à IA'
        ordering = ['-criado_em']
        indexes = [models.Index(fields=['usuario', 'criado_em'], name='ia_requisicao_usuario_data')]

    def __str__(self):
        return f"{self.get_origem_display()} — {self.criado_em:%d/%m/%Y %H:%M} ({self.tokens_total} tokens)"

    @property
    def custo_usd(self):
        """Estimativa pelos preços do settings (US$ por token de entrada/saída)."""
        entrada = Decimal(str(settings.GEMINI_PRECO_ENTRADA_USD))
        saida = Decimal(str(settings.GEMINI_PRECO_SAIDA_USD))
        return (self.tokens_entrada * entrada + self.tokens_saida * saida).quantize(Decimal('0.00000001'))

    @property
    def custo_brl(self):
        return self.custo_usd * Decimal(str(settings.GEMINI_COTACAO_BRL))
