"""Synthetic contract accounting examples; no national or Shanghai calibration."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from energy_model.q2_cfd import (
    CfdContract, CfdLedger, MeteredPeriod, OpeningObligation, PriceBasis, quote_settlement)


D = Decimal
JAN = date(2026, 1, 1)
FEB = date(2026, 2, 1)
MAR = date(2026, 3, 1)
APR = date(2026, 4, 1)
BASIS = PriceBasis("nominal_CNY_per_MWh", "vat_inclusive", ".13", "actual_net_export")


def contract(**changes):
    values = dict(project_id="solar1", producer_id="producer1", region="synthetic_region",
        technology="solar", eligible=True, eligibility_evidence="synthetic eligibility approval",
        actual_commissioning_date=date(2025, 12, 15), commissioning_evidence="verified actual meter commissioning",
        mechanism_start=JAN, mechanism_end_exclusive=date(2027, 1, 1),
        mechanism_price_cny_per_mwh="400", price_basis=BASIS,
        market_reference_method="monthly_same_technology_realtime_weighted",
        negative_market_price_rule="reject_negative", negative_price_rule_evidence="synthetic contract clause",
        annual_caps_mwh={2026: "100"}, monthly_caps_mwh={"2026-01": "60", "2026-02": "60", "2026-03": "60"})
    return CfdContract(**(values | changes))


def meter(**changes):
    values = dict(project_id="solar1", region="synthetic_region", start=JAN, end_exclusive=FEB,
        actual_net_export_mwh="50", eligible_net_export_mwh="40", claimed_mechanism_mwh="30",
        meter_evidence="synthetic final meter", market_reference_cny_per_mwh="300",
        market_reference_month="2026-01", market_reference_method=contract().market_reference_method,
        price_basis=BASIS, green_certificate_revenue_on_claim_cny="0",
        other_difference_settlement_on_claim_cny="0")
    return MeteredPeriod(**(values | changes))


def ledger(*, contracts=None, system="500", producer="100", opening=(),
           opening_date=JAN, year_used=None, month_used=None):
    contracts = [contract()] if contracts is None else contracts
    return CfdLedger(region="synthetic_region", opening_date=opening_date, contracts=contracts,
        opening_system_cash_cny=system,
        opening_producer_cash_cny={c.producer_id: producer for c in contracts}, opening_obligations=opening,
        opening_year_used_mwh={c.project_id: 0 for c in contracts} if year_used is None else year_used,
        opening_month_used_mwh={c.project_id: 0 for c in contracts} if month_used is None else month_used)


class CfdTests(unittest.TestCase):
    def check_balances(self, book):
        b = book.balances()
        self.assertEqual(b["cash_conservation_residual_cny"], 0)
        self.assertEqual(b["system"]["payable_cny"],
                         sum(p["receivable_cny"] for p in b["producers"].values()))
        self.assertEqual(b["system"]["receivable_cny"],
                         sum(p["payable_cny"] for p in b["producers"].values()))
        self.assertEqual(b["fiscal_subsidy_accrual_cny"], 0)
        self.assertGreaterEqual(b["system"]["cash_cny"], 0)
        for p in b["producers"].values():
            for value in p.values():self.assertGreaterEqual(value, 0)
        return b

    def test_pure_quote_both_directions_and_equal_price(self):
        for price, signed in (("300", 3000), ("450", -1500), ("400", 0)):
            q = quote_settlement(contract(), meter(market_reference_cny_per_mwh=price))
            self.assertEqual(q["signed_producer_accrual_cny"], signed)
            self.assertEqual(q["mechanism_volume_mwh"], 30)
            self.assertIn("not_fiscal_subsidy", q["accounting_kind"])
        self.assertEqual(quote_settlement(contract(), meter())["actual_net_export_mwh"], 50)

    def test_system_shortfall_preserves_receivable_then_later_cash_pays_it(self):
        b = ledger()
        q = b.accrue(meter(), posting_date=FEB)
        payment = b.pay(q["obligation_id"], requested_cny=3000, on=FEB)
        self.assertEqual(payment["paid_cny"], 500)
        self.assertEqual(payment["outstanding_cny"], 2500)
        balances = self.check_balances(b)
        self.assertEqual(balances["producers"]["producer1"]["cash_cny"], 600)
        self.assertEqual(balances["producers"]["producer1"]["receivable_cny"], 2500)
        b.add_cash(party="system", amount_cny=1000, on=MAR, evidence="documented system-cost collection")
        b.pay(q["obligation_id"], requested_cny=2500, on=MAR)
        b.add_cash(party="system", amount_cny=1500, on=APR, evidence="later collection")
        b.pay(q["obligation_id"], requested_cny=1500, on=APR)
        self.assertEqual(b.obligations[q["obligation_id"]]["paid_cny"], 3000)
        self.assertEqual(self.check_balances(b)["system"]["payable_cny"], 0)
        self.assertEqual(len(b.payments), 3)

    def test_producer_shortfall_preserves_system_receivable_and_reverse_payment(self):
        b = ledger()
        q = b.accrue(meter(market_reference_cny_per_mwh=450), posting_date=FEB)
        payment = b.pay(q["obligation_id"], requested_cny=1500, on=FEB)
        self.assertEqual(payment["paid_cny"], 100)
        self.assertEqual(payment["system_cash_delta_cny"]+payment["producer_cash_delta_cny"], 0)
        self.assertEqual(self.check_balances(b)["system"]["receivable_cny"], 1400)
        b.add_cash(party="producer1", amount_cny=1400, on=MAR, evidence="producer's actual liquidity")
        b.pay(q["obligation_id"], requested_cny=1400, on=MAR)
        self.assertEqual(self.check_balances(b)["system"]["cash_cny"], 2000)

    def test_opposite_obligations_are_gross_and_do_not_automatically_offset(self):
        b = ledger(system=0, producer=0)
        plus = b.accrue(meter(), posting_date=FEB)
        minus = b.accrue(meter(start=FEB, end_exclusive=MAR, market_reference_month="2026-02",
                              market_reference_cny_per_mwh=500), posting_date=MAR)
        balances = self.check_balances(b)
        self.assertEqual(balances["system"]["payable_cny"], 3000)
        self.assertEqual(balances["system"]["receivable_cny"], 3000)
        self.assertEqual(b.pay(plus["obligation_id"], requested_cny=3000, on=MAR)["paid_cny"], 0)
        self.assertEqual(b.pay(minus["obligation_id"], requested_cny=3000, on=MAR)["paid_cny"], 0)
        self.check_balances(b)

    def test_caps_are_cumulative_within_month_and_across_months(self):
        b = ledger()
        b.accrue(meter(end_exclusive=date(2026, 1, 16), claimed_mechanism_mwh=40),
                 posting_date=FEB)
        before = b.obligations
        with self.assertRaisesRegex(ValueError, "Cumulative"):
            b.accrue(meter(start=date(2026, 1, 16), claimed_mechanism_mwh=30), posting_date=FEB)
        self.assertEqual(b.obligations, before)
        b.accrue(meter(start=date(2026, 1, 16), claimed_mechanism_mwh=20), posting_date=FEB)
        b.accrue(meter(start=FEB, end_exclusive=MAR, market_reference_month="2026-02",
                      claimed_mechanism_mwh=40), posting_date=MAR)
        with self.assertRaisesRegex(ValueError, "Cumulative"):
            b.accrue(meter(start=MAR, end_exclusive=APR, market_reference_month="2026-03",
                          claimed_mechanism_mwh=1), posting_date=APR)
        self.check_balances(b)

    def test_actual_meter_eligibility_not_awarded_volume_bounds_claim(self):
        for changes in (dict(actual_net_export_mwh=0, eligible_net_export_mwh=0),
                        dict(eligible_net_export_mwh=29), dict(eligible_net_export_mwh=51),
                        dict(claimed_mechanism_mwh=61, eligible_net_export_mwh=61, actual_net_export_mwh=61)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                quote_settlement(contract(), meter(**changes))
        q = quote_settlement(contract(), meter(actual_net_export_mwh=0,
            eligible_net_export_mwh=0, claimed_mechanism_mwh=0))
        self.assertEqual(q["amount_cny"], 0)

    def test_midyear_opening_keeps_previously_used_annual_quota(self):
        c = contract(annual_caps_mwh={2026: 1000},
            monthly_caps_mwh={"2026-01": 300, "2026-02": 300, "2026-03": 300, "2026-04": 400})
        b = ledger(contracts=[c], opening_date=APR, year_used={"solar1": 800},
                   month_used={"solar1": 0})
        april = meter(start=APR, end_exclusive=date(2026, 5, 1), market_reference_month="2026-04",
                      actual_net_export_mwh=300, eligible_net_export_mwh=300, claimed_mechanism_mwh=201)
        with self.assertRaisesRegex(ValueError, "Cumulative"):
            b.accrue(april, posting_date=date(2026, 5, 1))
        b.accrue(replace(april, claimed_mechanism_mwh=200), posting_date=date(2026, 5, 1))
        self.assertEqual(len(b.settlements), 1)
        self.assertEqual(b.volume_usage["annual"][0]["used_mwh"], 1000)
        self.check_balances(b)

    def test_midmonth_opening_keeps_previously_used_monthly_quota(self):
        day = date(2026, 2, 15)
        b = ledger(opening_date=day, year_used={"solar1": 70}, month_used={"solar1": 40})
        request = meter(start=day, end_exclusive=MAR, market_reference_month="2026-02",
                        claimed_mechanism_mwh=21)
        with self.assertRaisesRegex(ValueError, "Cumulative"):
            b.accrue(request, posting_date=MAR)
        b.accrue(replace(request, claimed_mechanism_mwh=20), posting_date=MAR)
        self.assertEqual(len(b.settlements), 1)
        self.assertEqual(b.volume_usage["monthly"][0]["used_mwh"], 60)

    def test_opening_usage_is_explicit_and_consistent_with_caps_and_dates(self):
        for year, month in (({}, {"solar1": 0}), ({"solar1": 0}, {}),
                            ({"solar1": 0}, {"unknown": 0}), ({"solar1": -1}, {"solar1": 0}),
                            ({"solar1": 20}, {"solar1": 21}), ({"solar1": 101}, {"solar1": 0}),
                            ({"solar1": 70}, {"solar1": 61}), ({"solar1": "NaN"}, {"solar1": 0})):
            with self.subTest(year=year, month=month), self.assertRaises(ValueError):
                ledger(opening_date=date(2026, 2, 15), year_used=year, month_used=month)
        # Neither a month boundary nor an unstarted mechanism can have prior
        # usage in that month. Unknown usage is never silently treated as zero.
        with self.assertRaises(ValueError):
            ledger(opening_date=FEB, year_used={"solar1": 10}, month_used={"solar1": 10})
        with self.assertRaises(ValueError):
            ledger(opening_date=date(2026, 1, 15), year_used={"solar1": 20}, month_used={"solar1": 10})
        with self.assertRaises(ValueError):
            ledger(contracts=[contract(mechanism_start=MAR)], opening_date=FEB,
                   year_used={"solar1": 10}, month_used={"solar1": 0})
        # An annual aggregate cannot be backed by nonexistent monthly rights.
        with self.assertRaises(ValueError):
            ledger(opening_date=APR, year_used={"solar1": 100}, month_used={"solar1": 0},
                   contracts=[contract(monthly_caps_mwh={"2026-01": 10, "2026-04": 100})])

    def test_opening_arrears_are_not_a_proxy_for_opening_used_energy(self):
        c = contract(annual_caps_mwh={2026: 1000},
                     monthly_caps_mwh={"2026-01": 800, "2026-04": 500})
        claim = OpeningObligation("old", "solar1", "system_to_producer", 50,
                                  FEB, "known prior invoice, independent of volume")
        for amount in (0, 100000):
            b = ledger(contracts=[c], opening_date=APR, year_used={"solar1": 800},
                       month_used={"solar1": 0}, opening=[replace(claim, amount_cny=amount)])
            with self.assertRaisesRegex(ValueError, "Cumulative"):
                b.accrue(meter(start=APR, end_exclusive=date(2026, 5, 1),
                    market_reference_month="2026-04", actual_net_export_mwh=300,
                    eligible_net_export_mwh=300, claimed_mechanism_mwh=201),
                    posting_date=date(2026, 5, 1))

    def test_promised_or_ineligible_project_has_no_legal_accrual(self):
        for c in (contract(actual_commissioning_date=None, commissioning_evidence=""),
                  contract(eligible=False), contract(actual_commissioning_date=date(2026, 2, 15))):
            with self.assertRaises(ValueError):quote_settlement(c, meter())
        with self.assertRaises(ValueError):contract(actual_commissioning_date="2025-12-15")

    def test_partial_month_requires_actual_meter_inside_exact_term(self):
        c = contract(actual_commissioning_date=date(2026, 1, 15),
                     mechanism_start=date(2026, 1, 20), mechanism_end_exclusive=date(2026, 2, 15))
        with self.assertRaises(ValueError):quote_settlement(c, meter())
        q = quote_settlement(c, meter(start=date(2026, 1, 20)))
        self.assertEqual(q["mechanism_volume_mwh"], 30)
        with self.assertRaises(ValueError):
            quote_settlement(c, meter(start=FEB, end_exclusive=MAR, market_reference_month="2026-02"))
        quote_settlement(c, meter(start=FEB, end_exclusive=date(2026, 2, 15),
                                  market_reference_month="2026-02"))
        with self.assertRaises(ValueError):
            quote_settlement(c, meter(start=date(2026, 2, 15), end_exclusive=MAR,
                                      market_reference_month="2026-02"))
        with self.assertRaises(ValueError):quote_settlement(contract(), meter(end_exclusive=MAR))

    def test_tax_units_reference_month_method_and_region_must_match(self):
        for changes in (
            dict(price_basis=replace(BASIS, tax_basis="vat_exclusive")),
            dict(price_basis=replace(BASIS, vat_rate=".09")),
            dict(market_reference_month="2026-02"), dict(market_reference_method="wrong mean"),
            dict(region="another_region"), dict(project_id="unknown")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                quote_settlement(contract(), meter(**changes))
        with self.assertRaises(ValueError):replace(BASIS, currency="CNY_per_kWh")
        with self.assertRaises(ValueError):replace(BASIS, energy_basis="gross_generation")

    def test_negative_reference_price_requires_explicit_signed_rule(self):
        negative = meter(market_reference_cny_per_mwh=-50)
        with self.assertRaises(ValueError):quote_settlement(contract(), negative)
        c = contract(negative_market_price_rule="allow_signed")
        self.assertEqual(quote_settlement(c, negative)["signed_producer_accrual_cny"], 13500)
        with self.assertRaises(ValueError):contract(negative_market_price_rule="silently_floor_zero")
        with self.assertRaises(ValueError):contract(negative_price_rule_evidence="")

    def test_green_certificate_and_other_difference_cannot_be_added_on_same_claim(self):
        for changes in (dict(green_certificate_revenue_on_claim_cny=1),
                        dict(other_difference_settlement_on_claim_cny=1),
                        dict(other_difference_settlement_on_claim_cny=-1)):
            with self.assertRaises(ValueError):quote_settlement(contract(), meter(**changes))

    def test_duplicates_overlaps_unknown_project_and_backdating_rejected_atomically(self):
        b = ledger();b.accrue(meter(), posting_date=FEB)
        before = b.obligations, b.settlements, b.balances()
        for m in (meter(), meter(start=date(2026, 1, 15)), meter(project_id="unknown")):
            with self.assertRaises(ValueError):b.accrue(m, posting_date=FEB)
        with self.assertRaises(ValueError):
            b.add_cash(party="system", amount_cny=1, on=JAN, evidence="backdated")
        with self.assertRaises(ValueError):
            b.add_cash(party="unknown", amount_cny=1, on=FEB, evidence="unknown")
        self.assertEqual((b.obligations, b.settlements, b.balances()), before)

    def test_future_meter_or_missing_quota_cannot_be_accrued(self):
        b = ledger()
        with self.assertRaises(ValueError):b.accrue(meter(), posting_date=date(2026, 1, 31))
        with self.assertRaises(ValueError):
            quote_settlement(contract(monthly_caps_mwh={}), meter())
        with self.assertRaises(ValueError):
            contract(annual_caps_mwh={2027: 10})
        self.assertEqual(b.obligations, {})

    def test_opening_arrears_survive_expiry_and_both_sides_close(self):
        c = contract(mechanism_start=date(2025, 1, 1), mechanism_end_exclusive=JAN)
        claims = (OpeningObligation("oldplus", "solar1", "system_to_producer", 70,
                                    date(2025, 12, 1), "verified opening receivable"),
                  OpeningObligation("oldminus", "solar1", "producer_to_system", 30,
                                    date(2025, 12, 1), "verified opening payable"))
        b = ledger(contracts=[c], opening=claims)
        b.pay("oldplus", requested_cny=70, on=FEB)
        b.pay("oldminus", requested_cny=30, on=FEB)
        self.assertEqual(self.check_balances(b)["system"]["cash_cny"], 460)
        with self.assertRaises(ValueError):b.accrue(meter(), posting_date=FEB)
        with self.assertRaises(ValueError):b.pay("oldplus", requested_cny=1, on=FEB)
        with self.assertRaises(ValueError):b.pay("unknown", requested_cny=0, on=FEB)

    def test_nonfinite_money_volume_and_bool_are_rejected_without_mutation(self):
        for value in ("NaN", "Infinity", "-Infinity", float("nan"), True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):contract(mechanism_price_cny_per_mwh=value)
                with self.assertRaises(ValueError):quote_settlement(contract(), meter(market_reference_cny_per_mwh=value))
                with self.assertRaises(ValueError):quote_settlement(contract(), meter(claimed_mechanism_mwh=value))
                b = ledger();before = b.balances()
                with self.assertRaises(ValueError):
                    b.add_cash(party="system", amount_cny=value, on=FEB, evidence="invalid")
                self.assertEqual(b.balances(), before)
                with self.assertRaises(ValueError):ledger(system=value)
                q = b.accrue(meter(), posting_date=FEB)
                before = b.obligations, b.balances()
                with self.assertRaises(ValueError):
                    b.pay(q["obligation_id"], requested_cny=value, on=FEB)
                self.assertEqual((b.obligations, b.balances()), before)
        with self.assertRaises(ValueError):
            quote_settlement(contract(mechanism_price_cny_per_mwh="1e999999"), meter())

    def test_multiple_owners_and_returned_records_cannot_mutate_books(self):
        c2 = contract(project_id="wind2", producer_id="producer2", technology="wind")
        b = ledger(contracts=[contract(), c2])
        q = b.accrue(meter(), posting_date=FEB)
        b.accrue(meter(project_id="wind2", market_reference_cny_per_mwh=500), posting_date=FEB)
        q["amount_cny"] = 0
        copy = b.obligations;copy.clear()
        self.assertEqual(len(b.obligations), 2)
        b.pay(q["obligation_id"], requested_cny=3000, on=FEB)
        balances = self.check_balances(b)
        self.assertEqual(balances["producers"]["producer1"]["cash_cny"], 600)
        self.assertEqual(balances["producers"]["producer2"]["cash_cny"], 100)
        with self.assertRaises(ValueError):ledger(contracts=[contract(), contract()])
        caps = {"2026-01": 60};c = contract(monthly_caps_mwh=caps);caps["2026-01"] = 0
        self.assertEqual(c.monthly_caps_mwh["2026-01"], 60)


if __name__ == "__main__":
    unittest.main()
