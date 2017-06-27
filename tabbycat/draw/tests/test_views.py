from django.test import TestCase

from tournaments.models import Round
from utils.tests import ConditionalTableViewTest


class PublicDrawForRoundViewTest(ConditionalTableViewTest, TestCase):
    view_name = 'draw-public-for-round'
    view_toggle = 'public_features__public_draw'
    round_seq = 2

    def table_data(self):
        # Check number of debates is correct
        round = Round.objects.get(tournament=self.t, seq=self.round_seq)
        return round.debate_set.all().count()
