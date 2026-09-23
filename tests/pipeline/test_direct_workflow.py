"""The manual production workflow cannot start Manus or select another provider."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class DirectWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / '.github/workflows/fetch-manus.yml').read_text(encoding='utf-8')
        cls.blocks = re.split(r'\n      - ', cls.workflow)
        cls.pipeline = next(block for block in cls.blocks if '\n        id: direct-pipeline\n' in block)

    def input_block(self, name):
        match = re.search(rf'^      {name}:\n(.*?)(?=^      \w+:|^\S|\Z)',
                          self.workflow, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_only_manual_full_direct_route_is_exposed_and_executed(self):
        triggers = self.workflow.split('\npermissions:', 1)[0]
        self.assertIn('\n  workflow_dispatch:', triggers)
        self.assertNotRegex(triggers, r'(?m)^  (?:schedule|push|pull_request|workflow_run):')
        self.assertNotRegex(triggers, r'(?m)^\s*-?\s*cron:')
        for name, value in (('stage', 'all'), ('source_mode', 'direct-only')):
            block = self.input_block(name)
            self.assertIn(f'options: [{value}]', block)
            self.assertIn(f'default: {value}', block)
        self.assertIn('args=(run --window-mode rolling-24h --stage all --source-mode direct-only --skip-search)',
                      self.pipeline)
        self.assertIn('python scripts/run_pipeline.py "${args[@]}"', self.pipeline)
        self.assertNotIn('INPUT_STAGE', self.pipeline)
        self.assertNotIn('INPUT_SOURCE_MODE', self.pipeline)
        self.assertNotIn('--manus-credit-limit', self.pipeline)
        self.assertNotRegex(triggers, r'(?m)^      (?:manus_credit_limit|skip_search):')

    def test_processing_uses_only_paratera_deepseek_without_provider_fallback(self):
        self.assertIn('DEEPSEEK_API_KEY: ${{ secrets.PARATERA_API_KEY }}', self.pipeline)
        self.assertIn('LLM_API_BASE: https://llmapi.paratera.com/v1\n', self.pipeline)
        self.assertIn('LLM_MODEL: DeepSeek-V4-Pro\n', self.pipeline)
        for legacy in ('MANUS_API_KEY', 'TAVILY_API_KEY', 'secrets.DEEPSEEK_API_KEY',
                       'vars.LLM_API_BASE', 'vars.LLM_MODEL', 'api.deepseek.com', 'deepseek-v4-flash'):
            self.assertNotIn(legacy, self.pipeline)

    def test_company_manus_quota_and_live_credentials_are_absent(self):
        for text in ('company_index.discovery', 'company-discovery/quota.json',
                     'company-discovery-day-', 'company-quota-confirm', 'COMPANY_DISCOVERY_QUOTA_READY',
                     'TAVILY_API_KEY'):
            self.assertNotIn(text, self.workflow)
        # The old Manus secret may remain solely as a recovery encryption key.
        for block in self.blocks:
            if 'automation.recovery pack' not in block:
                self.assertNotIn('secrets.MANUS_API_KEY', block)
        self.assertNotRegex(self.workflow, r'(?m)^\s+MANUS_API_KEY:')

    def test_research_lease_recovery_and_publication_contracts_remain(self):
        for suffix in ('restore', 'reserve', 'save', 'confirm', 'ready'):
            self.assertIn(f'id: company-research-{suffix}', self.workflow)
        self.assertIn('COMPANY_RESEARCH_BUDGET_READY:', self.pipeline)
        recovery = next(block for block in self.blocks if 'automation.recovery pack' in block)
        self.assertIn('PIPELINE_RECOVERY_KEY: ${{ secrets.PIPELINE_RECOVERY_KEY || secrets.PARATERA_API_KEY || secrets.DEEPSEEK_API_KEY || secrets.MANUS_API_KEY }}', recovery)
        self.assertIn('always() && !inputs.dry_run', recovery)
        self.assertIn('python scripts/test_pipeline.py offline', self.workflow)
        self.assertIn('git push', self.workflow)
        self.assertIn('gh workflow run deploy-pages.yml --ref main', self.workflow)
        self.assertIn('work/publication-receipt.json', self.workflow)


if __name__ == '__main__':
    unittest.main()
