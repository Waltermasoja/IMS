"""
URL configuration for inventorySystem project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.http import HttpResponse, FileResponse
from django.views.decorators.cache import cache_control
from django.conf.urls.static import static
from django.conf import settings
import os

from inventory.views import login_view, logout_view

def redirect_to_login(request):
    return redirect('login')

@cache_control(max_age=0)
def service_worker(request):
    """Serve sw.js from root scope with Service-Worker-Allowed header."""
    path_ = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    resp = FileResponse(open(path_, 'rb'), content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'
    return resp

urlpatterns = [
    path('', redirect_to_login, name='root'),
    path('admin/', admin.site.urls),
    path('sw.js', service_worker, name='service_worker'),
    path('inventory/', include('inventory.urls')),
    path('accounting/', include('accounting.urls')),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
