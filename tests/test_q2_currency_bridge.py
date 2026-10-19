"""Currency direction, missingness and vintage separation before model use."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_q2_currency_bridge as bridge
import build_workspace_catalog as catalog


class CurrencyBridgeTests(unittest.TestCase):
    def test_known_exchange_and_inflation_hand_calculation(self):
        rows = bridge.conversion_factors({2008: 5., 2014: 10.}, {2008: 100., 2014: 200.})
        row = rows[-1]
        self.assertAlmostEqual(row['USD2008_per_CNY_nominal'], .05)
        # 2CNY/kWh *1000 /10CNYperUSD /2inflation /1e6 =0.0001millionUSD/MWh.
        self.assertAlmostEqual(2 * row['tariff_CNY_per_kWh_to_million_USD2008_per_MWh'], .0001)
        self.assertEqual(row['tax_treatment'], 'unchanged; no VAT removal')

    def test_missing_or_misaligned_year_cannot_be_filled(self):
        with self.assertRaisesRegex(ValueError, 'Matched annual'):
            bridge.conversion_factors({2008: 5., 2014: 10.}, {2008: 100.})
        with self.assertRaisesRegex(ValueError, 'positive'):
            bridge.conversion_factors({2008: 0.}, {2008: 100.})

    def test_missing_duplicate_or_foreign_observation_rejected(self):
        source = json.loads((ROOT / 'data/raw/q2/wdi_us_gdp_deflator_2008_2024.json').read_text(encoding='utf-8'))
        bridge.series(source, 'NY.GDP.DEFL.ZS', 'USA', 2008, 2024)
        for mutation in ('missing', 'duplicate', 'country'):
            document = deepcopy(source)
            if mutation == 'missing':
                document[1][0]['value'] = None
            elif mutation == 'duplicate':
                document[1][-1]['date'] = document[1][0]['date']
            else:
                document[1][0]['countryiso3code'] = 'CHN'
            with self.assertRaises(ValueError):
                bridge.series(document, 'NY.GDP.DEFL.ZS', 'USA', 2008, 2024)

    def test_index_rebasing_preserves_real_conversion(self):
        fx = {2008: 6., 2014: 8.}
        original = bridge.conversion_factors(fx, {2008: 80., 2014: 100.})
        rebased = bridge.conversion_factors(fx, {2008: 160., 2014: 200.})
        for a, b in zip(original, rebased):
            self.assertEqual(a['USD2008_per_CNY_nominal'], b['USD2008_per_CNY_nominal'])

    def test_catalog_reuse_requires_same_registered_public_original_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'data/raw/existing/fx.json'
            original.parent.mkdir(parents=True)
            original.write_text('original', encoding='utf-8')
            relative = original.relative_to(root).as_posix()
            source = dict(source_key='yx:FX', canonical_path=relative, file_available=True, sha256=catalog.sha(original))
            row = dict(path=relative, sha256=source['sha256'], reuse_source_key='yx:FX')
            self.assertEqual(catalog.scoped_original('q2', row, [source], root), relative)
            for key, value in [('reuse_source_key', 'yx:unknown'), ('sha256', 'wrong'), ('path', 'data/restricted/fx.json')]:
                changed = dict(row, **{key: value})
                with self.assertRaisesRegex(ValueError, 'without verified reuse'):
                    catalog.scoped_original('q2', changed, [source], root)
            original.write_text('changed', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'without verified reuse'):
                catalog.scoped_original('q2', row, [source], root)


if __name__ == '__main__':
    unittest.main()
