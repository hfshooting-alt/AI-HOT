"""A privacy policy's data hosting location is not company-country evidence."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from company_index.page_evidence import eligible_fact


class ResearchCountryGate(unittest.TestCase):
    def fact(self, quote):
        return {'field': 'country', 'value': '美国', 'quote': quote,
                'url': 'https://example.com/privacy', 'title': 'Privacy'}

    def test_observed_openrouter_server_transfer_quote_is_rejected(self):
        quote = ('When you access our Site or Service, your personal data may be '
                 'transferred to our servers in the US')
        fact = self.fact(quote)
        original = copy.deepcopy(fact)
        self.assertIsNone(eligible_fact(fact, {'company_name': 'OpenRouter'}))
        self.assertEqual(fact, original)

    def test_explicit_hosting_and_data_processing_locations_are_rejected(self):
        for quote in ('Our data is stored in the United States.',
                      'We process personal information in the United States.',
                      'Our data centres are located in the United States.',
                      'Our server address is in the United States.',
                      '用户数据将传输至美国服务器。', '我们的服务器地址位于美国。',
                      '我们在美国存储数据。'):
            with self.subTest(quote=quote):
                self.assertIsNone(eligible_fact(self.fact(quote), {'company_name': 'Example'}))

    def test_company_hq_office_and_address_evidence_is_preserved(self):
        for quote in ('Example headquarters are in the United States.',
                      'Example has an office in San Francisco, United States.',
                      'Company address: 123 Main Street, San Francisco, CA, United States.',
                      'Example is incorporated in the United States.',
                      'Example总部位于美国，服务器也设在美国。',
                      'Example办公地址为美国加州，数据存储使用第三方服务。',
                      'Example office: San Francisco, United States. We also operate US servers.'):
            with self.subTest(quote=quote):
                fact = self.fact(quote)
                self.assertEqual(eligible_fact(fact, {'company_name': 'Example'}), fact)

    def test_unrelated_business_field_is_not_changed_by_country_gate(self):
        fact = self.fact('Example operates data centres in the United States.')
        fact.update(field='business', value='运营数据中心')
        self.assertEqual(eligible_fact(fact, {'company_name': 'Example'}), fact)


if __name__ == '__main__':
    unittest.main()
