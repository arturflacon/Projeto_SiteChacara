from django.contrib import admin

from .models import MensagemAssistente


@admin.register(MensagemAssistente)
class MensagemAssistenteAdmin(admin.ModelAdmin):
    list_display = ['criado_em', 'usuario', 'papel', 'conteudo']
    list_filter = ['papel']
    search_fields = ['usuario__username']
    list_select_related = ['usuario']
    readonly_fields = ['usuario', 'papel', 'conteudo', 'criado_em', 'requisicao']

    def has_add_permission(self, request):
        return False
