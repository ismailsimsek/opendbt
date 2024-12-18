import logging
import os
import sys
from pathlib import Path

######################
from opendbt.dbt import patch_dbt

patch_dbt()
from opendbt.utils import Utils
######################

from dbt.cli.main import dbtRunner as DbtCliRunner
from dbt.cli.main import dbtRunnerResult
from dbt.config import PartialProject
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.results import RunResult
from dbt.exceptions import DbtRuntimeError
from dbt.task.base import get_nearest_project_dir


class OpenDbtLogger:
    _log = None

    @property
    def log(self) -> logging.Logger:
        if self._log is None:
            self._log = logging.getLogger(name="opendbt")
            if not self._log.hasHandlers():
                handler = logging.StreamHandler(sys.stdout)
                formatter = logging.Formatter("[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s")
                handler.setFormatter(formatter)
                handler.setLevel(logging.INFO)
                self._log.addHandler(handler)
        return self._log


class OpenDbtCli:

    def __init__(self, project_dir: Path, profiles_dir: Path = None, callbacks: list = None):
        self.project_dir: Path = Path(get_nearest_project_dir(project_dir.as_posix()))
        self.profiles_dir: Path = profiles_dir
        self._project: PartialProject = None
        self._user_callbacks = callbacks if callbacks else []
        self._project_callbacks = None

    @property
    def project(self) -> PartialProject:
        if not self._project:
            self._project = PartialProject.from_project_root(project_root=self.project_dir.as_posix(),
                                                             verify_version=True)

        return self._project

    @property
    def project_dict(self) -> dict:
        return self.project.project_dict

    @property
    def project_vars(self) -> dict:
        """
        :return: dict: Variables defined in the `dbt_project.yml` file, `vars`.
                Note:
                    This method only retrieves global project variables specified within the `dbt_project.yml` file.
                    Variables passed via command-line arguments are not included in the returned dictionary.
        """
        if 'vars' in self.project_dict:
            return self.project_dict['vars']

        return {}

    @property
    def project_callbacks(self):
        if not self._project_callbacks:
            self._project_callbacks = self._user_callbacks
            if 'dbt_callbacks' in self.project_vars:
                for _callback_module in str(self.project_vars['dbt_callbacks']).split(','):
                    _project_callback = Utils.import_module_attribute_by_name(_callback_module)
                    self._project_callbacks.append(_project_callback)

        return self._project_callbacks

    def invoke(self, args: list, callbacks: list = None) -> dbtRunnerResult:
        """
        Run dbt with the given arguments.

        :param args: The arguments to pass to dbt.
        :param callbacks:
        :return: The result of the dbt run.
        """
        run_callbacks = self.project_callbacks + callbacks if callbacks else self.project_callbacks
        run_args = args if args else []
        if "--project-dir" not in run_args:
            run_args += ["--project-dir", self.project_dir.as_posix()]
        if "--profiles-dir" not in run_args and self.profiles_dir:
            run_args += ["--profiles-dir", self.profiles_dir.as_posix()]
        return self.run(args=run_args, callbacks=run_callbacks)

    @staticmethod
    def run(args: list, callbacks: list = None) -> dbtRunnerResult:
        """
        Run dbt with the given arguments.

        :param callbacks:
        :param args: The arguments to pass to dbt.
        :return: The result of the dbt run.
        """
        callbacks = callbacks if callbacks else []
        # https://docs.getdbt.com/reference/programmatic-invocations
        dbtcr = DbtCliRunner(callbacks=callbacks)
        result: dbtRunnerResult = dbtcr.invoke(args)
        if result.success:
            return result

        if result.exception:
            raise result.exception

        # take error message and raise it as exception
        for _result in result.result:
            _result: RunResult
            _result_messages = ""
            if _result.status == 'error':
                _result_messages += f"{_result_messages}\n"
            if _result_messages:
                raise DbtRuntimeError(msg=_result.message)

        raise DbtRuntimeError(msg=f"DBT execution failed!")

    def manifest(self, partial_parse=True, no_write_manifest=True) -> Manifest:
        args = ["parse"]
        if partial_parse:
            args += ["--partial-parse"]
        if no_write_manifest:
            args += ["--no-write-json"]

        result = self.invoke(args=args)
        if isinstance(result.result, Manifest):
            return result.result

        raise Exception(f"DBT execution did not return Manifest object. returned:{type(result.result)}")

    def generate_docs(self, args: list = None):
        _args = ["docs", "generate"] + args if args else []
        self.invoke(args=_args)


class OpenDbtProject(OpenDbtLogger):
    """
    This class is used to take action on a dbt project.
    """

    DEFAULT_TARGET = 'dev'  # development

    def __init__(self, project_dir: Path, target: str = None, profiles_dir: Path = None, args: list = None):
        super().__init__()
        self.project_dir: Path = project_dir
        self.profiles_dir: Path = profiles_dir
        self.target: str = target if target else self.DEFAULT_TARGET
        self.args = args if args else []
        self.cli: OpenDbtCli = OpenDbtCli(project_dir=self.project_dir, profiles_dir=self.profiles_dir)

    @property
    def project(self) -> PartialProject:
        return self.cli.project

    @property
    def project_dict(self) -> dict:
        return self.cli.project_dict

    @property
    def project_vars(self) -> dict:
        return self.cli.project_vars

    def run(self, command: str = "build", target: str = None, args: list = None, use_subprocess: bool = False,
            write_json: bool = False) -> dbtRunnerResult:

        run_args = args if args else []
        run_args += ["--target", target if target else self.target]
        run_args += ["--project-dir", self.project_dir.as_posix()]
        if self.profiles_dir:
            run_args += ["--profiles-dir", self.profiles_dir.as_posix()]
        run_args = [command] + run_args + self.args
        if write_json:
            run_args.remove("--no-write-json")

        if use_subprocess:
            shell = False
            self.log.info(f"Working dir: {os.getcwd()}")
            py_executable = sys.executable if sys.executable else 'python'
            self.log.info(f"Python executable: {py_executable}")
            __command = [py_executable, '-m', 'opendbt'] + run_args
            self.log.info(f"Running command (shell={shell}) `{' '.join(__command)}`")
            Utils.runcommand(command=__command)
            return None

        self.log.info(f"Running `dbt {' '.join(run_args)}`")
        return self.cli.invoke(args=run_args)

    def manifest(self, partial_parse=True, no_write_manifest=True) -> Manifest:
        return self.cli.manifest(partial_parse=partial_parse, no_write_manifest=no_write_manifest)

    def generate_docs(self, args: list = None):
        return self.cli.generate_docs(args=args)
