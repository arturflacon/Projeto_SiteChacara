from django.urls import path

from . import views

app_name = 'ia'

urlpatterns = [
    # Admin
    path('requisicoes/', views.RequisicoesListView.as_view(), name='requisicoes'),
    path('requisicoes/<int:pk>/', views.RequisicaoDetailView.as_view(), name='requisicao_detail'),
    path('configuracao/', views.ConfiguracaoIAUpdateView.as_view(), name='configuracao'),
    path('configuracao/testar/', views.TestarConexaoView.as_view(), name='testar_conexao'),
    path('usuarios/', views.UsuariosIAListView.as_view(), name='usuarios'),
    path('usuarios/<int:usuario_id>/editar/', views.PerfilIAUsuarioUpdateView.as_view(), name='perfil_update'),
    # Qualquer usuário logado
    path('meu-consumo/', views.MeuConsumoView.as_view(), name='meu_consumo'),
]
