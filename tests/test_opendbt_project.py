import json
from pathlib import Path

from base_dbt_test import BaseDbtTest
from opendbt import OpenDbtProject


class TestOpenDbtProject(BaseDbtTest):
    def test_run_compile(self):
        dp = OpenDbtProject(project_dir=self.DBTCORE_DIR, profiles_dir=self.DBTCORE_DIR)
        dp.run(command="compile")

    def test_run_run(self):
        dp = OpenDbtProject(project_dir=self.DBTCORE_DIR, profiles_dir=self.DBTCORE_DIR)
        dp.run(command="run",
               args=['--select', '+my_second_dbt_model+', "--exclude", "my_failing_dbt_model"],
               use_subprocess=True)

    def test_run_build(self):
        dp = OpenDbtProject(project_dir=self.DBTCORE_DIR, profiles_dir=self.DBTCORE_DIR)
        dp.run(command="run", args=["--exclude", "my_failing_dbt_model"])
        dp.run(command="run", args=["--exclude", "my_failing_dbt_model"])
        manifest_str = self.DBTCORE_DIR.joinpath('target').joinpath('manifest.json').read_text()
        manifest = json.loads(manifest_str)
        assert "model.dbtcore.my_core_table1" in manifest.get("parent_map").get("model.dbtcore.my_second_dbt_model")
        node = manifest.get("nodes").get("model.dbtcore.my_second_dbt_model")
        assert "model.dbtcore.my_core_table1" in node.get("depends_on_nodes")

    def test_project_attributes(self):
        dp = OpenDbtProject(project_dir=self.DBTCORE_DIR, profiles_dir=self.DBTCORE_DIR)
        self.assertEqual(dp.project.profile_name, "dbtcore")
        self.assertEqual(dp.project_vars['dbt_custom_adapter'], 'opendbt.examples.DuckDBAdapterV2Custom')
