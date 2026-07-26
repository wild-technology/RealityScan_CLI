#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import logging
import argparse
import inquirer

from module_base.parameter import Parameter
from module_base.rs_module import RSModule
from module_base.settings_store import SettingsStore
from modules.extract_images.extract_images import ExtractImages
from modules.georeference.georeference_images import GeoreferenceImages
from modules.preprocess_images.preprocess_images import PreprocessImages
from modules.image_batcher.batch_directory import BatchDirectory
from modules.realityscan_interface.realityscan_interface import RealityScanAlignment

def initialize_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    return logger

def initialize_modules(logger) -> dict[str, RSModule]:
    """
    Initializes the modules and returns a dict of the active modules.

    Honors optional environment variables (restored from RC_Main; the
    inquirer checkbox requires a real terminal, which automated drivers
    do not have):
    - RS_MODULES: comma-separated list of module display names to enable
    - RS_NO_INTERACTIVE: truthy value enables all modules (or the
      RS_MODULES selection) without prompting
    """
    available_modules: dict[str, RSModule] = {
        'Extract Images': ExtractImages(logger),
        'Georeference Images': GeoreferenceImages(logger),
        'Preprocess Images': PreprocessImages(logger),
        'Batch Directory': BatchDirectory(logger),
        'RealityScan Alignment': RealityScanAlignment(logger)
    }

    no_interactive = os.environ.get('RS_NO_INTERACTIVE', '').strip().lower() in ('1', 'true', 'yes', 'y')
    modules_env = os.environ.get('RS_MODULES')
    if no_interactive or modules_env:
        if modules_env:
            wanted = [m.strip() for m in modules_env.split(',') if m.strip()]
            unknown = [m for m in wanted if m not in available_modules]
            if unknown:
                logger.error(f'RS_MODULES names unknown modules: {unknown}. '
                             f'Valid names: {list(available_modules.keys())}')
                sys.exit(1)
            return {name: mod for name, mod in available_modules.items()
                    if name in wanted}
        return dict(available_modules)

    module_choices = [
        inquirer.Checkbox(
            'modules',
            message='Select modules to enable (arrow keys to move, space to select, enter to confirm)',
            choices=list(available_modules.keys()),
            default=list(available_modules.keys()),
            carousel=True
        )
    ]

    answers = inquirer.prompt(module_choices)
    if answers is None:
        # user cancelled (Ctrl-C) or no interactive terminal
        sys.exit(1)

    enabled_modules: dict[str, RSModule] = {}
    for name, mod in available_modules.items():
        if name in answers.get('modules', []):
            enabled_modules[name] = mod

    return enabled_modules

def initialize_parameters(modules) -> dict[str, Parameter]:
    """
    Initializes the parameters and returns a dict of the active parameters.
    """
    params: dict[str, Parameter] = {}

    # Global Parameters
    params['output_dir'] = Parameter(
        name='Output Directory',
        cli_short='o',
        cli_long='output_dir',
        type=str,
        default_value=None,
        description='Path to the output directory',
        prompt_user=True
    )

    params['continue_automatically'] = Parameter(
        name='Continue Automatically',
        cli_short='c',
        cli_long='continue_automatically',
        type=bool,
        default_value=False,
        description='Whether to continue automatically after each module',
        prompt_user=True
    )

    # Module-specific parameters
    for module in modules.values():
        for pname, p in module.get_parameters().items():
            disable = p.disable_when_module_active
            if disable is not None:
                if isinstance(disable, list):
                    if any(m in modules for m in disable):
                        continue
                else:
                    if disable in modules:
                        continue
            params[pname] = p

    return params

