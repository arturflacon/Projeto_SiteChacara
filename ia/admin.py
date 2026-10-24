from django.contrib import admin

from .models import ConfiguracaoIA, PerfilIAUsuario, RequisicaoIA


@admin.register(ConfiguracaoIA)
class ConfiguracaoIAAdmin(admin.ModelAdmin):
    list_display = ['provedor', 'modelo', 'ativo', 'cota_mensal_padrao_tokens', 'atualizado_em', 'atualizado_por']
    readonly_fields = ['atualizado_em', 'atualizado_por']

    def has_add_permission(self, request):
        # Singleton: a linha é criada por ConfiguracaoIA.obter().
        return not ConfiguracaoIA.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PerfilIAUsuario)
class PerfilIAUsuarioAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'habilitado', 'cota_mensal_tokens']
    list_filter = ['habilitado']
    search_fields = ['usuario__username']
    list_select_related = ['usuario']


@admin.register(RequisicaoIA)
class RequisicaoIAAdmin(admin.ModelAdmin):
    list_display = ['criado_em', 'origem', 'usuario', 'modelo', 'tokens_total', 'duracao_ms', 'sucesso']
    list_filter = ['origem', 'sucesso']
    search_fields = ['usuario__username', 'prompt']
    date_hierarchy = 'criado_em'
    # Auditoria: só leitura.
    readonly_fields = [f.name for f in RequisicaoIA._meta.fields]
    list_select_related = ['usuario']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
