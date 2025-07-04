from typing import Any, Dict, Optional, Union

import sqlglot
from dbt.compilation import Compiler
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.graph.nodes import ManifestSQLNode, ModelNode, SourceDefinition
from sqlglot import exp

from opendbt.logger import OpenDbtLogger
from opendbt.runtime_patcher import PatchClass


@PatchClass(module_name="dbt.compilation", target_name="Compiler")
class OpendbtCompiler(Compiler, OpenDbtLogger):
    """
    Patches the dbt Compiler to add static SQL parsing for dependency resolution.

    This allows opendbt to discover `ref` and `source` dependencies from plain
    SQL table references, even if they are not defined using dbt's Jinja functions.
    """

    def compile_node(
        self,
        node: ManifestSQLNode,
        manifest: Manifest,
        extra_context: Optional[Dict[str, Any]] = None,
        write: bool = True,
        split_suffix: Optional[str] = None,
    ) -> ManifestSQLNode:
        """
        Compiles a node and then parses the compiled SQL to find undeclared
        dependencies, adding them to the node's dependency list.
        """
        self.log.debug(f"OpenDBT compiler processing node: {node.unique_id}")

        # Use the parent compiler to render the Jinja into SQL
        super().compile_node(
            node=node,
            manifest=manifest,
            extra_context=extra_context,
            write=False,  # We'll write the file later after modifications
            split_suffix=split_suffix,
        )

        # Parse the compiled SQL to find and add static dependencies
        self._find_and_add_static_dependencies(node=node, manifest=manifest)

        # After modifying dependencies, rebuild the manifest's internal lookups
        manifest.rebuild_ref_lookup()
        manifest.build_parent_and_child_maps()

        if write:
            self._write_node(node, split_suffix=split_suffix)

        self.log.debug(
            f"Finished processing node {node.unique_id}. "
            f"Final dependencies: {node.depends_on.nodes}"
        )
        return node

    def _find_and_add_static_dependencies(
        self, node: "ManifestSQLNode", manifest: Manifest
    ) -> None:
        """
        Parses the node's compiled SQL to find table references and add them as
        dependencies.
        """
        if not node.compiled_code:
            self.log.debug(
                f"Node '{node.name}' has no compiled code, skipping static parsing."
            )
            return

        try:
            dialect = self.config.credentials.type
            expressions = sqlglot.parse(node.compiled_code, read=dialect)
        except Exception as e:
            self.log.warning(
                f"SQLglot failed to parse node '{node.name}'. "
                f"Static dependencies may be incomplete. Error: {e}"
            )
            return

        if not expressions:
            self.log.debug(
                f"SQLglot parsing for '{node.name}' returned no expressions."
            )
            return

        for expression in expressions:
            try:
                # Get all CTE names to avoid treating them as table dependencies
                cte_names = {
                    cte.this.alias_or_name.lower()
                    for cte in expression.find_all(exp.CTE)
                }
            except Exception as e:
                self.log.warning(
                    f"Failed to extract CTEs from node '{node.name}'. "
                    f"Static dependency resolution may be incorrect. Error: {e}"
                )
                cte_names = set()

            for table in expression.find_all(exp.Table):
                table_name = table.this.name.lower()
                if table_name in cte_names:
                    self.log.debug(
                        f"Skipping '{table_name}' in '{node.name}' as it is a CTE."
                    )
                    continue

                schema_name = table.db if table.db else node.schema
                table_name = table.name if table.name else node.alias
                dep_node = self._resolve_table_as_dependency(manifest, schema_name, table_name)

                if dep_node:
                    if dep_node.unique_id not in node.depends_on.nodes:
                        node.depends_on.nodes.append(dep_node.unique_id)
                        self.log.info(
                            f"Found static {dep_node.resource_type} dependency: '{dep_node.name}' and added it to '{node.name}'"
                        )
                else:
                    self.log.debug(
                        f"Could not resolve table reference '{table.sql()}' in "
                        f"node '{node.name}' to a dbt resource."
                    )

    def _resolve_table_as_dependency(
        self, manifest: Manifest, schema_name: str, table_name: str
    ) -> Optional[Union[ModelNode, SourceDefinition]]:
        """
        Tries to resolve a table reference to a dbt model or source using dbt's
        internal finders by constructing potential ref/source calls.
        """
        # A list of potential ways the table could be referenced in dbt.
        # We try to resolve them in order of specificity.
        possible_dep_calls = [f"ref('{schema_name}.{table_name}')", f"ref('{table_name}')", f"source('{schema_name}', '{table_name}')", ]

        for dep_call in possible_dep_calls:
            try:
                # Use dbt's internal method to resolve a ref/source string
                dep_node = manifest.find_node_from_ref_or_source(dep_call)
                if dep_node:
                    self.log.debug(f"Resolved '{dep_call}' to node {dep_node.unique_id}")
                    return dep_node
            except Exception:
                # This can fail if the ref is ambiguous, etc. We can ignore it and try the next one.
                self.log.debug(f"Could not resolve potential dependency: {dep_call}", exc_info=False)

        return None