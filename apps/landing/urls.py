from django.urls import path

from apps.landing import views

app_name = "landing"

urlpatterns = [
    path("", views.index, name="index"),
]
