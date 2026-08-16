from django.urls import path

from . import views

urlpatterns = [
    # Pipeline
    path("fraud/rebuild-graph/", views.rebuild_graph, name="rebuild-graph"),
    path("fraud/score/", views.score_rings, name="score-rings"),
    path("fraud/status/", views.pipeline_status, name="pipeline-status"),
    path("fraud/graph/", views.graph_data, name="graph-data"),
    # Rings
    path("fraud/rings/", views.FlaggedRingListView.as_view(), name="ring-list"),
    path("fraud/rings/<int:pk>/", views.FlaggedRingDetailView.as_view(), name="ring-detail"),
    path("fraud/rings/<int:pk>/confirm/", views.confirm_ring, name="ring-confirm"),
    # Ledger
    path("ledger/blocks/", views.LedgerBlockListView.as_view(), name="ledger-blocks"),
    path("ledger/verify/", views.verify_ledger, name="ledger-verify"),
]
