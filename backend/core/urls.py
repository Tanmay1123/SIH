from django.urls import path

from . import team_views, views

urlpatterns = [
    path("companies/", views.CompanyListView.as_view(), name="company-list"),
    path("companies/<int:pk>/", views.CompanyDetailView.as_view(), name="company-detail"),
    path("invoices/", views.InvoiceListView.as_view(), name="invoice-list"),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice-detail"),
    # Datasets - every upload is kept, one is active at a time.
    path("datasets/", views.DatasetListView.as_view(), name="dataset-list"),
    path("datasets/<int:pk>/", views.rename_dataset, name="dataset-rename"),
    path("datasets/<int:pk>/activate/", views.activate_dataset, name="dataset-activate"),
    path("datasets/<int:pk>/delete/", views.delete_dataset, name="dataset-delete"),
    path("data/upload/", views.upload_dataset, name="data-upload"),
    # Auth + the signed-in account
    path("auth/login/", views.login, name="auth-login"),
    path("auth/logout/", views.logout, name="auth-logout"),
    path("auth/whoami/", views.whoami, name="auth-whoami"),
    path("auth/me/", team_views.me, name="auth-me"),
    path("auth/change-password/", team_views.change_password, name="auth-change-password"),
    # The supervisor's view of the team
    path("team/", team_views.team_overview, name="team-overview"),
    path("team/activity/", team_views.team_activity, name="team-activity"),
    path("team/<int:pk>/role/", team_views.set_member_role, name="team-set-role"),
    # Settings an administrator can change without touching .env
    path("settings/", team_views.app_settings, name="app-settings"),
    path("settings/update/", team_views.update_app_settings, name="app-settings-update"),
]
