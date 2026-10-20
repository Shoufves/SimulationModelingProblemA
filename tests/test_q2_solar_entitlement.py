"""Known solar qualification horizon never becomes the physical asset life."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.q2_solar_entitlement import apply_solar_duration
from energy_model.q2_subsidies import SupportTerms
from energy_model.q2_support_investment import SupportOffer


def offer(technology="solar"):
    return SupportOffer(technology=technology, decision_year=2015, announced_year=2015,
        commissioning_deadline=2016, eligible_years=25, lifetime_hours=25*8760,
        premium_cap_nominal_cny_per_mwh=1000, expected_premium_nominal_cny_per_mwh=400,
        metering_fraction=.9, expected_collection_fraction=.75, expected_payment_delay_years=2,
        expected_real_2024_per_nominal=1, priority=0, evidence="synthetic policy fixture")


def position(online, actor="solar"):
    return dict(terms=SupportTerms(project=f"{actor}/{online}", actor=actor, eligible=True,
        commissioned_year=online, policy_start_year=2015, eligible_years=25, capacity_mw=100,
        lifetime_hours=25*8760, priority=0, evidence="fixture"), prior_lifetime_mwh=12345.)


class SolarEntitlementTests(unittest.TestCase):
    def fixture(self):
        return SimpleNamespace(new_support=SimpleNamespace(awards={}, reserved={},
            offers={(2015, t): offer(t) for t in ("solar", "wind")}),
            positions=[position(2013), position(2014), position(2014,"wind")],
            fund=SimpleNamespace(cash=123., payables={"old":456.}))

    def test_offers_use_twenty_years_without_changing_wind(self):
        policy=self.fixture(); before=deepcopy(policy)
        apply_solar_duration(policy)
        solar=policy.new_support.offers[2015,"solar"]
        self.assertEqual((solar.eligible_years,solar.lifetime_hours),(20,175200))
        self.assertEqual(policy.new_support.offers[2015,"wind"],before.new_support.offers[2015,"wind"])
        self.assertLess(solar.pv_per_mw(lead=1,life=25,gross_full_load_hours=1500,discount_rate=.05),
                        before.new_support.offers[2015,"solar"].pv_per_mw(lead=1,life=25,gross_full_load_hours=1500,discount_rate=.05))

    def test_unknown_older_qualification_is_not_backdated_and_meters_cash_stay(self):
        policy=self.fixture(); before=deepcopy(policy)
        apply_solar_duration(policy)
        self.assertEqual(policy.positions[0],before.positions[0])
        self.assertEqual(policy.positions[1]["terms"].eligible_years,20)
        self.assertEqual(policy.positions[1]["prior_lifetime_mwh"],12345)
        self.assertEqual(policy.positions[2],before.positions[2])
        self.assertEqual(policy.fund.cash,before.fund.cash)
        self.assertEqual(policy.fund.payables,before.fund.payables)

    def test_later_hour_limit_is_not_replaced_by_a_larger_limit(self):
        policy=self.fixture()
        policy.new_support.offers[2015,"solar"]=replace(offer(),eligible_years=15,lifetime_hours=22000)
        apply_solar_duration(policy)
        self.assertEqual(policy.new_support.offers[2015,"solar"].lifetime_hours,22000)
        self.assertEqual(policy.new_support.offers[2015,"solar"].eligible_years,15)

    def test_repeat_configuration_is_idempotent(self):
        policy=self.fixture()
        self.assertTrue(apply_solar_duration(policy))
        self.assertEqual(apply_solar_duration(policy),[])

    def test_existing_commitments_cannot_be_silently_rewritten(self):
        policy=self.fixture();policy.new_support.reserved={2015:123.}
        with self.assertRaisesRegex(ValueError,"before commitment"):
            apply_solar_duration(policy)

    def test_without_new_programme_inherited_terms_still_corrected(self):
        policy=self.fixture();policy.new_support=None
        apply_solar_duration(policy)
        self.assertEqual(policy.positions[1]["terms"].eligible_years,20)


if __name__ == "__main__": unittest.main()
