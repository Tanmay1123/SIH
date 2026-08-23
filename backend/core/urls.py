from django.urls import path

from . import views

urlpatterns = [
    path("companies/", views.CompanyListView.as_view(), name="company-list"),
    path("companies/<int:pk>/", views.CompanyDetailView.as_view(), name="company-detail"),
    path("invoices/", views.InvoiceListView.as_view(), name="invoice-list"),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice-detail"),
    path("data/upload/", views.upload_dataset, name="data-upload"),
    path("auth/login/", views.login, name="auth-login"),
    path("auth/logout/", views.logout, name="auth-logout"),
    path("auth/whoami/", views.whoami, name="auth-whoami"),
]
