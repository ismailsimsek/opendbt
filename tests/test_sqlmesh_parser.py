import json
import unittest

import semver
from dbt.exceptions import DbtRuntimeError

from base_dbt_test import BaseDbtTest
from opendbt import OpenDbtProject, OpenDbtCli
from opendbt.examples import email_dbt_test_callback


class BaseParserTest(BaseDbtTest):

    def test_parser_build(self):
        dp = OpenDbtProject(project_dir=self.DBTCORE_DIR, profiles_dir=self.DBTCORE_DIR)
        dp.run(command="parse")
        manifes = dp.manifest()
        node = manifes.nodes.get("model.dbtcore.my_second_dbt_model")
        self.assertIsNotNone(node)
        print(node.depends_on.nodes)
        print(node.sources)
        # NOTE: my_core_table1 is parsed by sqlmesh it is hardcoded schema.tablename value!!
        # self.assertIn('model.dbtcore.my_core_table1', node.sources)
        self.assertIn('model.dbtcore.my_core_table1', node.depends_on.nodes)
