from django.conf import settings
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('ia/', include('ia.urls')),
    path('assistente/', include('assistente.urls')),
    path('telegram/', include('telegram_bot.urls')),
    path('', include('website.urls')),
]

if settings.DEBUG and not settings.TESTANDO:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
