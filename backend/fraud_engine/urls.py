from django.urls import path

from . import lab_views, views

urlpatterns = [
    # Pipeline
    path("fraud/run/", views.run_detection, name="run-detection"),
    path("fraud/status/", views.pipeline_status, name="pipeline-status"),
    path("fraud/graph/", views.graph_data, name="graph-data"),
    # Detection runs - each one a named, dated record of what was found.
    path("fraud/runs/", views.DetectionRunListView.as_view(), name="run-list"),
    path("fraud/runs/<int:pk>/", views.DetectionRunDetailView.as_view(), name="run-detail"),
    path("fraud/runs/<int:pk>/delete/", views.delete_run, name="run-delete"),
    path("fraud/runs/<int:pk>/report/", views.create_report, name="run-report"),
    # Alerts (circular-trade rings and fake invoice mills)
    path("fraud/rings/", views.FlaggedRingListView.as_view(), name="ring-list"),
    path("fraud/rings/<int:pk>/", views.FlaggedRingDetailView.as_view(), name="ring-detail"),
    path("fraud/rings/<int:pk>/confirm/", views.confirm_ring, name="ring-confirm"),
    path("fraud/rings/<int:pk>/dismiss/", views.dismiss_ring, name="ring-dismiss"),
    path("fraud/dismissal-reasons/", views.dismissal_reasons, name="dismissal-reasons"),
    # Case reports to the supervisor
    path("reports/", views.CaseReportListView.as_view(), name="report-list"),
    path("reports/mail-status/", views.mail_status, name="report-mail-status"),
    path("reports/<int:pk>/", views.CaseReportDetailView.as_view(), name="report-detail"),
    path("reports/<int:pk>/send/", views.resend_report, name="report-send"),
    # Dataset Lab - fabricated test data, deliberately outside the console
    path("lab/presets/", lab_views.lab_presets, name="lab-presets"),
    path("lab/preview/", lab_views.lab_preview, name="lab-preview"),
    path("lab/download/", lab_views.lab_download, name="lab-download"),
    path("lab/load/", lab_views.lab_load, name="lab-load"),
    # Ledger
    path("ledger/blocks/", views.LedgerBlockListView.as_view(), name="ledger-blocks"),
    path("ledger/verify/", views.verify_ledger, name="ledger-verify"),
]
