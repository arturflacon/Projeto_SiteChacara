from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone


class Cliente(models.Model):
    nome = models.CharField(max_length=255, verbose_name='Nome Completo', help_text='Nome completo do cliente.')
    telefone = models.CharField(max_length=11, verbose_name='Telefone', help_text='Número de telefone (somente dígitos).')
    usuario = models.OneToOneField(User, on_delete=models.PROTECT, verbose_name='Usuário', help_text='Usuário associado a este cliente.')

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'

    def __str__(self):
        return self.nome


class Administrador(models.Model):
    nome = models.CharField(max_length=255, verbose_name='Nome Completo', help_text='Nome completo do administrador.')
    usuario = models.OneToOneField(User, on_delete=models.PROTECT, verbose_name='Usuário', help_text='Usuário associado a este administrador.')

    class Meta:
        verbose_name = 'Administrador'
        verbose_name_plural = 'Administradores'

    def __str__(self):
        return self.nome


class Chacara(models.Model):
    nome = models.CharField(max_length=255, verbose_name='Nome da Chácara', help_text='Nome da chácara para aluguel.')
    descricao = models.TextField(verbose_name='Descrição', help_text='Descrição detalhada da chácara.')
    preco_diaria = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Preço da Diária', help_text='Preço por diária em reais.')
    tem_estacionamento = models.BooleanField(default=False, verbose_name='Tem Estacionamento', help_text='Indica se a chácara possui estacionamento.')
    tem_piscina = models.BooleanField(default=False, verbose_name='Tem Piscina', help_text='Indica se a chácara possui piscina.')
    tem_churrasqueira = models.BooleanField(default=False, verbose_name='Tem Churrasqueira', help_text='Indica se a chácara possui churrasqueira.')
    num_quartos = models.IntegerField(verbose_name='Número de Quartos', help_text='Quantidade de quartos disponíveis.')
    num_banheiros = models.IntegerField(verbose_name='Número de Banheiros', help_text='Quantidade de banheiros disponíveis.')

    class Meta:
        verbose_name = 'Chácara'
        verbose_name_plural = 'Chácaras'

    def __str__(self):
        return self.nome


class Reserva(models.Model):
    STATUS_PENDENTE = 'PENDENTE'
    STATUS_CONFIRMADA = 'CONFIRMADA'
    STATUS_RECUSADA = 'RECUSADA'
    STATUS_CANCELADA = 'CANCELADA'

    STATUS_CHOICES = [
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_CONFIRMADA, 'Confirmada'),
        (STATUS_RECUSADA, 'Recusada'),
        (STATUS_CANCELADA, 'Cancelada'),
    ]

    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT,
        verbose_name='Cliente', help_text='Cliente que realizou o pedido de reserva.'
    )
    chacara = models.ForeignKey(
        Chacara, on_delete=models.PROTECT,
        verbose_name='Chácara', help_text='Chácara que está sendo reservada.'
    )
    data_inicio = models.DateField(
        verbose_name='Data de Início', help_text='Data de chegada na chácara.'
    )
    data_fim = models.DateField(
        verbose_name='Data de Fim',
        help_text='Data de saída da chácara (deve ser posterior à data de chegada).'
    )
    valor_total = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Valor Total', help_text='Calculado automaticamente: diária × número de dias.'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDENTE,
        verbose_name='Status', help_text='Status atual da reserva.'
    )
    data_pedido = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Data do Pedido', help_text='Data e hora em que o pedido foi feito.'
    )
    data_decisao = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Data da Decisão', help_text='Data e hora em que o pedido foi aprovado ou recusado.'
    )
    observacoes = models.TextField(
        blank=True,
        verbose_name='Observações', help_text='Descrição do evento ou informações adicionais para a administradora.'
    )
    analise_ia = models.JSONField(
        null=True, blank=True,
        verbose_name='Análise da IA',
        help_text='Resumo do pedido gerado automaticamente pela IA (apoio à administradora).'
    )
    analise_ia_em = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Análise da IA em', help_text='Data e hora em que a análise da IA foi gerada.'
    )

    class Meta:
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'
        ordering = ['-data_pedido']

    def __str__(self):
        return f"Reserva de {self.cliente.nome} — {self.chacara.nome} ({self.data_inicio} a {self.data_fim})"

    def sobrepostas(self, status):
        """Outras reservas da mesma chácara, no status informado, que se
        sobrepõem a este período. O dia de saída fica livre para nova entrada."""
        qs = Reserva.objects.filter(
            chacara_id=self.chacara_id,
            status=status,
            data_inicio__lt=self.data_fim,
            data_fim__gt=self.data_inicio,
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        return qs

    def clean(self):
        if self.data_inicio and self.data_fim:
            if self.data_fim < self.data_inicio:
                raise ValidationError({'data_fim': 'A data de saída não pode ser anterior à data de chegada.'})
            if self.data_fim == self.data_inicio:
                raise ValidationError({'data_fim': 'A data de saída deve ser posterior à data de chegada (mínimo de 1 diária).'})

            if self.chacara_id:
                if self.sobrepostas(self.STATUS_CONFIRMADA).exists():
                    raise ValidationError(
                        'Já existe uma reserva confirmada que se sobrepõe a estas datas. '
                        'Consulte o calendário de disponibilidade antes de escolher as datas.'
                    )

    def save(self, *args, **kwargs):
        if self.data_inicio and self.data_fim and self.chacara_id:
            dias = (self.data_fim - self.data_inicio).days
            if dias > 0:
                self.valor_total = self.chacara.preco_diaria * dias
        super().save(*args, **kwargs)


class HistoricoReserva(models.Model):
    """Registro de cada mudança de status de uma reserva (o "movimento")."""

    reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE, related_name='historico',
        verbose_name='Reserva', help_text='Reserva cujo status foi alterado.'
    )
    status_anterior = models.CharField(
        max_length=20, choices=Reserva.STATUS_CHOICES, blank=True,
        verbose_name='Status Anterior', help_text='Status antes da alteração (vazio na criação do pedido).'
    )
    status_novo = models.CharField(
        max_length=20, choices=Reserva.STATUS_CHOICES,
        verbose_name='Status Novo', help_text='Status depois da alteração.'
    )
    alterado_por = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True,
        verbose_name='Alterado por', help_text='Usuário que fez a alteração.'
    )
    data = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Data', help_text='Data e hora da alteração.'
    )
    observacao = models.TextField(
        blank=True,
        verbose_name='Observação', help_text='Motivo ou detalhe da alteração.'
    )

    class Meta:
        verbose_name = 'Histórico de Reserva'
        verbose_name_plural = 'Históricos de Reserva'
        ordering = ['-data']

    def __str__(self):
        return f"Reserva #{self.reserva_id}: {self.status_anterior or '—'} → {self.status_novo}"