def parse_arguments(argv, params, logger) -> None:
    """
    Parses CLI args and prompts for any missing values.

    Prompted values are persisted to rs_settings.json (section "main") and
    offered as the default on the next run - press enter to reuse them.
    """
    def str_to_bool(value: str) -> bool:
        # argparse with type=bool would treat any non-empty string
        # (including "False") as True
        return value.strip().lower() in ('true', 't', 'yes', 'y', '1')

    parser = argparse.ArgumentParser()
    for p in params.values():
        arg_type = str_to_bool if p.get_type() is bool else p.get_type()
        # argparse %-expands help text at print_help() time, so a literal
        # percent in a description (e.g. "96.3% -> 89.6%") crashes --help
        # and every argparse error path. Descriptions stay human-readable
        # for the interactive prompts; the escaping belongs here.
        parser.add_argument(f'-{p.cli_short}', f'--{p.cli_long}',
                            type=arg_type,
                            help=p.get_description().replace('%', '%%'))
    args = parser.parse_args(argv[1:])

    settings = SettingsStore()

    for p in params.values():
        val = getattr(args, p.cli_long, None)
        if val is None and p.prompt_user:
            last_value = settings.get('main', p.cli_long, p.get_default_value())
            prompt = f'{p.get_description()}'
            if last_value is not None:
                prompt += f' [{last_value}]'
            try:
                inp = input(f'{prompt}: ').strip()
                if not inp and last_value is not None:
                    val = last_value
                elif p.get_type() is bool:
                    val = inp.lower() in ('true', 't', 'yes', 'y')
                else:
                    val = p.get_type()(inp)
            except EOFError:
                # Unattended run (stdin closed / hidden console): take the
                # stored default silently - same convention as the module
                # prompts (Windows trap registry: isatty() lies, input()
                # must always be EOF-safe).
                logger.info(f'Non-interactive: {p.get_name()} = {last_value}')
                val = last_value
            except ValueError:
                logger.warning(f'Invalid value for {p.get_name()}, using default {p.get_default_value()}')
                val = p.get_default_value()
            if val is not None:
                settings.set('main', p.cli_long, val)
        if val is None and not p.prompt_user:
            val = p.get_default_value()
        p.set_value(val)

def update_parameters(params, modules) -> None:
    """
    Injects the global params dict into each module.
    """
    for mod in modules.values():
        mod.set_params(params)

def log_output_data(logger, output_data: dict[str, object], indent: int = 0) -> None:
    """
    Recursively logs output data.
    """
    pad = '  ' * indent
    for key, val in output_data.items():
        if isinstance(val, dict):
            logger.info(f'{pad}{key}:')
            log_output_data(logger, val, indent + 1)
        else:
            logger.info(f'{pad}{key}: {val}')

def main(argv) -> None:
    logger = initialize_logger()
    modules = initialize_modules(logger)
    params = initialize_parameters(modules)
    parse_arguments(argv, params, logger)
    update_parameters(params, modules)

    logger.info("Parameters:")
    for name, p in params.items():
        logger.info(f'  {name} ({p.cli_short}): {p.get_value()}')

    overall_data: dict[str, object] = {}
    for idx, mod in enumerate(modules.values()):
        ok, msg = mod.validate_parameters()
        if not ok:
            # sys.exit(1), NOT a bare return: a bare return exits 0, so an
            # unattended caller gating on exit status reads a refused run as
            # success. Surfaced 2026-07-26 when the batcher correctly refused
            # to reuse zones built from a different flight log and main.py
            # still reported 0 - the same silent-failure shape as the
            # module-failure branch below, which has always exited 1.
            logger.error(msg)
            sys.exit(1)

        logger.info(f'Running module: {mod.get_name()}')
        out = mod.run()
        mod.finish()
        logger.info(f'Finished module: {mod.get_name()}')
        overall_data[mod.get_name()] = out or {}

        # A failed module must stop the chain: running downstream modules
        # against its missing/partial output wastes hours and produces
        # results that look complete (observed: georeference failure ->
        # preprocess ran anyway -> batcher aborted on a missing flight log).
        if isinstance(out, dict) and out.get('Success') is False:
            logger.error(f'Module {mod.get_name()} reported failure; '
                         'stopping the pipeline here.')
            logger.info("Output Data:")
            log_output_data(logger, overall_data)
            sys.exit(1)

        if not params['continue_automatically'].get_value() and idx < len(modules) - 1:
            # isatty() lies under hidden consoles and redirected pipes, so
            # this gate cannot be reached only when a human is present.
            # Unattended, stdin is at EOF immediately: continue rather than
            # crash the chain between two modules that both succeeded
            # (observed on the H2024 run - georeference finished 8,197/8,197
            # and the pipeline died here before preprocessing).
            try:
                input("Press enter to continue...")
            except EOFError:
                logger.info('No console attached - continuing automatically.')

    logger.info("Output Data:")
    log_output_data(logger, overall_data)

if __name__ == '__main__':
    main(sys.argv)
