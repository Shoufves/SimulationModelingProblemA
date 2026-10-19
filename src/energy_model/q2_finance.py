"""Project financing and repayment; financial transfers are not resource costs."""


def debt(actor):
    return sum(p["remaining"] for p in actor.loans)


def book_assets(actor):
    m=actor.model
    return sum(c["capacity_mw"]*c["book_cost_cny_per_mw"]*max(0,(c["exit_year"]-m.year)/(c["exit_year"]-c["online_year"]))
        for c in m.cohorts if c["tech"]==actor.name and c["status"]=="active")


def financing_limit(actor, capex):
    a = actor.model.a
    if actor.arrears > .01:
        return 0.0
    equity = a["project_equity_fraction"]
    own = a["sponsor_equity_fraction"]
    committed = sum(p["cost"] for p in actor.model.projects if p["tech"]==actor.name and p["status"]=="construction")
    collateral = (book_assets(actor)+committed)*a["maximum_debt_asset_ratio"]
    # A new funded project can itself be pledged, in addition to existing
    # assets and committed construction. Sponsor cash is still mandatory.
    extra_debt_per_cost = 1-equity-a["maximum_debt_asset_ratio"]
    headroom = collateral-debt(actor)
    debt_limit = headroom/(extra_debt_per_cost*capex) if extra_debt_per_cost>0 else (float("inf") if headroom>=0 else 0)
    return max(0,min(actor.cash/(own*capex),debt_limit))


def fund_project(actor, cost, project):
    m, a = actor.model, actor.model.a
    equity = cost*a["sponsor_equity_fraction"]
    shareholder = cost*(a["project_equity_fraction"]-a["sponsor_equity_fraction"])
    principal = cost-equity-shareholder
    if equity > max(0,actor.cash)+.01:
        raise ValueError("Unfunded project equity")
    actor.cash -= equity
    actor.loans.append(dict(project=project, remaining=principal,
        annual_principal=principal/a["loan_term_years"], due=m.year+1, overdue=0.0, interest_overdue=0.0))
    m.finance.append(dict(year=m.year, kind="project_finance", actor=actor.name,
        project=project,equity_cny=equity,shareholder_equity_cny=shareholder,debt_draw_cny=principal,
        actor_cash_transfer_cny=-equity, escrow_transfer_cny=cost,
        lender_transfer_cny=-principal,shareholder_transfer_cny=-shareholder,resource_cost_cny=0))


def service_debt(actor):
    m, a = actor.model, actor.model.a
    actor.arrears = 0.0
    for loan in actor.loans:
        if loan["due"] > m.year:
            continue
        interest_due = loan["remaining"]*a["loan_interest_rate"]+loan["interest_overdue"]
        principal_due = min(loan["remaining"],loan["annual_principal"]+loan["overdue"])
        interest = min(max(0,actor.cash),interest_due)
        actor.cash -= interest
        principal = min(max(0,actor.cash),principal_due)
        actor.cash -= principal
        loan["remaining"] -= principal
        loan["overdue"] = principal_due-principal
        loan["interest_overdue"] = interest_due-interest
        actor.arrears += loan["overdue"]+loan["interest_overdue"]
        m.finance.append(dict(year=m.year,kind="debt_service",actor=actor.name,
            project=loan["project"],interest_due_cny=interest_due,principal_due_cny=principal_due,
            interest_paid_cny=interest,principal_paid_cny=principal,
            arrears_cny=loan["overdue"]+loan["interest_overdue"],debt_remaining_cny=loan["remaining"],
            actor_cash_transfer_cny=-interest-principal,lender_transfer_cny=interest+principal,resource_cost_cny=0))
