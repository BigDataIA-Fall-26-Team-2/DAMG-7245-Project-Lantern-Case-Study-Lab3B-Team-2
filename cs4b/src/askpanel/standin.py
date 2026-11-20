"""A deterministic stand-in for the SQL-writing model, so the notebooks run
offline at no cost. It knows a handful of fixture questions; one of them gets
a wrong first attempt, so the repair path is visible. It is a teaching device,
never a substitute for a real model on your own ten questions.

It queries the base tables (holdings, filings) so it works before you have
written holdings_v."""

FIXTURE = {
    "Which BDC has the largest total fair value in its current schedule?": [
        "SELECT f.name AS bdc, SUM(h.fair_value) AS total_fair_value "
        "FROM holdings h JOIN filings f ON f.adsh = h.adsh "
        "WHERE h.period_role = 'current' GROUP BY f.name "
        "ORDER BY total_fair_value DESC LIMIT 1"],
    "How many current holdings does each BDC report?": [
        "SELECT f.name AS bdc, COUNT(*) AS holdings "
        "FROM holdings h JOIN filings f ON f.adsh = h.adsh "
        "WHERE h.period_role = 'current' GROUP BY f.name ORDER BY f.name"],
    "Which current debt holdings carry a PIK rate above 2%?": [
        # first attempt uses a column that does not exist: repair shows it
        "SELECT f.name AS bdc, h.identifier, h.pik FROM holdings h "
        "JOIN filings f ON f.adsh = h.adsh WHERE h.pik > 0.02",
        "SELECT f.name AS bdc, h.identifier, h.pik_rate FROM holdings h "
        "JOIN filings f ON f.adsh = h.adsh "
        "WHERE h.period_role = 'current' AND h.pik_rate > 0.02 "
        "ORDER BY h.pik_rate DESC"],
    "Which debt holdings are priced below 95 in the current schedule?": [
        "SELECT f.name AS bdc, h.identifier, "
        "ROUND(100.0 * h.fair_value / h.principal, 1) AS price "
        "FROM holdings h JOIN filings f ON f.adsh = h.adsh "
        "WHERE h.period_role = 'current' AND h.principal > 0 "
        "AND 100.0 * h.fair_value / h.principal < 95 ORDER BY price"],
    "How did each BDC's total fair value change from the prior to the current schedule?": [
        "SELECT f.name AS bdc, "
        "SUM(CASE WHEN h.period_role = 'prior' THEN h.fair_value END) AS prior_fv, "
        "SUM(CASE WHEN h.period_role = 'current' THEN h.fair_value END) AS current_fv "
        "FROM holdings h JOIN filings f ON f.adsh = h.adsh "
        "GROUP BY f.name ORDER BY f.name"],
}
DECLINE = "I can only answer questions the BDC panel holds data for."


class FixtureSQLModel:
    """Called with a request dict (see nodes.build_request); returns a dict
    with sql or decline, plus usd and tokens, like a recorded response."""

    def __init__(self, answers=None, usd=0.00128, tokens=(2000, 300)):
        self.answers = FIXTURE if answers is None else answers
        self.usd, self.tokens = usd, tokens

    def __call__(self, req):
        base = {"usd": self.usd, "tokens_in": self.tokens[0],
                "tokens_out": self.tokens[1]}
        tries = self.answers.get(req["question"])
        if not tries:
            return {**base, "sql": None, "decline": DECLINE,
                    "explanation": "not answerable from the panel"}
        sql = tries[min(req.get("attempt", 0), len(tries) - 1)]
        return {**base, "sql": sql, "decline": None,
                "explanation": "stand-in query for a fixture question"}
