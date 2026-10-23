from django.urls import path

from . import views

app_name = 'assistente'

urlpatterns = [
    path('', views.ConversaView.as_view(), name='conversa'),
    path('perguntar/', views.PerguntarView.as_view(), name='perguntar'),
    path('limpar/', views.LimparConversaView.as_view(), name='limpar'),
]
