from django.conf.urls import url

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

from actionlog.consumers import ActionLogEntryConsumer
from checkins.consumers import CheckInEventConsumer
from draw.consumers import DebateConsumer
from results.consumers import BallotResultConsumer, BallotStatusConsumer


# This acts like a urls.py equivalent; need to import the channel routes
# from sub apps into this file (plus specifying their top level URL path)
# Note the lack of trailing "/" (but paths in apps need a trailing "/")

application = ProtocolTypeRouter({

    # WebSocket handlers
    "websocket": AuthMiddlewareStack(
        URLRouter([
            # TournamentOverviewContainer
            url(r'^ws/<slug:tournament_slug>/action_logs/$', ActionLogEntryConsumer),
            url(r'^ws/<slug:tournament_slug>/ballot_results/$', BallotResultConsumer),
            url(r'^ws/<slug:tournament_slug>/ballot_statuses/$', BallotStatusConsumer),
            # CheckInStatusContainer
            url(r'^ws/<slug:tournament_slug>/checkins/$', CheckInEventConsumer),
            # DebateConsumer
            url(r'^ws/<slug:tournament_slug>/<int:round_seq>/debates/$', DebateConsumer)
        ])
    ),
})
