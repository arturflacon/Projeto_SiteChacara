from django.contrib import admin

from .models import Administrador, Chacara, Cliente, HistoricoReserva, Reserva


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nome', 'telefone', 'usuario']
    search_fields = ['nome', 'telefone', 'usuario__username']
    # Evita N+1: a coluna "usuario" faria 1 consulta ao User por linha.
    list_select_related = ['usuario']


@admin.register(Administrador)
class AdministradorAdmin(admin.ModelAdmin):
    list_display = ['nome', 'usuario']
    search_fields = ['nome', 'usuario__username']
    # Evita N+1: a coluna "usuario" faria 1 consulta ao User por linha.
    list_select_related = ['usuario']


@admin.register(Chacara)
class ChacaraAdmin(admin.ModelAdmin):
    list_display = ['nome', 'preco_diaria', 'num_quartos', 'num_banheiros', 'tem_piscina', 'tem_churrasqueira', 'tem_estacionamento']
    search_fields = ['nome']
    list_filter = ['tem_piscina', 'tem_churrasqueira', 'tem_estacionamento']


class HistoricoReservaInline(admin.TabularInline):
    model = HistoricoReserva
    extra = 0
    readonly_fields = ['data', 'status_anterior', 'status_novo', 'alterado_por', 'observacao']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # O histórico é gravado pelas views; não se cria à mão.
        return False


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ['cliente', 'chacara', 'data_inicio', 'data_fim', 'valor_total', 'status', 'data_pedido']
    list_filter = ['status', 'chacara']
    search_fields = ['cliente__nome', 'chacara__nome']
    date_hierarchy = 'data_inicio'
    readonly_fields = ['data_pedido', 'valor_total']
    # Evita N+1: as colunas "cliente" e "chacara" (e o __str__) fariam
    # 2 consultas extras por linha da listagem.
    list_select_related = ['cliente', 'chacara']
    inlines = [HistoricoReservaInline]


@admin.register(HistoricoReserva)
class HistoricoReservaAdmin(admin.ModelAdmin):
    list_display = ['reserva', 'status_anterior', 'status_novo', 'alterado_por', 'data']
    list_filter = ['status_novo']
    readonly_fields = ['data']
    # Evita N+1: o __str__ da reserva acessa cliente e chácara, e a coluna
    # "alterado_por" acessa o User — sem isto seriam 3 consultas por linha.
    list_select_related = ['reserva__cliente', 'reserva__chacara', 'alterado_por']
