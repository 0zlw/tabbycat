from django.conf.urls import url

from . import views

urlpatterns = [

    # Traditional sheets
    url(r'^round/(?P<round_seq>\d+)/print/scoresheets/$',
        views.PrintScoreSheetsView.as_view(),
        name='printing-scoresheets'),
    url(r'^round/(?P<round_seq>\d+)/print/feedback/$',
        views.PrintFeedbackFormsView.as_view(),
        name='printing-feedback'),

    # Private URL distribution
    url(r'^feedback_urls_sheets/',
        views.PrintFeedbackURLsView.as_view(),
        name='printing-ballot-urls'),
    url(r'^ballots_urls_sheets/',
        views.PrintBallotURLsView.as_view(),
        name='printing-feedback-urls'),

    # WADL sheets
    url(r'^round/(?P<round_seq>\d+)/master_sheets/list/$',
        views.MasterSheetsListView.as_view(),
        name='printing-master-sheets-list'),
    url(r'^round/(?P<round_seq>\d+)/master_sheets/venue_category/(?P<venue_category_id>\d+)/$',
        views.MasterSheetsView.as_view(),
        name='printing-master-sheets-view'),
    url(r'^round/(?P<round_seq>\d+)/room_sheets_view/venue_category/(?P<venue_category_id>\d+)/$',
        views.RoomSheetsView.as_view(),
        name='printing-room-sheets-view'),


]
