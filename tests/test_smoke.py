import unittest
from core.pipeline import ContentAutomationPipeline, PipelineContext

class PipelineSmokeTest(unittest.TestCase):
    def test_pipeline_smoke(self):
        context = PipelineContext(payload={"status": "ready"})
        self.assertEqual(ContentAutomationPipeline().run(context), context)
