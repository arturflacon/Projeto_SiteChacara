from django.urls import path

from . import views

app_name = 'telegram_bot'

urlpatterns = [
    # Sem token na URL: a proteção é o cabeçalho com o segredo (ver WebhookView).
    path('webhook/', views.WebhookView.as_view(), name='webhook'),
    path('conectar/', views.ConectarTelegramView.as_view(), name='conectar'),
    path('conectar/gerar/', views.GerarCodigoView.as_view(), name='gerar_codigo'),
    path('conectar/desvincular/', views.DesvincularView.as_view(), name='desvincular'),
    path('mensagens/', views.MensagensTelegramListView.as_view(), name='mensagens'),
]
