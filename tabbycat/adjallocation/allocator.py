
def allocate_adjudicators(round, alloc_class):
    if round.draw_status != round.STATUS_CONFIRMED:
        raise RuntimeError("Tried to allocate adjudicators on unconfirmed draw")

    debates = round.debate_set.all()
    adjs = list(round.active_adjudicators.all())
    allocator = alloc_class(debates, adjs, round)

    for alloc in allocator.allocate():
        alloc.save()

    round.adjudicator_status = round.STATUS_DRAFT
    round.save()


class Allocator(object):
    def __init__(self, debates, adjudicators, round):
        self.tournament = round.tournament
        self.debates = list(debates)
        self.adjudicators = adjudicators

    def allocate(self):
        raise NotImplementedError
