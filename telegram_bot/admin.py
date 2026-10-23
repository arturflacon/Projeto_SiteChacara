from django.contrib import admin

from .models import CodigoVinculacao, MensagemTelegram, TentativaVinculoInvalida, VinculoTelegram


@admin.register(VinculoTelegram)
class VinculoTelegramAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'username', 'chat_id', 'vinculado_em']
    search_fields = ['usuario__username', 'username']
    list_select_related = ['usuario']


@admin.register(CodigoVinculacao)
class CodigoVinculacaoAdmin(admin.ModelAdmin):
    # O código em si não aparece na lista: é um segredo de curta duração.
    list_display = ['usuario', 'criado_em', 'expira_em', 'usado_em']
    exclude = ['codigo']
    readonly_fields = ['usuario', 'criado_em', 'expira_em', 'usado_em']
    list_select_related = ['usuario']

    def has_add_permission(self, request):
        return False


@admin.register(MensagemTelegram)
class MensagemTelegramAdmin(admin.ModelAdmin):
    list_display = ['criado_em', 'direcao', 'tipo', 'usuario', 'chat_id', 'texto']
    list_filter = ['direcao', 'tipo', 'aviso_limite']
    search_fields = ['usuario__username', 'texto']
    list_select_related = ['usuario']
    readonly_fields = [f.name for f in MensagemTelegram._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TentativaVinculoInvalida)
class TentativaVinculoInvalidaAdmin(admin.ModelAdmin):
    list_display = ['telegram_user_id', 'criado_em']