class Avaliacao(models.Model):
    """Avaliação de uma estadia, feita pelo próprio cliente.

    Regra de elegibilidade (``services.reservas_avaliaveis``): só a PRÓPRIA
    reserva, CONFIRMADA e com a estadia já concluída (``data_fim <= hoje``).
    Antes disso não há o que avaliar, e um pedido pendente/recusado nunca
    virou estadia. Uma avaliação por reserva (OneToOne).
    """

    NOTA_MINIMA = 1
    NOTA_MAXIMA = 5
    NOTA_CHOICES = [
        (1, '1 — Ruim'),
        (2, '2 — Regular'),
        (3, '3 — Boa'),
        (4, '4 — Muito boa'),
        (5, '5 — Excelente'),
    ]

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='avaliacoes',
        verbose_name='Usuário', help_text='Quem fez a avaliação (preenchido automaticamente).'
    )
    reserva = models.OneToOneField(
        Reserva, on_delete=models.CASCADE, related_name='avaliacao',
        verbose_name='Reserva', help_text='Estadia avaliada (confirmada e já concluída).'
    )
    nota = models.PositiveSmallIntegerField(
        choices=NOTA_CHOICES,
        validators=[MinValueValidator(NOTA_MINIMA), MaxValueValidator(NOTA_MAXIMA)],
        verbose_name='Nota', help_text='De 1 (ruim) a 5 (excelente).'
    )
    comentario = models.TextField(
        blank=True, max_length=1000,
        verbose_name='Comentário', help_text='Opcional. Conte como foi a estadia (até 1000 caracteres).'
    )
    criado_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Criada em', help_text='Data e hora em que a avaliação foi enviada.'
    )
    atualizado_em = models.DateTimeField(
        auto_now=True,
        verbose_name='Atualizada em', help_text='Data e hora da última alteração.'
    )

    class Meta:
        verbose_name = 'Avaliação'
        verbose_name_plural = 'Avaliações'
        ordering = ['-criado_em']

    def __str__(self):
        return f"Avaliação {self.nota}/5 — reserva #{self.reserva_id}"

    def clean(self):
        # O usuário é preenchido pela view antes da validação (nunca vem do POST).
        if not self.reserva_id or not self.usuario_id:
            return
        reserva = self.reserva
        if reserva.cliente.usuario_id != self.usuario_id:
            raise ValidationError({'reserva': 'Você só pode avaliar as suas próprias reservas.'})
        if reserva.status != Reserva.STATUS_CONFIRMADA or reserva.data_fim > timezone.localdate():
            raise ValidationError(
                {'reserva': 'Só é possível avaliar uma reserva confirmada cuja estadia já terminou.'})
