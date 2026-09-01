from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.views import serve as servir_statique
from django.urls import include, path, re_path
from rest_framework.authtoken.views import obtain_auth_token

from wms.views import app_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", obtain_auth_token),
    path("api/", include("wms.urls")),
    path("api/auth/", include("rest_framework.urls")),
]

# En DEBUG, Django sert /static/ tout seul. En exploitation il ne le fait plus :
# l'interface se chargeait alors sans CSS ni JavaScript (page blanche) puisque le
# WMS tourne sur un poste de l'entrepôt, sans Nginx devant lui. On rétablit la
# route explicitement. `DJANGO_SERVIR_STATIQUES=False` la coupe le jour où un vrai
# serveur web sert `staticfiles/`.
if not settings.DEBUG and settings.SERVIR_STATIQUES:
    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", servir_statique, {"insecure": True}),
    ]

# Catch-all de l'interface : toujours en dernier.
urlpatterns += [path("", app_index, name="app")]
